"""The MCP surface: six read-mostly tools, no way to decide or spend. Store, state files and the run thread are faked."""
import asyncio
import os

os.environ.setdefault("GRAPH_PATH", "/tmp/earshot-mcp-test.kuzu")

import httpx2  # noqa: E402
import pytest  # noqa: E402
from mcp.client import Client  # noqa: E402
from mcp.client.streamable_http import streamable_http_client  # noqa: E402

from app import autopilot, main, mcp_server, pipeline, store  # noqa: E402

TOOLS = {"find_leads", "run_status", "list_leads", "get_lead", "customer_profile", "trust"}


def _lead(login, score, tier="A", **kw):
    sig = lambda title, m: dict(id=title, url=f"https://github.com/o/r/issues/{title}", title=title, excerpt="I need metering",
                                created="2026-11-01", pain="metering is hard", match=m, repo="o/r")  # noqa: E731
    return {"login": login, "name": login.title(), "company": "Acme", "score": score, "tier": tier, "stage": "Matched",
            "draft_status": "pending", "reason": "Wrote about metering. Runs it in production.", "email": "a@acme.io",
            "email_status": "valid", "domain": "acme.io", "position": "CTO", "linkedin_url": "", "blog": "",
            "subject": "Metering", "body": "Saw your issue.", "production": True, "newest": "2026-11-01",
            "signals": [sig("weak", 0.4), sig("strong", 0.9)], **kw}


@pytest.fixture
def world(monkeypatch, tmp_path):
    leads = [_lead("ada", 90), _lead("bob", 70, tier="B")]
    monkeypatch.setattr(store, "leads", lambda: sorted(leads, key=lambda l: -l["score"]))
    monkeypatch.setattr(autopilot, "STATE_PATH", str(tmp_path / "autopilot.json"))
    monkeypatch.setattr(autopilot, "SIM_PATH", str(tmp_path / "none.json"))
    monkeypatch.setattr(autopilot.billing, "ledger", lambda: [])
    monkeypatch.setattr(pipeline, "ICP_PATH", str(tmp_path / "icp.json"))
    monkeypatch.setattr(mcp_server.lessons, "all", lambda: [
        {"id": "1", "kind": "k", "pattern": "p", "fix": "f", "seen": 2, "status": "open", "regressed": True},
        {"id": "2", "kind": "k2", "pattern": "p2", "fix": "f2", "seen": 1, "status": "fixed"}])
    monkeypatch.setitem(pipeline.state, "running", False)
    monkeypatch.setitem(pipeline.state, "error", "")
    monkeypatch.setitem(pipeline.state, "log", [f"step {n}" for n in range(20)])
    main.reset_run_budget()  # the run budget is process-wide; start each test with it empty
    return leads


def test_the_tool_list_is_exactly_the_six_and_none_can_decide_or_spend():
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert names == TOOLS


def test_run_status_returns_the_last_twelve_steps(world):
    s = mcp_server.run_status()
    assert s["running"] is False and s["error"] == "" and s["steps"] == [f"step {n}" for n in range(8, 20)]


def test_list_leads_is_sorted_filtered_limited_and_names_the_strongest_evidence(world):
    rows = mcp_server.list_leads()
    assert [r["login"] for r in rows] == ["ada", "bob"]
    assert set(rows[0]) == {"login", "name", "company", "score", "tier", "stage", "draft_status", "reason",
                            "evidence_title", "evidence_url"}
    assert rows[0]["reason"] == "Wrote about metering" and rows[0]["evidence_title"] == "strong"
    assert rows[0]["evidence_url"].endswith("/strong")
    assert [r["login"] for r in mcp_server.list_leads(tier="B")] == ["bob"]
    assert len(mcp_server.list_leads(limit=1)) == 1 and mcp_server.list_leads(limit=-5) == []


