import pytest

from app import policy, trust


def rec(agent, human):
    return {"login": "x", "agent": agent, "human": human, "ts": "t"}


MATCH = rec("release", "approve")
GOOD = [MATCH] * 10


def sim(*kinds):
    return {"by_kind": [{"kind": f"k{i}", **k} for i, k in enumerate(kinds)]}


GOOD_SIM = sim({"cases": 4, "works": 3, "thin": 1, "fails": 0, "relevant_pct": 80})


def make(decisions=GOOD, findings=(), simulation=GOOD_SIM, lessons=()):
    return trust.gates(decisions, list(findings), simulation, list(lessons))


def by_key(gate_list):
    return {g["key"]: g for g in gate_list}


def test_agreement_counts_each_kind():
    a = trust.agreement([rec("release", "approve"), rec("hold", "reject"), rec("drop", "reject"),
                         rec("release", "reject"), rec("hold", "approve"), rec("drop", "approve")])
    assert a == {"n": 6, "agree": 3, "rate": 0.75, "false_release": 1, "false_hold": 2}  # 3 of 4 judged calls


def test_agreement_empty_and_window():
    assert trust.agreement([]) == {"n": 0, "agree": 0, "rate": 0.0, "false_release": 0, "false_hold": 0}
    old_mistakes = [rec("release", "reject")] * 5
    a = trust.agreement(old_mistakes + [MATCH] * 3, window=3)  # newest records are last
    assert (a["n"], a["agree"], a["false_release"]) == (3, 3, 0)
    assert trust.agreement([MATCH, rec("hold", "approve")], window=0)["n"] == 0


def test_agreement_rate_is_rounded():
    assert trust.agreement([MATCH, MATCH, rec("release", "reject")])["rate"] == 0.67


def test_gate_order_and_all_pass():
    g = make()
    assert [x["key"] for x in g] == ["self_check", "agreement", "false_release", "simulation", "regressions"]
    assert [x["layer"] for x in g] == ["checked", "checked", "enforced", "checked", "enforced"]
    assert all(x["passed"] for x in g)
    assert all(isinstance(x[k], str) for x in g for k in ("label", "value", "target"))


def test_self_check_gate():
    assert by_key(make(findings=[]))["self_check"]["value"] == "0 problems"
    g = by_key(make(findings=[{"rule": "a"}] * 3))["self_check"]
    assert (g["passed"], g["value"]) == (False, "3 problems")


def test_agreement_gate():
    ok = by_key(make())["agreement"]
    assert ok["passed"] and ok["value"] == "10 matched, 0 wrong releases, 0 held that you approved"
    low = by_key(make([MATCH] * 8 + [rec("release", "reject")] * 2))["agreement"]  # 0.8 < 0.9
    assert not low["passed"] and low["value"] == "8 matched, 2 wrong releases, 0 held that you approved"
    cautious = by_key(make([MATCH] * 8 + [rec("hold", "approve")] * 2))["agreement"]  # caution is not error
    assert cautious["passed"]
    few = by_key(make([MATCH] * 3))["agreement"]
    assert not few["passed"] and few["value"] == "3 of 8 decisions needed"
    edge = by_key(make([MATCH] * 9 + [rec("hold", "approve")]))["agreement"]  # exactly 0.9
    assert edge["passed"]


def test_agreement_gate_uses_the_window_only():
    old = [rec("release", "reject")] * 10
    assert by_key(make(old + GOOD * 2))["agreement"]["passed"]


def test_false_release_gate():
    ok = by_key(make())["false_release"]
    assert ok["passed"] and ok["value"] == "0 messages you would have stopped"
    bad = by_key(make(GOOD + [rec("release", "reject")]))["false_release"]
    assert not bad["passed"] and bad["value"] == "1 message you would have stopped"
    # a mistake that has scrolled out of the window no longer counts
    assert by_key(make([rec("release", "reject")] + GOOD * 3))["false_release"]["passed"]


def test_false_hold_does_not_fail_false_release():
    assert by_key(make(GOOD + [rec("hold", "approve")]))["false_release"]["passed"]


def test_simulation_gate():
    none = by_key(make(simulation=None))["simulation"]
    assert not none["passed"] and none["value"] == "not run yet"
    assert not by_key(make(simulation={"by_kind": []}))["simulation"]["passed"]
    ok = by_key(make())["simulation"]
    assert ok["passed"] and ok["value"] == "80% relevant"
    low = by_key(make(simulation=sim({"cases": 4, "works": 1, "thin": 0, "fails": 3, "relevant_pct": 40})))
    assert not low["simulation"]["passed"]


