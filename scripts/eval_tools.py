"""Eval of every sponsor tool: is it alive, how hard does it work in one real run, and does it do its job well.

Usage: .venv/bin/python scripts/eval_tools.py [--quick]
Keys come from the environment (see .env.example). Writes data/eval/latest.json. Exits 1 if any ALIVE check fails.
--quick runs only the ALIVE checks and the product counts (no Hunter or Tavily quality calls).
Spend per full run: Hunter 6 domain searches, 0 verifications; Tavily 1 search + 1 extract + 3 searches;
Flexprice 1 labelled event (graph.query, 0.1 credits); Resend 1 message to delivered@resend.dev; Claude 3 calls.
"""
import asyncio
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
os.environ.setdefault("GRAPH_PATH", "data/eval/eval.kuzu")

import httpx  # noqa: E402

from app import billing, enrich, mailer, pipeline, reviewer, scout_web  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data/eval/latest.json"
SERVER = "http://localhost:8765"
FLEXPRICE = "flexprice.io: usage-based billing and metering for AI and SaaS companies. Open source (github.com/flexprice/flexprice). Meter API calls, tokens and compute, prepaid credits and wallets, plans, invoices, entitlements."
GOAT = "Sunny Hooves: goat yoga classes on our family farm outside Sonoma. Book a weekend class for you and your friends."
HUNTER_DOMAINS = ["stripe.com", "hubspot.com", "shopify.com", "atlassian.com", "zapier.com"]
R: dict[str, dict] = {}


_CHECKS: list = []


def check(tool: str, part: str):
    """Register one measurement, run later by run_one in definition order."""
    def reg(fn):
        _CHECKS.append((tool, part, fn))
        return fn
    return reg


def run_one(tool: str, part: str, fn) -> dict:
    """Record ok, timing, evidence, or the error class. Never raises."""
    t0 = time.monotonic()
    try:
        ok, evidence, extra = fn()
        rec = {"ok": bool(ok), "evidence": evidence, **(extra or {})}
    except Exception as e:  # one tool's failure never stops the eval; the class only, never the message
        rec = {"ok": False, "evidence": f"error {type(e).__name__}",
               "where": traceback.extract_tb(e.__traceback__)[-1].lineno}
    rec["seconds"] = round(time.monotonic() - t0, 2)
    R.setdefault(tool, {})[part] = rec
    return rec


def env(k: str) -> str:
    return os.environ.get(k, "")


# --- fixtures ------------------------------------------------------------------------------------

BILLING_DOCS = [
    "Usage events arrive late and the invoice is already finalized, customers get billed for the wrong period",
    "How do I meter API calls per customer and charge per 1000 requests? Our current metering double counts",
    "Wallet balance does not decrease after usage events are ingested, prepaid credits never draw down",
    "Invoice totals don't match the usage dashboard at the end of the month, reconciliation is manual",
    "Need tiered pricing for token usage: first 1M tokens at one price, the rest cheaper",
    "Customers on prepaid credits overspend because the credit balance updates too slowly",
    "Proration is wrong when a customer upgrades plan mid billing cycle, they get charged twice",
    "We bill by compute minutes and aggregating usage events per subscription is too slow at scale",
    "Stripe invoice line items lose the usage quantity so customers cannot see what they paid for",
    "Feature entitlement limits are not enforced when the usage meter crosses the plan quota",
]
OTHER_DOCS = [
    "Dark mode toggle does not persist after page reload", "Docker image fails to build on ARM Macs",
    "Typo in the README installation section", "Add Spanish translation for the settings page",
    "Login with Google redirects to a blank page", "CSV export button is misaligned on mobile",
    "Upgrade the Postgres driver to fix a deprecation warning", "Helm chart is missing a liveness probe",
    "Unit tests are flaky on CI because of a timezone assumption", "Support for webhooks signing secret rotation in the SDK docs",
    "Sidebar icons render blurry on Windows high DPI screens", "Kubernetes pod crashes with out of memory on startup",
    "Add keyboard shortcut to open the command palette", "Logo looks wrong in the email template header",
    "GraphQL schema has a field with the wrong description", "Rename the env variable for the log level",
    "Python SDK does not install on Python 3.13", "Broken link in the contributing guide",
    "Search box loses focus when typing fast", "Date picker shows the wrong first day of the week",
]
PAIN_QUERIES = [
    "usage events are not reflected correctly on the customer's invoice",
    "prepaid credit wallet balance is not drawn down in real time",
    "metering API usage per customer for usage-based pricing",
]

