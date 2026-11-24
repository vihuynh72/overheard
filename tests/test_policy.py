import datetime

import pytest

from app.policy import DEFAULT_POLICY, decide, make_rule, rule_matches, suggest_rule, summarize, validate

TODAY = datetime.date(2026, 11, 24)

LEAD = {
    "login": "x", "name": "Xavier Li", "company": "Acme", "role": "CTO", "location": "Berlin",
    "tier": "A", "score": 78, "email_status": "valid", "production": True, "newest": "2026-10-01",
    "reason": "Asked about usage-based billing.", "subject": "Your billing question",
    "body": "Saw your issue on usage metering.",
    "signals": [{"repo": "getlago/lago", "title": "Metering lag", "excerpt": "events arrive late"}],
}
AUTOPILOT = {**validate({}), "mode": "autopilot", "approved_first_batch": True}


def run(lead=None, policy=None, rules=(), findings=(), sent=0):
    return decide({**LEAD, **(lead or {})}, {**AUTOPILOT, **(policy or {})}, list(rules), list(findings), sent, TODAY)


def rule(field, op, value, action="hold", reason="r"):
    return make_rule(field, op, value, action, reason)


def test_clean_release_in_autopilot():
    assert run() == {"action": "release", "reasons": []}


@pytest.mark.parametrize("kwargs,reason", [
    ({"rules": [rule("company", "equals", "acme", reason="Known competitor")]}, "Known competitor"),
    ({"findings": [{"login": "x", "rule": "placeholder", "detail": "d"}]}, "Failed self-check: placeholder"),
    ({"lead": {"score": 42}}, "Score 42 is below your minimum of 50"),
    ({"lead": {"email_status": "unknown"}}, "No verified email address"),
    ({"policy": {"require_production_use": True}, "lead": {"production": False}}, "No sign of production use"),
    ({"lead": {"newest": "2020-01-01"}}, "Evidence is older than 730 days"),
    ({"lead": {"newest": "garbage"}}, "Evidence is older than 730 days"),
    ({"policy": {"never_say": ["metering"]}}, "Draft contains a phrase you banned: metering"),
    ({"sent": 20}, "Daily send limit of 20 reached"),
    ({"policy": {"mode": "supervised"}}, "You review every message in supervised mode"),
    ({"policy": {"approved_first_batch": False}}, "Waiting for you to approve the first batch"),
])
def test_each_hold_branch(kwargs, reason):
    assert run(**kwargs) == {"action": "hold", "reasons": [reason]}


def test_other_leads_findings_are_ignored():
    assert run(findings=[{"login": "someone-else", "rule": "placeholder", "detail": "d"}])["action"] == "release"


def test_hold_rule_that_does_not_match_is_ignored():
    assert run(rules=[rule("company", "equals", "globex")])["action"] == "release"


def test_drop_wins_over_everything():
    rules = [rule("company", "equals", "acme", "hold", "held"), rule("role", "equals", "cto", "drop", "Not our buyer")]
    got = run(lead={"score": 1, "email_status": ""}, policy={"mode": "supervised"}, rules=rules, sent=99)
    assert got == {"action": "drop", "reasons": ["Not our buyer"]}


def test_reasons_are_collected_together():
    got = run(lead={"score": 10, "email_status": ""}, policy={"mode": "supervised"},
              rules=[rule("tier", "equals", "a", reason="Tier A needs a look")])
    assert got["action"] == "hold"
    assert got["reasons"] == [
        "Tier A needs a look", "Score 10 is below your minimum of 50", "No verified email address",
        "You review every message in supervised mode",
    ]


def test_validate_defaults_and_cleaning():
    assert validate({}) == DEFAULT_POLICY
    assert validate({"mode": "autopilot", "bogus": 1})["mode"] == "autopilot"
    assert "bogus" not in validate({"bogus": 1})
    clean = validate({"never_say": ["  Hope You’re WELL ", "x" * 100] + ["a"] * 60})
    assert clean["never_say"][0] == "hope you’re well"
    assert len(clean["never_say"]) == 50 and len(clean["never_say"][1]) == 80
    assert DEFAULT_POLICY["never_say"] == []


