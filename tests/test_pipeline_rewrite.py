"""The Reviewer's catches get repaired: a deterministic number guard, then one bounded rewrite from the evidence."""
import os

os.environ.setdefault("GRAPH_PATH", "/tmp/earshot-test.kuzu")

from app import autopilot, pipeline, reviewer  # noqa: E402

LEAD = {"login": "derek", "name": "Derek Ng", "company": "Acme",
        "signals": [{"repo": "o/r", "created": "2026-11-01", "title": "Usage billing breaks",
                     "body": "We bill 3,000 customers and invoices drift by 2% every month."}]}


# --- guard -------------------------------------------------------------------------------

def test_guard_keeps_numbers_the_person_wrote():
    body = "You bill 3000 customers. Your invoices drift by 2%. Would a short call help?"
    assert reviewer.guard(body, reviewer.full_evidence(LEAD)) == (body, [])


def test_guard_strips_numbers_and_money_the_person_never_wrote():
    body = "Hi Derek, you raised invoice drift. You lose $40k a quarter on it. Acme has 12 engineers on billing. Would a call help?"
    out, removed = reviewer.guard(body, reviewer.full_evidence(LEAD))
    assert removed == ["You lose $40k a quarter on it.", "Acme has 12 engineers on billing."]
    assert out == "Hi Derek, you raised invoice drift. Would a call help?"


def test_guard_keeps_a_suffixed_number_the_person_wrote_and_cuts_a_changed_one():
    # Found by scripts/eval_tools.py: "40k" was read as a bare "40" and an honest sentence was cut.
    lead = {**LEAD, "signals": [{**LEAD["signals"][0], "body": "We send about 40k usage events a day and 2m on peak."}]}
    body = "You send about 40k usage events a day. You see 2m on peak days. Would a short call help?"
    assert reviewer.guard(body, reviewer.full_evidence(lead)) == (body, [])
    changed = "You send about 50k usage events a day. You raised late events. Would a short call help?"
    assert reviewer.guard(changed, reviewer.full_evidence(lead))[1] == ["You send about 50k usage events a day."]


def test_guard_leaves_numbers_not_about_the_recipient():
    body = "You raised invoice drift. Our tool handles 10M events a day. Would a call help?"
    assert reviewer.guard(body, reviewer.full_evidence(LEAD))[1] == []


def test_guard_never_empties_a_draft():
    body = "You lose $40k a quarter. Want to talk?"
    assert reviewer.guard(body, reviewer.full_evidence(LEAD)) == (body, [])


# --- repair ------------------------------------------------------------------------------

def _fail(*s):
    return {"login": "derek", "verdict": "fail", "claims": [], "unsupported": list(s)}


def _judge(bad):
    """Fails any question whose sentence contains `bad`."""
    return lambda state, qs: {k: 0.0 if bad in q else 1.0 for k, q in qs.items()}


def test_flagged_then_passes_is_replaced_and_marked_repaired():
    lead = {**LEAD, "subject": "Invoice drift", "body": "You lose $40k. You raised invoice drift."}
    reviews, calls = {"derek": _fail("You lose $40k.")}, []

    def rewrite(l, flagged):
        calls.append(flagged)
        assert "3,000 customers" in reviewer.evidence(l)  # full text, not the excerpt
        return "Invoice drift", "You raised invoice drift. Would a call help?"
    n = reviewer.repair([lead], reviews, rewrite, _judge("$40k"))
    assert n == {"rewritten": 1, "passed": 1, "held": 0} and calls == [["You lose $40k."]]
    assert lead["body"] == "You raised invoice drift. Would a call help?"
    assert reviews["derek"]["verdict"] == "pass" and reviews["derek"]["repaired"] is True
    assert reviews["derek"]["removed"] == ["You lose $40k."]


def test_flagged_then_still_fails_keeps_the_original_hold():
    lead = {**LEAD, "subject": "s", "body": "You lose $40k."}
    first = _fail("You lose $40k.")
    reviews, calls = {"derek": first}, []
    n = reviewer.repair([lead], reviews, lambda l, f: calls.append(1) or ("s", "You lose $40k, sadly."), _judge("$40k"))
    assert n == {"rewritten": 1, "passed": 0, "held": 1} and len(calls) == reviewer.MAX_REWRITES_PER_DRAFT == 1
    assert reviews["derek"] is first and lead["body"] == "You lose $40k."


