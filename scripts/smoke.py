"""End-to-end smoke test for any Earshot deployment.

    .venv/bin/python scripts/smoke.py [BASE_URL]              read-only (default http://localhost:8765)
    .venv/bin/python scripts/smoke.py [BASE_URL] --write-test  ALSO approves one pending draft

--write-test CHANGES STATE: it approves one lead's draft, which logs an event and, when a mailer is
configured and the mail goes out, spends one outreach.sent credit. Nothing is ever sent to the lead;
the mailer redirects to a test or demo inbox. Without the flag nothing is written.
Exit code is non-zero if any check FAILs (WARN does not fail).
"""
import json
import sys
from urllib.parse import quote

import httpx

args = [a for a in sys.argv[1:] if not a.startswith("--")]
BASE = (args[0] if args else "http://localhost:8765").rstrip("/")
WRITE = "--write-test" in sys.argv
EVENTS = {"lead.enriched", "outreach.sent", "graph.query"}  # app/billing.py COSTS
TOOLS = ["customer_profile", "find_leads", "get_lead", "list_leads", "run_status", "trust"]
results = []
c = httpx.Client(base_url=BASE, timeout=20, follow_redirects=True)


def report(name, status, evidence=""):
    results.append(status)
    print(f"{status:<5}{name:<28}{evidence}")


def check(name):
    """Run fn; True/str/(status, str) results become PASS lines, exceptions and failed asserts become FAIL."""
    def deco(fn):
        try:
            out = fn()
            status, ev = out if isinstance(out, tuple) else ("PASS", out or "")
            report(name, status, ev)
        except Exception as e:  # noqa: BLE001 - a smoke test reports every failure kind the same way
            report(name, "FAIL", f"{type(e).__name__}: {str(e)[:160]}")
    return deco


def get(path, **kw):
    r = c.get(path, **kw)
    assert r.status_code == 200, f"{path} -> {r.status_code}"
    return r


state = {}


@check("landing /")
def _():
    r = get("/")
    assert 'id="how"' in r.text and "Play the run" in r.text, "map section marker missing"
    assert 'href="/app"' in r.text, "no call to action linking to /app"
    return "200, map section and /app link present"


@check("app shell /app")
def _():
    t = get("/app").text
    miss = [f for f in ("app.js", "app.css", "ask.js") if f not in t]
    assert not miss, f"missing references: {miss}"
    return "200, references app.js app.css ask.js"


for path, kind in [("app.js", "javascript"), ("app.css", "css"), ("ask.js", "javascript"), ("tokens.css", "css"),
                   ("landing.js", "javascript"), ("vendor/gsap.min.js", "javascript")]:
    @check(f"static {path}")
    def _(path=path, kind=kind):
        r = get(f"/static/{path}")
        ct, cc = r.headers.get("content-type", ""), r.headers.get("cache-control")
        assert kind in ct, f"content-type {ct!r}"
        assert cc, "no Cache-Control header"
        return f"200 {ct.split(';')[0]}, {len(r.content)} bytes, cache-control: {cc}"


@check("state shape")
def _():
    d = get("/api/state").json()
    miss = [k for k in ("status", "icp", "leads", "stages", "floor", "billing", "graph") if k not in d]
    assert not miss, f"missing keys: {miss}"
    state.update(d)
    return f"200 JSON, {len(d['leads'])} leads, running={d['status'].get('running')}"


@check("leads: evidence rules")
def _():
    leads = state["leads"]
    if not leads:
        return "WARN", "no leads in state (no run yet); nothing to check"
    for l in leads:
        sigs = l.get("signals") or []
        assert any(str(s.get("url", "")).startswith(("http://", "https://")) for s in sigs), f"{l['login']}: no signal with an http(s) url"
        assert 0 <= l["score"] <= 100, f"{l['login']}: score {l['score']}"
        assert l["stage"] in state["stages"], f"{l['login']}: stage {l['stage']!r}"
        assert not (l["login"].startswith("web:") and (l.get("body") or "").strip()), f"{l['login']}: web lead has a draft body"
    valid = sum(1 for l in leads if l.get("email_status") == "valid")
    return f"{len(leads)} leads all cited, scored 0-100, staged; {valid} with a valid email"


@check("trust gates")
def _():
    t = state["floor"]["trust"]
    g = t["gates"]
    assert len(g) == 5, f"{len(g)} gates, expected 5"
    assert all({"label", "passed", "value"} <= set(x) for x in g), "a gate lacks label/passed/value"
    return f"{sum(1 for x in g if x['passed'])} of 5 pass, autonomy level {t.get('level')}"


