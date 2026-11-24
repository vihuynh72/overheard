import re
from types import SimpleNamespace

import pytest

from app import lessons, simulate

PRODUCT = {"key": "p1", "name": "P", "kind": "devtool", "description": "First sentence. Second one.",
           "repo": "a/b", "expect": "strong", "why": "w", "known_buyers": []}
FOUNDER = {"key": "detailed", "label": "d", "rewrite": lambda d: d}
ICP = {"product": "P", "pains": ["billing is hard"]}


def lead(i, score=80, company="Acme", email_status="valid", match=0.6, newest="2026-01-01"):
    return {"login": f"u{i}", "name": f"U{i}", "company": company, "email": "", "email_status": email_status,
            "score": score, "tier": "A" if score >= 70 else "B" if score >= 50 else "C", "fit": 70,
            "reason": "r", "stage": "Matched", "subject": "Hello there", "body": "Saw your issue.",
            "draft_status": "pending", "newest": newest,
            "signals": [{"id": f"x/y#{i}", "url": "https://github.com/x/y/issues/1", "title": "t",
                         "excerpt": "e", "match": match}]}


def fake_build(n, calls=None):
    def build(description, repo="", *, say=None, contact=True, index="issues"):
        if calls is not None:
            calls.append({"description": description, "repo": repo, "contact": contact, "index": index})
        say("working")
        return ICP, [lead(i, score=90 - i) for i in range(n)]
    return build


def fake_ask(relevant_first=None, outcome="no_reply"):
    """Answers relevant for the first `relevant_first` judge calls (all when None)."""
    state = {"n": 0}

    def ask(schema, system, user):
        if schema is simulate.Judgement:
            state["n"] += 1
            ok = relevant_first is None or state["n"] <= relevant_first
            return SimpleNamespace(relevant=ok, reason="because")
        return SimpleNamespace(outcome=outcome, reason="because")
    return ask


def result(**kw):
    base = {"product": "p1", "kind": "k", "founder": "detailed", "expect": "weak", "ok": True, "error": "",
            "leads": 6, "tiers": {"A": 6, "B": 0, "C": 0}, "with_company": 6, "with_valid_email": 0,
            "findings": {}, "median_match": 0.5, "median_age_days": 10, "judged": 6, "relevant": 6,
            "replies": {}, "recall": None, "verdict": "works", "log": []}
    base.update(kw)
    return base


# run_case

def test_run_case_normal_result():
    calls = []
    r = simulate.run_case(PRODUCT, FOUNDER, fake_build(8, calls), fake_ask(outcome="interested"), sample=6)
    assert r["ok"] and r["error"] == "" and r["leads"] == 8 and r["judged"] == 6 and r["relevant"] == 6
    assert r["verdict"] == "works" and r["replies"] == {"interested": 6}
    assert r["tiers"] == {"A": 8, "B": 0, "C": 0} and r["with_company"] == 8 and r["with_valid_email"] == 8
    assert r["median_match"] == 0.6 and r["median_age_days"] > 0 and r["recall"] is None
    assert r["log"] == ["working"] and r["product"] == "p1" and r["founder"] == "detailed"


def test_build_gets_contact_false_and_per_case_index():
    calls = []
    simulate.run_case(PRODUCT, FOUNDER, fake_build(1, calls), fake_ask())
    assert calls == [{"description": PRODUCT["description"], "repo": "a/b", "contact": False,
                      "index": "sim-p1-detailed"}]


def test_founder_rewrite_is_applied_to_the_description():
    calls = []
    founder = {"key": "one_liner", "label": "x", "rewrite": lambda d: "short"}
    simulate.run_case(PRODUCT, founder, fake_build(1, calls), fake_ask())
    assert calls[0]["description"] == "short" and calls[0]["index"] == "sim-p1-one_liner"


def test_only_top_sample_by_score_is_judged():
    seen = []

    def ask(schema, system, user):
        seen.append(user)
        return SimpleNamespace(relevant=True, reason="r", outcome="no_reply")
    simulate.run_case(PRODUCT, FOUNDER, fake_build(10), ask, sample=3)
    assert len(seen) == 6  # 3 judged + 3 replies


def test_judge_does_not_see_score_or_tier():
    seen = []

    def ask(schema, system, user):
        seen.append((schema, user))
        return SimpleNamespace(relevant=True, reason="r")
    simulate.judge_lead(lead(1, score=87), ICP, ask)
    assert "87" not in seen[0][1] and "tier" not in seen[0][1].lower() and "billing is hard" in seen[0][1]


def test_recall_when_known_buyers():
    product = {**PRODUCT, "known_buyers": ["Acme", "Zed"]}
    r = simulate.run_case(product, FOUNDER, fake_build(3), fake_ask())
    assert r["recall"]["found"] == ["Acme"] and r["recall"]["missed"] == ["Zed"]