def test_rewrite_raising_or_unchecked_or_empty_never_counts_as_passed():
    for rewrite, judge in [(lambda l, f: (_ for _ in ()).throw(RuntimeError("down")), _judge("x")),
                           (lambda l, f: ("s", "You raised drift."), lambda s, q: (_ for _ in ()).throw(RuntimeError())),
                           (lambda l, f: ("s", ""), _judge("x"))]:
        lead, first = {**LEAD, "subject": "s", "body": "You lose $40k."}, _fail("You lose $40k.")
        reviews = {"derek": first}
        assert reviewer.repair([lead], reviews, rewrite, judge)["passed"] == 0
        assert reviews["derek"] is first and lead["body"] == "You lose $40k."


def test_drafts_that_passed_or_were_unchecked_are_never_rewritten():
    leads = [{**LEAD, "login": "a", "body": "x"}, {**LEAD, "login": "b", "body": "y"}, {**LEAD, "login": "c", "body": "z"}]
    reviews = {"a": {"verdict": "pass", "unsupported": []}, "b": {"verdict": "unchecked", "reason": "E"}}
    calls = []
    n = reviewer.repair(leads, reviews, lambda l, f: calls.append(l) or ("s", "b"), _judge("x"))
    assert calls == [] and n == {"rewritten": 0, "passed": 0, "held": 0}


# --- pipeline wiring ---------------------------------------------------------------------

def test_repair_drafts_saves_the_repaired_review_and_says_so(monkeypatch):
    st = {"reviews": {"derek": _fail("You lose $40k."), "ok": {"verdict": "pass", "unsupported": []}}}
    saved, said = [], []
    monkeypatch.setattr(autopilot, "load", lambda: st)
    monkeypatch.setattr(autopilot, "save", saved.append)
    monkeypatch.setattr(pipeline, "say", said.append)
    asked = []
    monkeypatch.setattr(pipeline, "ask", lambda schema, system, user: asked.append(user) or pipeline.Rewrite(
        subject="Invoice drift", body="You raised invoice drift. Would a call help?"))
    lead = {**LEAD, "subject": "Invoice drift", "body": "You lose $40k.", "_guard_removed": ["You have 9 staff."]}
    pipeline.repair_drafts([lead, {**LEAD, "login": "ok", "body": "fine"}], judge=_judge("$40k"))
    assert len(asked) == 1 and "- You lose $40k." in asked[0] and "3,000 customers" in asked[0]
    assert saved and st["reviews"]["derek"]["repaired"] and st["reviews"]["derek"]["guard_removed"] == ["You have 9 staff."]
    assert said == ["Reviewer → Writer: 1 drafts claimed more than the evidence shows; rewrote them from the evidence. "
                    "1 now pass, 0 held for you."]


def test_a_rewrite_that_breaks_a_writing_rule_is_not_kept(monkeypatch):
    st = {"reviews": {"derek": _fail("You lose $40k.")}}
    monkeypatch.setattr(autopilot, "load", lambda: st)
    monkeypatch.setattr(autopilot, "save", lambda s: None)
    monkeypatch.setattr(pipeline, "say", lambda m: None)
    monkeypatch.setattr(pipeline, "ask", lambda *a: pipeline.Rewrite(subject="Hi [Name]", body="You raised drift."))
    lead = {**LEAD, "subject": "s", "body": "You lose $40k."}
    pipeline.repair_drafts([lead], judge=_judge("$40k"))
    assert lead["body"] == "You lose $40k." and st["reviews"]["derek"]["verdict"] == "fail"


def test_run_completes_when_the_rewrite_step_cannot_even_load_state(monkeypatch, tmp_path):
    lead = {**LEAD, "url": "https://github.com/derek", "subject": "s", "body": "You lose $40k.", "reason": "r",
            "score": 80, "tier": "A", "stage": "Matched", "draft_status": "pending", "_guard_removed": [],
            "signals": [{**LEAD["signals"][0], "id": "o/r#1", "url": "https://github.com/o/r/issues/1",
                         "excerpt": "x", "pain": "p", "match": 0.9}]}
    monkeypatch.setattr(pipeline, "build_leads", lambda *a, **k: ({"repos": {}}, [lead]))
    monkeypatch.setattr(pipeline, "ICP_PATH", str(tmp_path / "icp.json"))
    monkeypatch.setattr(pipeline.billing, "reset", lambda: None)
    monkeypatch.setattr(pipeline.billing, "record", lambda *a, **k: None)
    monkeypatch.setattr(autopilot, "load", lambda: (_ for _ in ()).throw(OSError("disk")))
    pipeline.run("d", review=lambda leads: None)
    assert pipeline.state["error"] == "" and pipeline.state["log"][-1].startswith("Done:")
    assert any("the first review stands" in m for m in pipeline.state["log"])