@pytest.mark.parametrize("bad", [
    {"mode": "yolo"}, {"min_score": -1}, {"min_score": 101}, {"min_score": "50"},
    {"daily_send_limit": -1}, {"max_evidence_age_days": -5},
    {"never_say": "hello"}, {"never_say": [1]}, {"never_say": ["ok", "  "]},
])
def test_validate_rejects(bad):
    with pytest.raises(ValueError):
        validate(bad)


@pytest.mark.parametrize("field,op,value,expected", [
    ("company", "equals", "  ACME ", True), ("company", "equals", "acm", False),
    ("role", "contains", "ct", True), ("location", "contains", "paris", False),
    ("login", "equals", "X", True), ("name", "contains", "xavier", True), ("tier", "equals", "a", True),
    ("company", "not_contains", "globex", True), ("company", "not_contains", "cme", False),
    ("repo", "equals", "GetLago/Lago", True), ("repo", "contains", "lago", True),
    ("repo", "not_contains", "lago", False), ("repo", "equals", "other/repo", False),
    ("text", "contains", "usage-based", True), ("text", "contains", "metering lag", True),
    ("text", "contains", "arrive late", True), ("text", "not_contains", "agency", True),
    ("text", "not_contains", "billing", False),
])
def test_rule_matches(field, op, value, expected):
    assert rule_matches(rule(field, op, value), LEAD) is expected


def test_rule_matches_missing_field_is_empty():
    assert rule_matches(rule("location", "equals", "berlin"), {"login": "y"}) is False
    assert rule_matches(rule("location", "not_contains", "berlin"), {"login": "y"}) is True


def test_make_rule_shape():
    r = make_rule("company", "equals", " Acme ", "drop", "why")
    assert r["value"] == "Acme" and r["source"] == "founder" and len(r["id"]) == 8
    assert set(r) == {"id", "field", "op", "value", "action", "reason", "source"}
    assert make_rule("tier", "equals", "C", "hold", "why")["id"] != r["id"]


@pytest.mark.parametrize("args", [
    ("salary", "equals", "x", "hold"), ("company", "matches", "x", "hold"),
    ("company", "equals", "x", "send"), ("company", "equals", "  ", "hold"), ("company", "equals", None, "hold"),
])
def test_make_rule_rejects(args):
    with pytest.raises(ValueError):
        make_rule(*args, "why")


def test_summarize():
    decisions = {
        "a": {"action": "release", "reasons": []},
        "b": {"action": "hold", "reasons": ["No verified email address", "Score 10 is below your minimum of 50"]},
        "c": {"action": "hold", "reasons": ["No verified email address"]},
        "d": {"action": "drop", "reasons": ["Known competitor"]},
        "e": {"action": "hold", "reasons": ["Score 11 is below your minimum of 50"]},
    }
    got = summarize(decisions)
    assert (got["release"], got["hold"], got["drop"]) == (1, 3, 1)
    assert got["top_reasons"][0] == ["No verified email address", 2]
    assert ["Score 10 is below your minimum of 50", 1] in got["top_reasons"]
    assert ["Score 11 is below your minimum of 50", 1] in got["top_reasons"]
    assert len(got["top_reasons"]) == 4


def test_summarize_caps_at_five_and_handles_empty():
    many = {str(i): {"action": "hold", "reasons": [f"r{i}"]} for i in range(8)}
    assert len(summarize(many)["top_reasons"]) == 5
    assert summarize({}) == {"release": 0, "hold": 0, "drop": 0, "top_reasons": []}


@pytest.mark.parametrize("said,word", [
    ("They run an Agency", "agency"), ("just a consultant", "consultan"), ("Hobby project", "hobby"),
    ("looks like a student", "student"), ("It's a personal project", "personal project"),
])
def test_suggest_rule_holds_on_text(said, word):
    r = suggest_rule(LEAD, said)
    assert (r["field"], r["op"], r["value"], r["action"], r["source"]) == ("text", "contains", word, "hold", "suggested")
    assert said in r["reason"]


@pytest.mark.parametrize("said", ["competitor of ours", "He works at a rival"])
def test_suggest_rule_drops_competitor_company(said):
    r = suggest_rule(LEAD, said)
    assert (r["field"], r["op"], r["value"], r["action"], r["source"]) == ("company", "equals", "Acme", "drop", "suggested")
    assert said in r["reason"]


def test_suggest_rule_none_cases():
    assert suggest_rule(LEAD, "just not a fit") is None
    assert suggest_rule({**LEAD, "company": ""}, "competitor") is None
