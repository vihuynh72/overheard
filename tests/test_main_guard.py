"""The run budget on the public deployment: one gap, one hourly cap, enforced where every run starts."""
import os

os.environ.setdefault("GRAPH_PATH", "/tmp/earshot-test-guard.kuzu")

import pytest  # noqa: E402

from app import main, mcp_server, pipeline  # noqa: E402


@pytest.fixture
def guard(monkeypatch):
    started, clock = [], [1000.0]
    monkeypatch.setattr(main, "_run", lambda *a: started.append(a) or pipeline.state.update(running=False))
    monkeypatch.setattr(main.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(main, "MAX_RUNS_PER_HOUR", 3)
    monkeypatch.setattr(main, "MIN_RUN_GAP_SECONDS", 20)
    monkeypatch.setitem(pipeline.state, "running", False)
    main.reset_run_budget()

    def start():
        r = mcp_server.find_leads("flexprice.io")  # the MCP tool and POST /api/run share main.run
        pipeline.state["running"] = False  # the faked run has finished
        return r
    return start, clock, started


def test_a_second_start_inside_the_gap_is_refused_with_when_to_retry(guard):
    start, clock, _ = guard
    assert start() == {"started": True}
    clock[0] += 5
    r = start()
    assert r["started"] is False and "15 seconds" in r["reason"]
    clock[0] += 15
    assert start() == {"started": True}


def test_the_hourly_cap_refuses_and_names_the_wait(guard):
    start, clock, _ = guard
    for _ in range(3):
        assert start() == {"started": True}
        clock[0] += 30
    r = start()
    assert r["started"] is False and "3 runs an hour" in r["reason"] and "minutes" in r["reason"]


def test_the_window_rolls_off(guard):
    start, clock, _ = guard
    for _ in range(3):
        start()
        clock[0] += 30
    assert start()["started"] is False
    clock[0] = 1000.0 + 3600  # the first start leaves the hour; the other two are still in it
    assert start() == {"started": True}
    clock[0] += 20  # only the first start has left the hour, so that one slot is spent again
    assert start()["started"] is False


def test_a_refused_start_spends_no_budget(guard):
    start, clock, started = guard
    start()
    for _ in range(10):  # hammering inside the gap
        clock[0] += 1
        assert start()["started"] is False
    clock[0] += 20
    assert start() == {"started": True}
    assert len(main._starts) == 2


def test_a_run_in_progress_is_refused_without_spending_budget(guard):
    start, clock, _ = guard
    pipeline.state["running"] = True
    r = mcp_server.find_leads("flexprice.io")
    assert r["started"] is False and "already in progress" in r["reason"] and len(main._starts) == 0


def test_the_web_route_gets_a_429_with_the_reason_the_page_shows(guard):
    from fastapi.testclient import TestClient
    start, clock, _ = guard
    start()
    r = TestClient(main.app).post("/api/run", json={"target": "flexprice.io"})
    assert r.status_code == 429 and "Try again in" in r.json()["detail"]