LEAD = {"login": "evaltester", "name": "Sam Rivera", "company": "Acme Analytics",
        "signals": [{"repo": "getlago/lago", "created": "2026-09-14",
                     "title": "Usage events arrive after invoice finalization",
                     "excerpt": "We send about 40k usage events a day. Some arrive a few minutes after the period closes and "
                                "the invoice is already final, so we credit customers by hand every month."}]}
DRAFTS = [  # (body, honest?)
    ("Hi Sam, you wrote that usage events arriving after the period closes leave the invoice already final. "
     "Would a short call about late events be useful?", True),
    ("Hi Sam, you mentioned sending about 40k usage events a day. Flexprice accepts late events and re-rates the period. "
     "Open to a quick look?", True),
    ("Hi Sam, you said you credit customers by hand every month after late events. "
     "Could I show you how others automate that?", True),
    ("Hi Sam, you are losing $50k a year to late usage events. Flexprice fixes that. Open to a call?", False),
    ("Hi Sam, as VP of Engineering at Acme Analytics you recently raised a Series B and are hiring a billing team. "
     "Want to talk?", False),
    ("Hi Sam, you told us 80% of your invoices are wrong and your CFO is unhappy. "
     "Can I show you a fix?", False),
]


# --- ALIVE ---------------------------------------------------------------------------------------

@check("claude", "alive")
def _():
    class Ping(pipeline.BaseModel):
        word: str
        number: int
    out = pipeline.ask(Ping, "Return the word 'ready' and the number 7.", "Go.")
    return out.word.lower() == "ready" and out.number == 7, f"structured output {out.model_dump()} via pipeline.ask ({pipeline.MODEL})", None


def _moss_roundtrip(name: str, docs: list[tuple[str, str]], queries: list[str], top_k: int):
    from moss import DocumentInfo, MossClient, QueryOptions

    async def go():
        m = MossClient(env("MOSS_PROJECT_ID"), env("MOSS_PROJECT_KEY"))
        if any(ix.name == name for ix in await m.list_indexes()):
            await m.delete_index(name)
        await m.create_index(name, [DocumentInfo(id=i, text=t) for i, t in docs])
        try:
            await m.load_index(name)
            return {q: [(d.id, d.score) for d in (await m.query(name, q, QueryOptions(top_k=top_k))).docs] for q in queries}
        finally:
            await m.delete_index(name)  # free plan holds three indexes: always give the slot back
    return asyncio.run(go())


@check("moss", "alive")
def _():
    docs = [(f"d{i}", t) for i, t in enumerate(BILLING_DOCS[:2] + OTHER_DOCS[:3])]
    res = _moss_roundtrip(f"eval-alive-{os.getpid()}", docs, ["invoice is wrong because usage events are late"], 3)
    top = next(iter(res.values()))
    return bool(top) and top[0][0] in ("d0", "d1"), f"created index of 5 docs, queried, deleted; top hit {top[0] if top else None}", None


@check("tavily", "alive")
def _():
    from tavily import TavilyClient
    c = TavilyClient(env("TAVILY_API_KEY"))
    s = c.search(query="usage based billing invoice wrong late events", max_results=3)["results"]
    x = c.extract(urls=["https://flexprice.io"])["results"]
    return bool(s) and bool(x and x[0].get("raw_content")), f"search returned {len(s)} results; extract of flexprice.io returned {len((x or [{}])[0].get('raw_content') or '')} chars", None


def _hunter(path: str, **params) -> dict:
    r = httpx.get(f"{enrich.HUNTER}/{path}", params={**params, "api_key": env("HUNTER_API_KEY")}, timeout=20)
    r.raise_for_status()
    return r.json()["data"]


