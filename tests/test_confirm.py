"""Confirming the product before a run: /api/understand and the `focus` on /api/run. Everything external is faked."""
import os

os.environ.setdefault("GRAPH_PATH", "/tmp/overheard-confirm-test.kuzu")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import intake, main, pipeline  # noqa: E402

READ = {"status": "ok", "source_text": "page text " * 5, "sources": ["https://flexprice.io", "https://flexprice.io/pricing"],
        "repo": "flexprice/flexprice", "name_hint": "flexprice"}
SEEN = intake.Understanding(product_name="Flexprice", category="usage-based billing",
                            one_liner="Open-source usage-based billing for AI companies.",
                            offerings=[intake.Offering(name="Flexprice", one_liner="Usage-based billing.")], primary=0,
                            confidence=0.9, ambiguity="", buyers_guess="engineers building billing")


@pytest.fixture
def api(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)) or pipeline.state.update(running=False))
    monkeypatch.setattr(main.autopilot, "after_run", lambda: None)

    class Inline:  # runs the thread's work before start() returns
        def __init__(self, target, args, daemon): self.target, self.args = target, args
        def start(self): self.target(*self.args)
    monkeypatch.setattr(main.threading, "Thread", Inline)
    monkeypatch.setitem(pipeline.state, "running", False)
    monkeypatch.setitem(pipeline.state, "error", "")
    monkeypatch.setattr(main, "MIN_RUN_GAP_SECONDS", 0)
    monkeypatch.setattr(main.intake, "read_product", lambda t: READ)
    monkeypatch.setattr(pipeline, "ask", lambda schema, system, user: SEEN)
    main.reset_run_budget()
    main._understands.clear()
    return TestClient(main.app), calls


def test_understand_says_what_the_site_sells_and_starts_nothing(api):
    c, calls = api
    r = c.post("/api/understand", json={"target": " flexprice.io "})
    assert r.status_code == 200
    assert r.json() == {"site": "https://flexprice.io", "repo": "flexprice/flexprice", "pages_read": 2, "understanding": SEEN.model_dump()}
    assert calls == [] and pipeline.state["running"] is False


@pytest.mark.parametrize("bad", ["", "two words.io", "http://127.0.0.1", "x" * 201])
def test_understand_rejects_a_bad_target(api, bad):
    c, _ = api
    assert c.post("/api/understand", json={"target": bad}).status_code == 422
    assert c.post("/api/understand", json={}).status_code == 422


def test_understand_failures_are_a_200_with_a_reason(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(pipeline, "ask", lambda *a: (_ for _ in ()).throw(RuntimeError("sk-secret boom")))
    r = c.post("/api/understand", json={"target": "flexprice.io"})
    assert r.status_code == 200 and r.json()["understanding"] is None
    assert r.json()["reason"] == "could not work out what that site sells" and "secret" not in r.text
    monkeypatch.setattr(main.intake, "read_product", lambda t: {"status": "error", "reason": "could not read that site"})
    r = c.post("/api/understand", json={"target": "flexprice.io"})
    assert r.status_code == 200 and r.json() == {"site": "https://flexprice.io", "understanding": None, "reason": "could not read that site"}


def test_understand_clamps_what_the_model_returns(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(pipeline, "ask", lambda *a: SEEN.model_copy(update={"primary": 7, "confidence": 3.0}))
    u = c.post("/api/understand", json={"target": "flexprice.io"}).json()["understanding"]
    assert u["primary"] == 0 and u["confidence"] == 1.0


def test_understand_has_its_own_hourly_guard(api):
    c, _ = api
    for _ in range(main.MAX_UNDERSTANDS_PER_HOUR):
        assert c.post("/api/understand", json={"target": "flexprice.io"}).status_code == 200
    r = c.post("/api/understand", json={"target": "flexprice.io"})
    assert r.status_code == 429 and "Try again in" in r.json()["detail"]
    assert c.post("/api/run", json={"target": "flexprice.io"}).status_code == 202  # the run budget is separate


def test_run_with_a_focus_puts_the_confirmed_line_first(api):
    c, calls = api
    assert c.post("/api/run", json={"target": "flexprice.io", "focus": "  Flexprice: usage-based billing "}).status_code == 202
    assert calls[0][0][0] == ("The founder confirmed the product to find customers for is: Flexprice: usage-based billing.\n\n"
                              + READ["source_text"])
    calls.clear()
    assert c.post("/api/run", json={"target": "flexprice.io"}).status_code == 202
    assert calls[0][0][0] == READ["source_text"]  # no focus: unchanged


@pytest.mark.parametrize("focus", ["x" * 301, "two\nlines", "bell\x07", "tab\there"])
def test_run_rejects_a_bad_focus(api, focus):
    c, calls = api
    assert c.post("/api/run", json={"target": "flexprice.io", "focus": focus}).status_code == 422
    assert calls == []