@check("billing")
def _():
    b = state["billing"]
    assert isinstance(b["credits"], (int, float)), f"credits is {type(b['credits']).__name__}"
    bad = {e["event"] for e in b.get("ledger", [])} - EVENTS
    assert not bad, f"unknown ledger events: {sorted(bad)}"
    return f"{b['credits']} credits, mode {b.get('mode')}, {len(b.get('ledger', []))} ledger entries"


@check("graph")
def _():
    g = state["graph"]
    keys = ("people", "companies", "repos", "signals", "pains", "edges")
    counts = g.get("counts") or {}
    if not counts:
        return "WARN", "graph counts empty (a run is in progress, or no run yet)"
    assert all(isinstance(counts.get(k), int) for k in keys), f"counts not all integers: {counts}"
    assert isinstance(g["insights"], list) and all({"key", "title", "rows"} <= set(i) for i in g["insights"]), "insight shape"
    r = get("/api/graph/insights").json()
    assert set(r) >= {"counts", "insights"} and all({"key", "title", "rows"} <= set(i) for i in r["insights"]), "/api/graph/insights shape"
    return f"counts {counts}, {len(g['insights'])} insights; /api/graph/insights agrees"


@check("MCP tools")
def _():
    h = {"content-type": "application/json", "accept": "application/json, text/event-stream"}

    def rpc(body, sid=None):
        r = c.post("/mcp", headers={**h, **({"mcp-session-id": sid} if sid else {})}, json=body)
        assert r.status_code in (200, 202), f"/mcp -> {r.status_code}"
        data = next((l[5:].strip() for l in r.text.splitlines() if l.startswith("data:")), r.text)
        return r, (json.loads(data) if data.strip() else {})
    r, init = rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}}})
    sid = r.headers.get("mcp-session-id")
    assert "result" in init, f"initialize: {init}"
    rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    _, tl = rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
    names = sorted(t["name"] for t in tl["result"]["tools"])
    assert names == sorted(TOOLS), f"tools {names}"
    return f"{len(names)} tools: {', '.join(names)}"


@check("evidence links live")
def _():
    leads = [l for l in state["leads"] if l.get("signals")][:3]
    if not leads:
        return "WARN", "no leads to check"
    out, worst = [], "PASS"
    for l in leads:
        url = l["signals"][0]["url"]
        try:
            code = httpx.get(url, timeout=8, follow_redirects=True, headers={"user-agent": "earshot-smoke"}).status_code
        except httpx.HTTPError as e:
            code = type(e).__name__
        host = url.split("/")[2]
        out.append(f"{host} {code}")
        if code in (403, 429):
            worst = "WARN" if worst == "PASS" else worst
        elif code != 200:
            worst = "FAIL"
    return worst, "; ".join(out)


@check("run endpoint present")
def _():
    paths = get("/openapi.json").json()["paths"]
    assert "/api/run" in paths, "/api/run missing from openapi"
    return "/api/run exists (not called: it would consume a run)"


if WRITE:
    @check("WRITE: approve one draft")
    def _():
        pend = next((l for l in state["leads"] if l.get("draft_status") == "pending"), None)
        assert pend, "no lead with draft_status pending"
        login = pend["login"]
        credits0 = state["billing"]["credits"]
        r = c.post(f"/api/leads/{quote(login, safe=':')}/decision", json={"action": "approve"})
        assert r.status_code == 200, f"decision -> {r.status_code} {r.text[:120]}"
        d = get("/api/state").json()
        new = next(l for l in d["leads"] if l["login"] == login)
        assert new["draft_status"] != "pending", "draft_status unchanged"
        ev = [e for e in d["events"] if e["login"] == login and e["action"] == "approved"]
        assert ev, "no approved event logged"
        detail = ev[0]["detail"]
        sent = "sent through" in detail
        if sent:
            assert "not to the lead" in detail and ("demo inbox" in detail or "test inbox" in detail or "founder's own inbox" in detail), f"event text: {detail}"
            n = sum(1 for e in d["billing"]["ledger"] if e["event"] == "outreach.sent" and e.get("lead") == login)
            assert n >= 1, "mail sent but billing has no outreach.sent"
        return f"{login}: {pend['draft_status']} -> {new['draft_status']}; event: {detail[:80]}; credits {credits0} -> {d['billing']['credits']}"

fails = results.count("FAIL")
print(f"\n{results.count('PASS')} pass, {results.count('WARN')} warn, {fails} fail  ({BASE})")
sys.exit(1 if fails else 0)