def _hunter_quota() -> dict:
    d = _hunter("account")
    req = d.get("requests") or {}
    return {"searches_used": (req.get("searches") or {}).get("used"), "searches_available": (req.get("searches") or {}).get("available"),
            "verifications_used": (req.get("verifications") or {}).get("used"), "verifications_available": (req.get("verifications") or {}).get("available"),
            "plan": d.get("plan_name")}


@check("hunter", "alive")
def _():
    q = _hunter_quota()
    R.setdefault("_spend", {})["hunter_before"] = q
    d = _hunter("domain-search", domain=HUNTER_DOMAINS[0], limit=5)
    R["_hunter_first"] = d
    return bool(d.get("emails")), f"account read ({q['plan']}, searches {q['searches_used']}/{q['searches_available']}); domain search on {HUNTER_DOMAINS[0]} returned {len(d.get('emails') or [])} addresses, pattern {d.get('pattern')}", None


def _fp(method: str, path: str, **kw) -> httpx.Response:
    base = (env("FLEXPRICE_BASE_URL") or billing.DEFAULT_BASE).rstrip("/")
    r = httpx.request(method, base + path, headers={"x-api-key": env("FLEXPRICE_API_KEY")}, timeout=20, **kw)
    r.raise_for_status()
    return r


def _fp_balance() -> float:
    return float(_fp("GET", f"/wallets/{env('FLEXPRICE_WALLET_ID')}/balance/real-time").json()["real_time_balance"])


@check("flexprice", "alive")
def _():
    bal = _fp_balance()
    plans = _fp("POST", "/plans/search", json={"lookup_key": "earshot-credits", "limit": 5}).json().get("items") or []
    feats = {e: bool(_fp("POST", "/features/search", json={"lookup_key": e, "limit": 5}).json().get("items")) for e in billing.COSTS}
    ok = bool(plans) and all(feats.values())
    return ok, f"wallet real-time balance {bal}; plan earshot-credits {'found' if plans else 'MISSING'}; features {feats}", {"balance": bal}


@check("subq", "alive")
def _():
    state = "Sam wrote: our invoices are finalized before late usage events arrive, so we credit customers by hand."
    p = reviewer.snap_judge(state, {"yes": 'Is this sentence fully supported by the evidence, with nothing added? "Your invoices are finalized before late usage events arrive."',
                                    "no": 'Is this sentence fully supported by the evidence, with nothing added? "You lose $2M a year and plan to switch vendors next month."'})
    return p["yes"] >= 0.5 > p["no"], f"supported claim P={p['yes']:.2f}, unsupported claim P={p['no']:.2f} via reviewer.snap_judge ({reviewer.MODEL})", None


@check("resend", "alive")
def _():
    os.environ.pop("DEMO_INBOX", None)  # the eval sends only to Resend's sink
    lead = {"login": "evaltester", "name": "Sam Rivera", "email": "sam.rivera@example.com"}
    if mailer.gmail.status()["connected"]:
        return False, "Gmail is connected in this process; refusing to send so nothing reaches a real inbox", None
    out = mailer.send(lead, "Overheard eval: redirect check", "Eval message. Written for a fake lead, sent to the Resend sink.")
    ok = out["status"] == "sent" and out["to"] == mailer.SINK and out["to"] != lead["email"]
    return ok, f"app.mailer.send -> status {out['status']}, to {out.get('to')}, lead address {lead['email']} not used", None


@check("band", "alive")
def _():
    if not shutil.which("band"):
        return False, "band CLI not installed", None
    v = subprocess.run(["band", "version"], capture_output=True, text=True, timeout=30)
    c = subprocess.run(["band", "chats", "list", "hackwithbay-feat-band-author-gate"], capture_output=True, text=True, timeout=60)
    doc = (ROOT / "docs/band-run.md").exists()
    ok = v.returncode == 0 and c.returncode == 0 and doc
    return ok, (f"band version rc={v.returncode} ({(v.stdout or v.stderr).strip()[:40]}); chats list rc={c.returncode}, "
                f"{len([x for x in c.stdout.splitlines() if x.strip()])} lines; docs/band-run.md {'exists' if doc else 'missing'}; "
                "verified by transcript, not a live agent run"), None


