import json

import httpx
import pytest

from app import reviewer as r

KEY = "sekrit-subq-key"
LEAD = {
    "login": "derek", "name": "Derek Chen", "company": "Nozzle", "role": "CTO", "location": "Berlin",
    "body": "Hi Derek,\nYou opened an issue about usage metering. We built a tool for that. "
            "Does that sound useful?",
    "signals": [{"repo": "getlago/lago", "created": "2026-02-26", "title": "Usage metering",
                 "excerpt": "We need per-event billing."}],
}


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("SUBQ_API_KEY", KEY)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("body,expected", [
    ("Use a tool, e.g. Lago. It works.", ["Use a tool, e.g. Lago.", "It works."]),
    ("We run K8s 1.35 today. Fine!", ["We run K8s 1.35 today.", "Fine!"]),
    ("See https://a.io/x.y for more. Ok?", ["See https://a.io/x.y for more.", "Ok?"]),
    ("Mail ada@nozzle.io now. Thanks.", ["Mail ada@nozzle.io now.", "Thanks."]),
    ("Hi Ada,\n\nOne line.\nTwo line", ["Hi Ada,", "One line.", "Two line"]),
    ("", []),
])
def test_split(body, expected):
    assert r.split(body) == expected


@pytest.mark.parametrize("sentence,expected", [
    ("You opened an issue.", True),
    ("Your repo is great.", True),
    ("I hope you're well.", True),
    ("Derek wrote about billing.", True),
    ("Nozzle ships fast.", True),
    ("Hi Derek,", False),
    ("Hi Derek, your issue was sharp.", True),
    ("Do you meter usage?", False),
    ("We built a metering tool.", False),
    ("Layoutyou is a word.", False),
])
def test_about_recipient(sentence, expected):
    assert r.about_recipient(sentence, LEAD) is expected


def test_evidence_has_profile_and_signal_fields():
    ev = r.evidence(LEAD)
    for part in ("Derek Chen", "Nozzle", "CTO", "Berlin", "getlago/lago", "2026-02-26",
                 "Usage metering", "per-event billing"):
        assert part in ev


def test_review_pass_asks_one_question_per_claim_in_one_call():
    calls = []

    def judge(state, questions):
        calls.append((state, questions))
        return {i: 0.9 for i in questions}

    res = r.review(LEAD, judge)
    assert res["verdict"] == "pass" and res["unsupported"] == [] and res["login"] == "derek"
    assert len(calls) == 1 and len(calls[0][1]) == 1
    assert res["claims"] == [{"sentence": "You opened an issue about usage metering.", "supported": 0.9}]


def test_review_fail_lists_low_probability_sentences():
    res = r.review(LEAD, lambda s, q: {i: 0.2 for i in q})
    assert res["verdict"] == "fail"
    assert res["unsupported"] == ["You opened an issue about usage metering."]


def test_review_missing_answer_fails_closed():
    assert r.review(LEAD, lambda s, q: {})["verdict"] == "fail"


def test_review_no_claims_makes_no_judge_call():
    def judge(s, q):
        raise AssertionError("called")

    res = r.review({**LEAD, "body": "We built a tool. Want a demo?"}, judge)
    assert res == {"login": "derek", "verdict": "pass", "claims": [], "unsupported": []}


def test_review_judge_raising_is_unchecked_and_leaks_nothing():
    def judge(s, q):
        raise RuntimeError(KEY)

    res = r.review(LEAD, judge)
    assert res["verdict"] == "unchecked" and res["reason"] == "RuntimeError"
    assert KEY not in json.dumps(res)


def test_findings_both_rules():
    other = {**LEAD, "login": "ada"}
    calls = iter([{"q0": 0.1}, RuntimeError("x")])

    def judge(s, q):
        v = next(calls)
        if isinstance(v, Exception):
            raise v
        return v

    assert r.findings([LEAD, other], judge) == [
        {"login": "derek", "rule": "unsupported_claim", "detail": "You opened an issue about usage metering."},
        {"login": "ada", "rule": "review_unavailable", "detail": "RuntimeError"},
    ]


def test_findings_clean_is_empty():
    assert r.findings([LEAD], lambda s, q: {i: 1.0 for i in q}) == []


def test_snap_judge_request_shape_and_parsing():
    seen = []

    def h(req):
        seen.append(req)
        return httpx.Response(200, json={"answers": {"a": {"noul": 0.8}, "b": {"noul": 0.1}}})

    out = r.snap_judge("evidence text", {"a": "Is A?", "b": "Is B?"}, client=client(h))
    assert out == {"a": 0.8, "b": 0.1}
    (req,) = seen
    assert str(req.url) == "https://api.subq.ai/v1/systemone" and req.method == "POST"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == "subq-snap-1.2" and body["state"] == "evidence text"
    assert set(body["questions"]) == {"a", "b"}
    q = body["questions"]["a"]
    assert q["type"] == "noul" and q["instructions"] == "Is A?"
    assert set(q["criteria"]) == {"true", "false"}


def test_snap_judge_missing_key(monkeypatch):
    monkeypatch.delenv("SUBQ_API_KEY")
    with pytest.raises(RuntimeError, match="no SUBQ_API_KEY"):
        r.snap_judge("s", {"a": "q"})


def test_snap_judge_http_500_message_has_no_key():
    c = client(lambda req: httpx.Response(500, text=f"boom {KEY}"))
    with pytest.raises(RuntimeError) as e:
        r.snap_judge("s", {"a": "q"}, client=c)
    assert str(e.value) == "SubQ HTTP 500" and KEY not in str(e.value)


def test_snap_judge_caps_at_128_and_fails_closed_for_the_rest():
    sent = []

    def h(req):
        qs = json.loads(req.content)["questions"]
        sent.append(len(qs))
        return httpx.Response(200, json={"answers": {i: {"noul": 1.0} for i in qs}})

    questions = {f"q{i}": "x" for i in range(130)}
    out = r.snap_judge("s", questions, client=client(h))
    assert sent == [128] and len(out) == 130
    assert out["q127"] == 1.0 and out["q128"] == 0.0 and out["q129"] == 0.0


def test_review_through_snap_judge_never_leaks_key():
    c = client(lambda req: httpx.Response(500, text=KEY))
    res = r.review(LEAD, lambda s, q: r.snap_judge(s, q, client=c))
    assert res["verdict"] == "unchecked" and KEY not in json.dumps(res)