def test_simulation_average_is_case_weighted_and_skips_all_fail_kinds():
    mixed = sim({"cases": 3, "works": 3, "thin": 0, "fails": 0, "relevant_pct": 90},
                {"cases": 1, "works": 0, "thin": 1, "fails": 0, "relevant_pct": 30})
    g = by_key(make(simulation=mixed))["simulation"]
    assert g["passed"] and g["value"] == "75% relevant"  # (90*3 + 30*1) / 4
    # a kind where every case fails (relevant_pct 0) must not drag the average down
    with_dead = sim({"cases": 2, "works": 2, "thin": 0, "fails": 0, "relevant_pct": 70},
                    {"cases": 10, "works": 0, "thin": 0, "fails": 10, "relevant_pct": 0})
    assert by_key(make(simulation=with_dead))["simulation"]["passed"]
    only_dead = sim({"cases": 5, "works": 0, "thin": 0, "fails": 5, "relevant_pct": 0})
    g = by_key(make(simulation=only_dead))["simulation"]
    assert not g["passed"] and g["value"] == "no usable cases"
    no_cases = sim({"cases": 0, "works": 0, "thin": 0, "fails": 0, "relevant_pct": 100})
    assert not by_key(make(simulation=no_cases))["simulation"]["passed"]


def test_regressions_gate():
    ok = by_key(make(lessons=[{"status": "open"}, {"status": "fixed", "regressed": True}]))["regressions"]
    assert ok["passed"] and ok["value"] == "0 fixed mistakes came back"
    bad = by_key(make(lessons=[{"status": "open", "regressed": True}]))["regressions"]
    assert not bad["passed"] and bad["value"] == "1 fixed mistake came back"


def test_thresholds_are_adjustable():
    g = by_key(trust.gates([MATCH] * 3, [], GOOD_SIM, [], min_decisions=3, min_rate=1.0, min_relevant_pct=90))
    assert g["agreement"]["passed"] and not g["simulation"]["passed"]


@pytest.mark.parametrize("requested", ["shadow", "supervised"])
def test_level_low_requests_always_allowed(requested):
    for gate_list in (make(), make(findings=[{"rule": "a"}], simulation=None)):
        r = trust.level(requested, gate_list)
        assert (r["level"], r["requested"], r["allowed"], r["blocked_by"]) == (requested, requested, True, [])
        assert r["note"]


def test_level_autopilot_needs_every_gate():
    r = trust.level("autopilot", make())
    assert (r["level"], r["allowed"], r["blocked_by"]) == ("autopilot", True, [])
    r = trust.level("autopilot", make(findings=[{"rule": "a"}]))
    assert (r["level"], r["requested"], r["allowed"]) == ("supervised", "autopilot", False)
    assert r["blocked_by"] == ["Self-check is clean"] and "Self-check is clean" in r["note"]
    r = trust.level("autopilot", make([MATCH] * 3, simulation=None))
    assert r["blocked_by"] == ["Agent matches your decisions", "Simulation finds relevant leads"]


def test_level_unknown_raises():
    with pytest.raises(ValueError):
        trust.level("turbo", make())


def test_demote_on_enforced_failure():
    d = trust.demote("autopilot", make(GOOD + [rec("release", "reject")]))
    assert d["level"] == "supervised" and "No release you would have stopped" in d["reason"]
    d = trust.demote("autopilot", make(lessons=[{"status": "open", "regressed": True}]))
    assert d["level"] == "supervised" and "No fixed mistake came back" in d["reason"]


def test_no_demotion_for_checked_failure_or_other_levels():
    assert trust.demote("autopilot", make(findings=[{"rule": "a"}], simulation=None)) is None
    assert trust.demote("autopilot", make()) is None
    bad = make(GOOD + [rec("release", "reject")])
    assert trust.demote("supervised", bad) is None
    assert trust.demote("shadow", bad) is None


def test_to_policy_mode_maps_to_modes_policy_knows():
    assert trust.to_policy_mode("autopilot") == "autopilot"
    assert trust.to_policy_mode("shadow") == "supervised"
    assert trust.to_policy_mode("supervised") == "supervised"
    assert all(trust.to_policy_mode(name) in policy.MODES for name in trust.LEVELS)