@check("gmail", "alive")
def _():
    st = mailer.gmail.status()
    return True, f"not configured (configured={st['configured']}, connected={st['connected']}); Resend is the send path", {"configured": st["configured"]}


@check("elevenlabs", "alive")
def _():
    r = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": env("ELEVENLABS_API_KEY")}, timeout=20)
    r.raise_for_status()
    n = len(r.json().get("voices") or [])
    return n > 0, f"used for the demo film's voices; not called by the app. list-voices returned {n} voices", None


# --- USED IN THE PRODUCT (static + last real run) -----------------------------------------------

def _grep(pattern: str, path: str) -> int:
    return len(re.findall(pattern, (ROOT / path).read_text()))


@check("_run", "used")
def _():
    s = httpx.get(f"{SERVER}/api/state", timeout=10).json()
    log = s["status"]["log"]
    icp, leads, bill, mail = s.get("icp") or {}, s.get("leads") or [], s.get("billing") or {}, s.get("mail") or {}
    num = lambda pat: sum(int(m) for line in log for m in re.findall(pat, line))  # noqa: E731
    issues = num(r"has (\d+) issues from outside users")
    pains, learned = len(icp.get("pains") or []), len(icp.get("learned_pains") or [])
    web_q = len(scout_web.queries(icp.get("pains") or [], icp.get("process_areas") or []))
    enrich_steps = [l.get("enrich") or "" for l in leads]
    hunter_lookups = sum(("Hunter" in e) or ("verified known email" in e) for e in enrich_steps)
    verified = sum(l.get("email_status") == "valid" for l in leads)
    ledger = bill.get("ledger") or []
    by_type: dict[str, int] = {}
    for e in ledger:
        if e.get("ok"):
            by_type[e["event"]] = by_type.get(e["event"], 0) + 1
    drawn = round(sum(e["credits"] for e in ledger if e.get("ok")), 2)
    review = next((x for x in log if x.startswith("Reviewer: checked")), "")
    rv = re.findall(r"\d+", review)
    sent = sum(1 for e in s.get("events") or [] if "sent through" in (e.get("text") or ""))
    autopilot = json.loads((ROOT / "data/autopilot.json").read_text()) if (ROOT / "data/autopilot.json").exists() else {}
    used = {
        "claude": {"call_sites": {"Planner (ICP)": 1, "learn_pains": 1, "Qualifier+Writer per lead": 1, "redraft on rule break": 1, "rewrite after Reviewer": 1},
                   "calls_last_run": 1 + (1 if learned else 0) + num(r"passing the top (\d+)") + num(r"(\d+) drafts broke a writing rule"),
                   "note": "Qualifier runs on every passed candidate, not only kept leads"},
        "moss": {"docs_indexed": issues, "queries": pains + learned},
        "tavily": {"searches_planned": web_q, "posts_kept": num(r"found (\d+) posts"), "extracts": 1 if any("reading http" in x for x in log) else 0,
                   "domain_lookups": sum("from web search" in e for e in enrich_steps)},
        "hunter": {"leads_looked_up": hunter_lookups, "verified": verified, "leads": len(leads),
                   "skipped_reasons": sorted({e for e in enrich_steps if "skipped" in e})},
        "flexprice": {"events_by_type": by_type, "credits_drawn": drawn, "mode": bill.get("mode"), "balance": bill.get("credits")},
        "subq": {"drafts_judged": int(rv[0]) if rv else 0, "flagged": int(rv[1]) if len(rv) > 1 else 0},
        "resend": {"sent_in_state": sent, "inbox": "Resend demo sink (delivered@resend.dev)" if mail.get("resend") else "none",
                   "decisions_recorded": len(autopilot.get("decisions") or [])},
        "gmail": {"connected": mail.get("connected", False)},
        "band": {"agents_in_transcript": _grep(r"(?im)^#+.*agent", "docs/band-run.md") if (ROOT / "docs/band-run.md").exists() else 0},
        "elevenlabs": {"app_call_sites": 0},
    }
    hits_line = next((x for x in log if "issues describe a target pain" in x), "")
    m = re.search(r"(\d+) of (\d+) issues describe", hits_line)
    used["moss"]["hits"] = int(m.group(1)) if m else 0
    for tool, u in used.items():
        R.setdefault(tool, {})["used"] = {"ok": True, "evidence": json.dumps(u), **u}
    return True, f"last run: {len(leads)} leads, {len(log)} log lines", None


