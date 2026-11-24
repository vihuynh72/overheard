"""The customer profile on its own, for products Overheard declines: /api/profile. Everything external is faked."""
import os

os.environ.setdefault("GRAPH_PATH", "/tmp/overheard-profile-test.kuzu")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main, pipeline  # noqa: E402

READ = {"status": "ok", "source_text": "We roast coffee. " * 5, "sources": ["https://roaster.example"], "repo": "", "name_hint": "roaster"}
S = {"values": ["x"], "confidence": 0.8, "reasoning": "r"}


def icp():
    fields = {k: S for k in ("industries", "company_size", "personas", "triggers")}
    try:
        return pipeline.ICP(product="Coffee", **fields, pains=["stale beans"], negative_signals=[], expansion=[], competitors=[],
                            tracker_fit=False, tracker_fit_reason="Buyers are cafe owners, who do not file issues.",
                            channels=[{"domain": "reddit.com", "kind": "forum", "why": "They ask there."}], process_areas=[])
    except Exception:  # the Scored shape is the pipeline's to change; build without validation rather than copy it
        return pipeline.ICP.model_construct(product="Coffee", pains=["stale beans"], tracker_fit=False,
                                            tracker_fit_reason="Buyers are cafe owners, who do not file issues.", channels=[])


@pytest.fixture
def api(monkeypatch):
    asked = []
    monkeypatch.setattr(main.intake, "read_product", lambda t: READ)
    monkeypatch.setattr(pipeline, "ask", lambda schema, system, user: asked.append((schema, system, user)) or icp())
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: pytest.fail("a profile must not start a run"))
    main._profiles.clear()
    return TestClient(main.app), asked


def test_profile_returns_the_customer_and_starts_nothing(api):
    c, asked = api
    r = c.post("/api/profile", json={"target": " roaster.example "})
    assert r.status_code == 200
    j = r.json()
    assert set(j) == {"site", "icp", "fit", "reason"} and j["site"] == "https://roaster.example"
    assert j["fit"] is False and j["reason"].startswith("Buyers are cafe owners") and j["icp"]["pains"] == ["stale beans"]
    assert asked == [(pipeline.ICP, pipeline.ICP_SYSTEM, READ["source_text"])]  # the run's own inference, asked once


def test_focus_becomes_the_first_line(api):
    c, asked = api
    c.post("/api/profile", json={"target": "roaster.example", "focus": "Wholesale beans"})
    assert asked[0][2] == f"The founder confirmed the product to find customers for is: Wholesale beans.\n\n{READ['source_text']}"


def test_bad_target_and_bad_focus_are_refused(api):
    c, asked = api
    assert c.post("/api/profile", json={"target": "not a site"}).status_code == 422
    assert c.post("/api/profile", json={"target": "roaster.example", "focus": "a\nb"}).status_code == 422
    assert asked == []


def test_a_failed_read_or_model_gives_a_plain_reason(api, monkeypatch):
    c, _ = api
    monkeypatch.setattr(pipeline, "ask", lambda *a: (_ for _ in ()).throw(RuntimeError("sk-secret")))
    assert c.post("/api/profile", json={"target": "roaster.example"}).json() == {
        "site": "https://roaster.example", "icp": None, "reason": "could not work out who buys this"}
    monkeypatch.setattr(main.intake, "read_product", lambda t: {"status": "error", "reason": "could not read that site"})
    assert c.post("/api/profile", json={"target": "roaster.example"}).json()["reason"] == "could not read that site"


def test_twelve_an_hour(api):
    c, _ = api
    for _ in range(main.MAX_PROFILES_PER_HOUR):
        assert c.post("/api/profile", json={"target": "roaster.example"}).status_code == 200
    r = c.post("/api/profile", json={"target": "roaster.example"})
    assert r.status_code == 429 and "12 profiles an hour" in r.json()["detail"]