def test_runtime_error_is_a_valid_failing_result():
    def build(*a, **k):
        raise RuntimeError("no public issues found to search")
    r = simulate.run_case(PRODUCT, FOUNDER, build, fake_ask())
    assert r["ok"] is True and r["leads"] == 0 and r["verdict"] == "fails"
    assert r["error"] == "no public issues found to search"


def test_unexpected_exception_is_not_ok():
    def build(*a, **k):
        raise ValueError("boom")
    r = simulate.run_case(PRODUCT, FOUNDER, build, fake_ask())
    assert r["ok"] is False and "boom" in r["error"] and r["verdict"] == "fails"


def test_model_failure_while_judging_is_not_ok():
    def ask(*a):
        raise RuntimeError("rate limited")
    r = simulate.run_case(PRODUCT, FOUNDER, fake_build(3), ask)
    assert r["ok"] is False and "rate limited" in r["error"]


@pytest.mark.parametrize("leads,judged,relevant,verdict", [
    (5, 5, 3, "works"), (5, 5, 2, "thin"), (10, 10, 6, "works"), (10, 10, 5, "thin"),
    (10, 10, 3, "thin"), (10, 10, 2, "fails"), (4, 4, 4, "thin"), (4, 4, 0, "thin"),
    (1, 1, 0, "thin"), (0, 0, 0, "fails"), (6, 6, 0, "fails"),
])
def test_verdict_thresholds(leads, judged, relevant, verdict):
    assert simulate._verdict(leads, judged, relevant) == verdict


def test_verdict_end_to_end_with_partial_relevance():
    r = simulate.run_case(PRODUCT, FOUNDER, fake_build(8), fake_ask(relevant_first=3), sample=6)
    assert r["relevant"] == 3 and r["judged"] == 6 and r["verdict"] == "thin"


# run_matrix

def test_run_matrix_one_result_per_pair_and_callback():
    products = [{**PRODUCT, "key": "a"}, {**PRODUCT, "key": "b"}, {**PRODUCT, "key": "c"}]
    founders = [FOUNDER, {"key": "one_liner", "label": "o", "rewrite": lambda d: d}]
    got = []
    out = simulate.run_matrix(products, founders, fake_build(2), fake_ask(), workers=2, on_result=got.append)
    assert len(out) == 6 and len(got) == 6
    assert {(r["product"], r["founder"]) for r in out} == {(p["key"], f["key"]) for p in products for f in founders}


# scorecard

def test_scorecard_grouping_percentages_and_surprises():
    rs = [
        result(kind="dev", product="a", expect="strong", verdict="works", leads=8, judged=6, relevant=5,
               replies={"interested": 2, "annoyed": 2}),
        result(kind="dev", product="b", expect="strong", verdict="thin", leads=2, judged=2, relevant=1,
               replies={"no_reply": 2}),
        result(kind="app", product="c", expect="none", verdict="fails", leads=0, judged=0, relevant=0),
        result(kind="app", product="d", expect="none", verdict="works", founder="jargon", leads=6),
    ]
    card = simulate.scorecard(rs)
    assert card["cases"] == 4
    dev = next(r for r in card["by_kind"] if r["kind"] == "dev")
    assert dev == {"kind": "dev", "cases": 2, "works": 1, "thin": 1, "fails": 0, "avg_leads": 5.0,
                   "relevant_pct": 75, "interested_pct": 33, "annoyed_pct": 33}
    assert {r["founder"] for r in card["by_founder"]} == {"detailed", "jargon"}
    assert card["surprises"] == [
        {"product": "b", "founder": "detailed", "expect": "strong", "verdict": "thin"},
        {"product": "d", "founder": "jargon", "expect": "none", "verdict": "works"}]
    assert len(card["fit"]) == 2 and any("dev" in s for s in card["fit"])


def test_fit_sentences_follow_the_numbers():
    rs = [result(kind="good"), result(kind="bad", verdict="fails", leads=0, judged=0, relevant=0),
          result(kind="mixed"), result(kind="mixed", verdict="fails")]
    fit = {k: next(s for s in simulate.scorecard(rs)["fit"] if f" {k}" in s) for k in ("good", "bad", "mixed")}
    assert fit["good"].startswith("Overheard fits")
    assert fit["bad"].startswith("Overheard does not fit")
    assert fit["mixed"].startswith("Overheard partly fits")


# derive_lessons

def patterns(rs):
    return {x["kind"]: x["pattern"] for x in simulate.derive_lessons(rs)}


def test_no_lessons_for_a_healthy_matrix():
    assert simulate.derive_lessons([result(), result(product="p2")]) == []