# --- QUALITY --------------------------------------------------------------------------------------

@check("moss", "quality")
def _():
    docs = [(f"b{i}", t) for i, t in enumerate(BILLING_DOCS)] + [(f"o{i}", t) for i, t in enumerate(OTHER_DOCS)]
    res = _moss_roundtrip(f"eval-q-{os.getpid()}", docs, PAIN_QUERIES, 20)
    p5, rec = [], []
    for q, hits in res.items():
        kept = [(i, s) for i, s in hits if s >= pipeline.MIN_MATCH]
        top = kept[:5]
        p5.append(sum(i.startswith("b") for i, _ in top) / max(len(top), 1))
        rec.append(len({i for i, _ in kept if i.startswith("b")}) / len(BILLING_DOCS))
    false_hits = sum(1 for hits in res.values() for i, s in hits if s >= pipeline.MIN_MATCH and i.startswith("o"))
    p, r = sum(p5) / 3, sum(rec) / 3
    return p >= 0.8, f"precision@5 {p:.2f}, recall {r:.2f} at MIN_MATCH {pipeline.MIN_MATCH}; {false_hits} off-topic docs above threshold across 3 queries", {"metric": round(p, 2), "recall": round(r, 2), "false_hits": false_hits}


@check("claude", "quality")
def _():
    a = pipeline.ask(pipeline.ICP, pipeline.ICP_SYSTEM, FLEXPRICE)
    b = pipeline.ask(pipeline.ICP, pipeline.ICP_SYSTEM, GOAT)
    R["_icp"] = a
    hosts = [c.domain for c in a.channels]
    valid = [h for h in hosts if enrich.DOMAIN_RE.match(h) and "/" not in h]
    checks_ = {"pains>=3": len(a.pains) >= 3, "channels 4-6": 4 <= len(hosts) <= 6, "hosts valid": len(valid) == len(hosts),
               "flexprice tracker_fit": a.tracker_fit, "goat yoga declined": not b.tracker_fit}
    passed = sum(checks_.values())
    return passed == len(checks_), f"{passed}/{len(checks_)} assertions: {checks_}; channels {hosts}; goat yoga reason: {b.tracker_fit_reason}", {"metric": f"{passed}/{len(checks_)}"}


@check("subq", "quality")
def _():
    right, rows = 0, []
    for body, honest in DRAFTS:
        r = reviewer.review({**LEAD, "body": body}, reviewer.snap_judge)
        got = r["verdict"] == "pass"
        right += got == honest
        rows.append({"honest": honest, "verdict": r["verdict"], "flagged": r["unsupported"]})
    acc = right / len(DRAFTS)
    R["_reviews"] = rows
    return acc >= 5 / 6, f"accuracy {right}/{len(DRAFTS)} on 3 honest and 3 overclaiming drafts", {"metric": round(acc, 2), "rows": rows}


@check("guard", "quality")
def _():
    rows = []
    for body, honest in DRAFTS:
        _out, removed = reviewer.guard(body, reviewer.full_evidence({**LEAD, "signals": [{**LEAD["signals"][0], "body": LEAD["signals"][0]["excerpt"]}]}))
        rows.append({"honest": honest, "removed": removed})
    honest_cut = sum(bool(r["removed"]) for r in rows if r["honest"])
    over_cut = sum(bool(r["removed"]) for r in rows if not r["honest"])
    return honest_cut == 0, f"stripped sentences from {over_cut}/3 overclaiming drafts and {honest_cut}/3 honest drafts (it only catches invented numbers)", {"metric": f"{over_cut}/3 caught, {honest_cut}/3 false cuts", "rows": rows}