def test_get_lead_has_every_signal_the_draft_the_contact_and_why_it_is_held(world):
    lead = mcp_server.get_lead("ada")
    assert lead["found"] and [s["title"] for s in lead["signals"]] == ["strong", "weak"]
    assert set(lead["signals"][0]) == {"title", "url", "source", "date", "pain", "match", "excerpt"}
    assert lead["draft"] == {"subject": "Metering", "body": "Saw your issue."}
    assert lead["contact"]["email"] == "a@acme.io" and lead["contact"]["email_status"] == "valid"
    assert "You review every message in supervised mode" in lead["held_reasons"]
    assert lead["reason"] == "Wrote about metering. Runs it in production."
    assert mcp_server.get_lead("nobody")["found"] is False


def test_customer_profile_is_empty_before_a_run_and_projected_after(world, tmp_path):
    assert mcp_server.customer_profile()["available"] is False
    s = pipeline.Scored(values=["CTOs"], confidence=0.9)
    icp = pipeline.ICP(product="P", industries=s, company_size=s, personas=s, triggers=s, pains=["metering is hard"],
                       negative_signals=[], expansion=[], competitors=[], tracker_fit=False,
                       tracker_fit_reason="Buyers are not developers.", channels=[], process_areas=[])
    (tmp_path / "icp.json").write_text(icp.model_dump_json())
    p = mcp_server.customer_profile()
    assert p["available"] and p["pains"] == ["metering is hard"] and p["buyers"]["values"] == ["CTOs"]
    assert p["method_fits"] is False and p["method_fit_reason"] == "Buyers are not developers."


def test_trust_reports_gates_and_what_was_learned(world):
    t = mcp_server.trust()
    assert t["level"] == "supervised" and t["requested"] == "supervised"
    assert {g["label"] for g in t["gates"]} >= {"Self-check is clean", "Agent matches your decisions"}
    assert all(set(g) == {"label", "met", "value", "target"} and isinstance(g["met"], bool) for g in t["gates"])
    assert [l["id"] for l in t["learned"]["open"]] == ["1"] and [l["id"] for l in t["learned"]["fixed"]] == ["2"]
    assert t["learned"]["rules"] == []


def test_find_leads_starts_through_the_web_route_and_shares_its_lock(world, monkeypatch):
    started = []
    monkeypatch.setattr(main, "_run", lambda *a: started.append(a) or pipeline.state.update(running=False))
    assert mcp_server.find_leads("flexprice.io") == {"started": True}
    for _ in range(100):
        if started:
            break
        asyncio.run(asyncio.sleep(0.01))
    assert started == [("", "", "flexprice.io")]
    pipeline.state["running"] = True
    r = mcp_server.find_leads("flexprice.io")
    assert r["started"] is False and "already in progress" in r["reason"]


@pytest.mark.parametrize("bad", ["", "   ", "http://127.0.0.1", "javascript:alert(1)", "two words.io", "x" * 300])
def test_find_leads_rejects_a_bad_target_without_starting_anything(world, monkeypatch, bad):
    monkeypatch.setattr(main, "_run", lambda *a: pytest.fail("a bad target must not start a run"))
    r = mcp_server.find_leads(bad)
    assert r["started"] is False and r["reason"] and pipeline.state["running"] is False


def test_a_real_client_talks_to_mounted_mcp_in_process(world):
    async def go():
        http = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=main.app), base_url="http://testserver")
        async with main.app.router.lifespan_context(main.app), http:
            async with Client(streamable_http_client("http://testserver/mcp", http_client=http)) as client:
                tools = {t.name for t in (await client.list_tools()).tools}
                status = await client.call_tool("run_status", {})
                leads = await client.call_tool("list_leads", {"limit": 1})
        return tools, status, leads
    tools, status, leads = asyncio.run(go())
    assert tools == TOOLS
    assert not status.is_error and '"running":false' in status.content[0].text.replace(" ", "")
    assert "ada" in leads.content[0].text