def test_lesson_when_a_kind_always_fails():
    rs = [result(kind="local", verdict="fails", leads=0, judged=0, relevant=0),
          result(kind="local", product="p2", verdict="fails", leads=0, judged=0, relevant=0)]
    (x,) = simulate.derive_lessons(rs)
    assert x["pattern"] == "no public tracker ecosystem for local"
    assert "tell the founder before spending credits" in x["fix"] and x["evidence"]["kind"] == "local"


def test_no_ecosystem_lesson_needs_every_case_to_fail():
    rs = [result(kind="k", verdict="fails", leads=0, judged=0, relevant=0), result(kind="k", product="p2")]
    assert "no_ecosystem" not in patterns(rs)


def test_lesson_when_a_founder_persona_is_worse_than_detailed():
    rs = [result(product="a"), result(product="b"),
          result(product="a", founder="jargon", verdict="thin"),
          result(product="b", founder="jargon", verdict="fails"),
          result(product="a", founder="one_liner"), result(product="b", founder="one_liner")]
    p = [x for x in simulate.derive_lessons(rs) if x["kind"] == "founder_degrades"]
    assert [x["pattern"] for x in p] == ["jargon descriptions degrade results"]
    assert p[0]["fix"] == "ask a follow-up question at intake"


def test_lesson_when_a_check_rule_fires_in_over_20_percent_of_leads():
    rs = [result(leads=10, findings={"placeholder": 3, "bad_email": 2})]
    assert patterns(rs) == {"check_rule": "check rule placeholder fires in over 20% of leads"}
    assert simulate.derive_lessons([result(leads=10, findings={"placeholder": 2})]) == []


def test_lesson_when_annoyed_replies_exceed_25_percent():
    (x,) = simulate.derive_lessons([result(replies={"annoyed": 4, "no_reply": 8})])
    assert x["kind"] == "annoyed_replies" and "tighten the reviewer" in x["fix"]
    assert simulate.derive_lessons([result(replies={"annoyed": 3, "no_reply": 9})]) == []


def test_lesson_when_matches_are_loose():
    (x,) = simulate.derive_lessons([result(kind="k", judged=6, relevant=2, verdict="thin")])
    assert x["kind"] == "loose_matches" and "raise the match threshold" in x["fix"]
    assert simulate.derive_lessons([result(judged=6, relevant=3)]) == []


def test_lesson_when_the_pipeline_crashed():
    rs = [result(product="vague", ok=False, error="ValueError: boom", verdict="fails", leads=0, judged=0, relevant=0)]
    (x,) = simulate.derive_lessons(rs)
    assert x["pattern"] == "pipeline crashed on vague" and "ValueError: boom" in x["fix"]


def test_record_lessons_dedupes_across_runs(tmp_path):
    path = tmp_path / "l.jsonl"
    rs = [result(replies={"annoyed": 5})]
    simulate.record_lessons(rs, path=path)
    simulate.record_lessons(rs, path=path)
    (row,) = lessons.all(path=path)
    assert row["seen"] == 2


# catalogue

def test_founder_rewrites_are_deterministic_and_different():
    d = PRODUCT["description"]
    outs = {f["key"]: f["rewrite"](d) for f in simulate.FOUNDERS}
    assert outs == {f["key"]: f["rewrite"](d) for f in simulate.FOUNDERS}
    assert len(set(outs.values())) == 4
    assert outs["detailed"] == d and outs["one_liner"] == "First sentence."
    assert outs["jargon"].endswith(d) and outs["wrong_audience"].startswith(d)
    assert "non-technical executive" in outs["wrong_audience"]


def test_products_have_required_shape():
    assert len(simulate.PRODUCTS) == 10
    assert len({p["key"] for p in simulate.PRODUCTS}) == 10
    for p in simulate.PRODUCTS:
        assert {"key", "name", "kind", "description", "repo", "expect", "why", "known_buyers"} <= p.keys()
        assert p["expect"] in ("strong", "weak", "none")
        assert p["repo"] == "" or re.fullmatch(r"[\w.-]+/[\w.-]+", p["repo"])
        assert 3 <= p["description"].count(". ") + 1 <= 5 or p["key"] == "vague"
        assert p["name"] == "Flexprice" or p["name"].startswith("Fictional: ")


def test_flexprice_case_is_exact():
    p = next(p for p in simulate.PRODUCTS if p["key"] == "flexprice")
    assert p["repo"] == "flexprice/flexprice" and p["expect"] == "strong"
    assert p["known_buyers"] == ["Vercel", "Supabase", "Replit", "Pinecone", "Baseten", "Chroma",
                                 "Mistral AI", "Laravel", "Cerebrium", "Porter", "Webflow", "Miro", "PagerDuty"]


def test_reply_simulation_normalises_unknown_outcomes():
    ask = lambda schema, system, user: SimpleNamespace(outcome="weird", reason="r")  # noqa: E731
    assert simulate.simulate_reply(lead(1), ICP, ask)["outcome"] == "no_reply"