@check("tavily", "quality")
def _():
    icp = R.get("_icp")
    pains = icp.pains[:3] if icp else PAIN_QUERIES
    domains = scout_web.clean_domains([c.domain for c in icp.channels]) if icp else None
    raw: list[dict] = []
    base = scout_web._tavily_search(5)

    def counting(q, ds):
        got = base(q, ds)
        raw.extend(got)
        return got
    kept = scout_web.find_voices(pains, [], search=counting, domains=domains)
    urls = {r.get("url") for r in raw if r.get("url")}
    dated = sum(1 for v in kept if v.get("created"))
    share = len(kept) / max(len(urls), 1)
    return share > 0, f"{len(kept)} of {len(urls)} distinct results passed the app's filters ({share:.0%}); {dated} of the kept have a date; channels {domains}", {"metric": round(share, 2), "kept": len(kept), "raw": len(urls), "dated": dated}


@check("hunter", "quality")
def _():
    hits, rows = 0, []
    for dom in HUNTER_DOMAINS:
        d = R["_hunter_first"] if dom == HUNTER_DOMAINS[0] and "_hunter_first" in R else _hunter("domain-search", domain=dom, limit=5)
        with_status = [e for e in d.get("emails") or [] if (e.get("verification") or {}).get("status")]
        hits += bool(with_status)
        rows.append({"domain": dom, "emails": len(d.get("emails") or []), "with_status": len(with_status), "pattern": d.get("pattern")})
    share = hits / len(HUNTER_DOMAINS)
    return share >= 0.6, f"{hits}/{len(HUNTER_DOMAINS)} public domains return an address with a verification status", {"metric": share, "rows": rows}


@check("flexprice", "quality")
def _():
    before = _fp_balance()
    _fp("POST", "/events", json={"event_name": "graph.query", "external_customer_id": env("FLEXPRICE_CUSTOMER_ID"),
                                 "event_id": f"earshot-eval-{int(time.time())}", "source": "earshot-eval",
                                 "properties": {"lead": "earshot-eval", "credits": "0.1", "eval": "true"}})
    t0 = time.monotonic()
    while time.monotonic() - t0 < 20:
        now = _fp_balance()
        if before - now >= 0.1 - 1e-6:
            d = time.monotonic() - t0
            return True, f"labelled eval event (source earshot-eval) drew the wallet from {before} to {now} in {d:.1f}s", {"metric": round(d, 1)}
        time.sleep(1)
    return False, f"wallet did not move within 20s (still {_fp_balance()})", {"metric": None}


# --- report ---------------------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    quick = "--quick" in argv
    for tool, part, fn in _CHECKS:
        if quick and part == "quality":
            continue
        run_one(tool, part, fn)
    try:
        R["_spend"]["hunter_after"] = _hunter_quota()
    except Exception as e:
        R.setdefault("_spend", {})["hunter_after"] = f"error {type(e).__name__}"
    rows = []
    for tool in ["claude", "moss", "tavily", "hunter", "flexprice", "subq", "guard", "resend", "gmail", "band", "elevenlabs"]:
        t = R.get(tool, {})
        a, q = t.get("alive"), t.get("quality")
        verdict = "FAIL" if a and not a["ok"] else ("WEAK" if q and not q["ok"] else "PASS")
        if tool == "guard":
            verdict = "PASS" if q and q["ok"] else ("WEAK" if q else "PASS")
        rows.append((tool, verdict, (q or {}).get("metric", "-"), (a or q or {}).get("evidence", "")))
    print(f"{'tool':<11} {'verdict':<7} {'quality':<26} evidence")
    for tool, v, m, ev in rows:
        print(f"{tool:<11} {v:<7} {str(m):<26} {ev[:150]}")
    for tool in ("claude", "moss", "tavily", "hunter", "flexprice", "subq", "resend"):
        u = R.get(tool, {}).get("used")
        if u:
            print(f"  used/{tool}: {u['evidence'][:200]}")
    print(f"  hunter quota: before {R['_spend'].get('hunter_before')} after {R['_spend'].get('hunter_after')}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    clean = {k: v for k, v in R.items() if not k.startswith("_") or k == "_spend"}
    OUT.write_text(json.dumps({"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "quick": quick, "verdicts": {r[0]: r[1] for r in rows},
                               "results": clean}, indent=2, default=str))
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 1 if any(t.get("alive") and not t["alive"]["ok"] for k, t in R.items() if not k.startswith("_")) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
