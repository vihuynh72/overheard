import copy

import pytest

from app.checks import check_leads, rediscovery

STAGES = ["Matched", "Contacted", "Replied", "Closed/Lost"]

CLEAN = {
    "login": "x", "name": "X", "url": "https://github.com/x", "company": "", "email": "",
    "score": 78, "tier": "A", "fit": 72, "reason": "Asked about usage-based billing.",
    "stage": "Matched", "stage_actor": "agent", "subject": "Your billing question",
    "body": "Saw your issue on usage metering. We built something for that.",
    "draft_status": "pending",
    "signals": [{
        "id": "getlago/lago#12", "url": "https://github.com/getlago/lago/issues/12",
        "title": "t", "excerpt": "e", "created": "2026-02-26", "pain": "p",
        "match": 0.61, "repo": "getlago/lago",
    }],
}


def rules(**changes):
    lead = copy.deepcopy(CLEAN)
    lead.update(changes)
    return [f["rule"] for f in check_leads([lead], STAGES)]


def test_clean_lead_has_no_findings():
    assert check_leads([CLEAN], STAGES) == []


def test_finding_shape():
    lead = {**CLEAN, "reason": ""}
    (f,) = check_leads([lead], STAGES)
    assert f["login"] == "x" and f["rule"] == "no_reason" and f["detail"]


@pytest.mark.parametrize("changes,rule", [
    ({"signals": []}, "no_evidence"),
    ({"signals": [{**CLEAN["signals"][0], "url": "http://github.com/a/b/issues/1"}]}, "no_evidence"),
    ({"score": 101}, "score_range"),
    ({"score": -1}, "score_range"),
    ({"score": "78"}, "score_range"),
    ({"tier": "B"}, "tier_mismatch"),
    ({"reason": ""}, "no_reason"),
    ({"subject": ""}, "empty_draft"),
    ({"body": ""}, "empty_draft"),
    ({"subject": " ".join(["w"] * 13)}, "long_subject"),
    ({"body": " ".join(["w"] * 131)}, "long_body"),
    ({"body": "Hi [Name], saw your issue."}, "placeholder"),
    ({"subject": "Hello {{name}}"}, "placeholder"),
    ({"stage": "Nonsense"}, "bad_stage"),
    ({"stage": "Contacted"}, "unreviewed_contact"),
    ({"email": "not-an-email"}, "bad_email"),
    ({"signals": [{**CLEAN["signals"][0], "match": 0.29}]}, "weak_match"),
])
def test_each_rule_fires(changes, rule):
    assert rule in rules(**changes)


def test_length_limits_are_inclusive():
    assert rules(subject=" ".join(["w"] * 12), body=" ".join(["w"] * 130)) == []


def test_weak_match_threshold_is_inclusive():
    assert rules(signals=[{**CLEAN["signals"][0], "match": 0.3}]) == []


def test_forward_stage_is_fine_after_a_human_decision():
    assert rules(stage="Contacted", draft_status="approved") == []


def test_closed_lost_pending_is_fine():
    assert rules(stage="Closed/Lost") == []


def test_valid_email_passes():
    assert rules(email="a.b@acme.io") == []


def test_findings_are_per_lead():
    bad = {**CLEAN, "login": "y", "reason": ""}
    assert [f["login"] for f in check_leads([CLEAN, bad], STAGES)] == ["y"]


def test_rediscovery_normalises_names():
    r = rediscovery(["@Acme, Inc.", " Globex LLC ", "Initech Ltd", "Hooli Inc", "Other"],
                    ["acme", "globex", "INITECH", "hooli", "Umbrella"], 4)
    assert r == {"k": 4, "known": 5, "found": ["acme", "globex", "INITECH", "hooli"],
                 "missed": ["Umbrella"], "recall": 0.8}


def test_rediscovery_only_counts_top_k():
    r = rediscovery(["A", "B", "C"], ["A", "C"], 2)
    assert r["found"] == ["A"] and r["missed"] == ["C"] and r["recall"] == 0.5


def test_rediscovery_empty_known():
    assert rediscovery(["A"], [], 5) == {"k": 5, "known": 0, "found": [], "missed": [], "recall": 0.0}
