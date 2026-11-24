"""Run Earshot against many kinds of products and founders, measure it, and record what fails."""
import argparse
import collections
import concurrent.futures
import datetime
import json
import pathlib
import statistics
from typing import Literal

from pydantic import BaseModel

from app import checks, lessons

STAGES = ["Matched", "Contacted", "Replied", "Meeting Booked", "Closed/Lost"]
OUTCOMES = ("interested", "not_now", "annoyed", "wrong_person", "no_reply")
VERDICT_SCORE = {"works": 2, "thin": 1, "fails": 0}

FLEXPRICE_BUYERS = ["Vercel", "Supabase", "Replit", "Pinecone", "Baseten", "Chroma", "Mistral AI",
                    "Laravel", "Cerebrium", "Porter", "Webflow", "Miro", "PagerDuty"]

PRODUCTS = [
    {"key": "flexprice", "name": "Flexprice", "kind": "devtool_open_source",
     "description": (
         "Flexprice is open-source usage-based billing and metering for AI and SaaS companies. "
         "It meters events such as tokens, API calls and GPU seconds, prices them with credits, tiers and "
         "hybrid subscription-plus-usage plans, and produces invoices. Engineering teams that have outgrown "
         "Stripe Billing or maintain homegrown metering use it to stop rebuilding billing infrastructure. "
         "It can be self-hosted or run as a managed cloud."),
     "repo": "flexprice/flexprice", "expect": "strong",
     "why": "open-source billing with open-source competitors whose users file public issues",
     "known_buyers": FLEXPRICE_BUYERS},
    {"key": "flags", "name": "Fictional: Togglr feature flags", "kind": "devtool_open_source",
     "description": (
         "Togglr is a feature-flag service for engineering teams that want to ship behind flags and roll "
         "back without a deploy. It offers percentage rollouts, targeting rules by user attribute and a "
         "kill switch, with SDKs for the common backend languages. Teams that built flags into a config "
         "file and now struggle with stale flags and no audit trail are the target. The core is open source "
         "and self-hostable."),
     "repo": "Unleash/unleash", "expect": "strong",
     "why": "open-source category with an active public tracker (real competitor repo used as the seed)",
     "known_buyers": []},
    {"key": "logs", "name": "Fictional: Tailpipe logging", "kind": "devtool_open_source",
     "description": (
         "Tailpipe is an open-source log aggregation and search tool for small platform teams. It ingests "
         "logs from containers and servers, indexes only labels so storage stays cheap, and lets engineers "
         "query across services during an incident. It is aimed at teams whose hosted logging bill grew "
         "faster than their traffic. It runs on a single node or scales out on Kubernetes."),
     "repo": "grafana/loki", "expect": "strong",
     "why": "observability users report pain in public trackers of open-source tools",
     "known_buyers": []},
    {"key": "vectordb", "name": "Fictional: Voxel vector database", "kind": "devtool_open_source",
     "description": (
         "Voxel is an open-source vector database for teams building search and retrieval-augmented "
         "generation features. It stores embeddings with metadata, supports hybrid keyword and vector "
         "queries and filters, and keeps latency low as collections grow into the hundreds of millions of "
         "vectors. Developers who hit memory limits or slow filtered queries in their current store are "
         "the audience. Voxel ships as a single binary and as a hosted service."),
     "repo": "qdrant/qdrant", "expect": "strong",
     "why": "vector database users file detailed public issues about scale and filtering",
     "known_buyers": []},
    {"key": "auth", "name": "Fictional: Gatepost authentication library", "kind": "devtool_open_source",
     "description": (
         "Gatepost is an open-source authentication library for web applications. It handles sign-in with "
         "email, passwords, social providers and passkeys, manages sessions, and adds organisations and "
         "roles without a separate identity service. Developers who are tired of wiring OAuth callbacks by "
         "hand or paying per active user for a hosted identity provider are the target. It works with the "
         "popular JavaScript frameworks."),
     "repo": "nextauthjs/next-auth", "expect": "strong",
     "why": "auth libraries have large public trackers full of integration pain",
     "known_buyers": []},
    {"key": "closed_dev", "name": "Fictional: Pingwise API monitoring", "kind": "devtool_closed_source",
     "description": (
         "Pingwise is a closed-source hosted service that monitors public APIs from many regions and "
         "alerts when latency or error rates cross a threshold. It also records response payload changes so "
         "teams notice breaking changes from third-party APIs before customers do. Backend engineers and "
         "small platform teams at software companies buy it. Pricing is per monitored endpoint."),
     "repo": "", "expect": "weak",
     "why": "buyers are developers but there is no own tracker; only open-source competitors' trackers help",
     "known_buyers": []},
    {"key": "closed_nondev", "name": "Fictional: Ledgerly payroll and books", "kind": "b2b_non_developer",
     "description": (
         "Ledgerly is closed-source HR and accounting software for firms with 5 to 50 employees. It runs "
         "payroll, tracks leave, files payroll taxes and reconciles the books against the bank feed. The "
         "buyer is the owner or office manager of a small accounting, legal or dental practice, not "
         "someone who writes code. Customers pay per employee per month."),
     "repo": "", "expect": "none",
     "why": "office managers do not file public GitHub issues",
     "known_buyers": []},
    {"key": "consumer_app", "name": "Fictional: Streakly habit app", "kind": "consumer_mobile_app",
     "description": (
         "Streakly is a mobile app that helps people build daily habits with streaks, gentle reminders and "
         "a weekly review. Users pick a habit, check in with one tap and see their progress on a "
         "home-screen widget. It is free with a paid tier that adds history and sharing with a friend. The "
         "audience is anyone who wants to exercise, read or meditate more regularly."),
     "repo": "", "expect": "none",
     "why": "consumers do not discuss habit apps in public developer trackers in a buyer voice",
     "known_buyers": []},
    {"key": "local_service", "name": "Fictional: Brightside Window Cleaning", "kind": "local_service",
     "description": (
         "Brightside Window Cleaning is a local business that cleans windows for homes and small shops in "
         "the East Bay. We do a one-off clean or a monthly plan, bring our own equipment and guarantee a "
         "streak-free finish. Customers are homeowners and shop owners within thirty miles of Oakland. "
         "We want more recurring monthly customers."),
     "repo": "", "expect": "none",
     "why": "local customers do not post in public issue trackers",
     "known_buyers": []},
    {"key": "vague", "name": "Fictional: Nimbus AI", "kind": "vague",
     "description": (
         "We help companies work smarter with AI. Our platform brings together data, people and "
         "processes to unlock productivity. Anyone who wants to move faster can benefit."),
     "repo": "", "expect": "none",
     "why": "nothing concrete to infer a pain or an audience from",
     "known_buyers": []},
]


def _one_liner(description: str) -> str:
    first = description.split(". ")[0].strip()
    return first if first.endswith(".") else first + "."


_JARGON = ("We are a next-generation, AI-powered, end-to-end platform that leverages cutting-edge "
           "technology to unlock synergies, streamline workflows and deliver best-in-class, "
           "enterprise-grade outcomes at scale. Our mission-critical solution empowers stakeholders "
           "to accelerate digital transformation. ")

_WRONG_AUDIENCE = (" Our buyer is a non-technical executive, such as a chief executive or chief "
                   "operating officer, who has never written code.")

FOUNDERS = [
    {"key": "detailed", "label": "Detailed founder", "rewrite": lambda d: d},
    {"key": "one_liner", "label": "One-liner founder", "rewrite": _one_liner},
    {"key": "jargon", "label": "Jargon-heavy founder", "rewrite": lambda d: _JARGON + d},
    {"key": "wrong_audience", "label": "Wrong-audience founder", "rewrite": lambda d: d + _WRONG_AUDIENCE},
]


class Judgement(BaseModel):
    relevant: bool
    reason: str


class Reply(BaseModel):
    outcome: Literal["interested", "not_now", "annoyed", "wrong_person", "no_reply"]
    reason: str


JUDGE_SYSTEM = (
    "You are an independent reviewer. You are given a product, the pains it solves, and what one person "
    "wrote in public issue trackers. Decide whether this person plausibly has a problem the product "
    "solves. Judge only from the text shown; a loosely related topic or a different problem is not "
    "relevant. Answer with relevant true or false and one short reason."
)

REPLY_SYSTEM = (
    "You play the recipient of a cold email. You know only what is under 'About you': your own public "
    "issue text and profile fields. Answer as that person would. Most cold email is ignored, so "
    "'no_reply' is the normal outcome. Answer 'annoyed' when the message states something untrue "
    "about you or reads as generic or templated. Answer 'wrong_person' if this is not your area, "
    "'not_now' if it is relevant but the timing is wrong, and 'interested' only if the message is "
    "specific, accurate and useful to you. Give one short reason."
)


def _signals_text(lead: dict) -> str:
    return "\n".join(f"- {s.get('title', '')}: {str(s.get('excerpt', ''))[:400]}"
                     for s in lead.get("signals") or [])


def judge_lead(lead: dict, icp: dict, ask) -> dict:
    """Independent relevance check: it never sees the lead's score or tier."""
    user = (f"Product: {icp.get('product', '')}\nPains it solves:\n"
            + "\n".join(f"- {p}" for p in icp.get("pains", []))
            + f"\n\nWhat this person wrote:\n{_signals_text(lead)}")
    r = ask(Judgement, JUDGE_SYSTEM, user)
    return {"relevant": bool(r.relevant), "reason": r.reason}


def simulate_reply(lead: dict, icp: dict, ask) -> dict:
    profile = ", ".join(f"{k}: {lead[k]}" for k in ("name", "company", "role", "location") if lead.get(k))
    user = (f"About you ({profile or 'no profile details'}):\nWhat you wrote publicly:\n{_signals_text(lead)}"
            f"\n\nEmail you received.\nSubject: {lead.get('subject', '')}\n\n{lead.get('body', '')}")
    r = ask(Reply, REPLY_SYSTEM, user)
    outcome = r.outcome if r.outcome in OUTCOMES else "no_reply"
    return {"outcome": outcome, "reason": r.reason}


def _verdict(leads: int, judged: int, relevant: int) -> str:
    if leads >= 5 and relevant * 10 >= judged * 6:
        return "works"
    if leads >= 1 and (leads <= 4 or relevant * 10 >= judged * 3):
        return "thin"
    return "fails"


def _measure(leads: list[dict], product: dict) -> dict:
    today = datetime.date.today()
    ages = []
    for lead in leads:
        try:
            ages.append((today - datetime.date.fromisoformat(lead.get("newest", ""))).days)
        except (ValueError, TypeError):
            pass
    matches = [s.get("match", 0) for lead in leads for s in lead.get("signals") or []]
    ranked = [lead.get("company", "") for lead in sorted(leads, key=lambda x: -x.get("score", 0))]
    return {
        "tiers": {t: sum(1 for lead in leads if lead.get("tier") == t) for t in "ABC"},
        "with_company": sum(1 for lead in leads if lead.get("company")),
        "with_valid_email": sum(1 for lead in leads if lead.get("email_status") == "valid"),
        "findings": dict(collections.Counter(f["rule"] for f in checks.check_leads(leads, STAGES))),
        "median_match": round(statistics.median(matches), 2) if matches else 0.0,
        "median_age_days": int(statistics.median(ages)) if ages else 0,
        "recall": checks.rediscovery(ranked, product["known_buyers"], 20) if product["known_buyers"] else None,
    }


def run_case(product: dict, founder: dict, build, ask, *, sample: int = 6) -> dict:
    log: list[str] = []
    out = {"product": product["key"], "kind": product["kind"], "founder": founder["key"],
           "expect": product["expect"], "ok": True, "error": "", "leads": 0,
           "tiers": {"A": 0, "B": 0, "C": 0}, "with_company": 0, "with_valid_email": 0, "findings": {},
           "median_match": 0.0, "median_age_days": 0, "judged": 0, "relevant": 0,
           "replies": {}, "recall": None, "verdict": "fails", "log": log}
    description = founder["rewrite"](product["description"])
    try:
        icp, leads = build(description, product["repo"], say=log.append, contact=False,
                           index=f"sim-{product['key']}-{founder['key']}")
    except RuntimeError as e:  # no public tracker ecosystem: a valid, informative result
        out["error"] = str(e)
        return out
    except Exception as e:
        out.update(ok=False, error=f"{type(e).__name__}: {e}")
        return out
    try:
        top = sorted(leads, key=lambda x: -x.get("score", 0))[:sample]
        judgements = [judge_lead(lead, icp, ask) for lead in top]
        replies = collections.Counter(simulate_reply(lead, icp, ask)["outcome"] for lead in top)
    except Exception as e:
        out.update(ok=False, error=f"{type(e).__name__}: {e}")
        return out
    out.update(_measure(leads, product), leads=len(leads), judged=len(judgements),
               relevant=sum(j["relevant"] for j in judgements), replies=dict(replies))
    out["verdict"] = _verdict(out["leads"], out["judged"], out["relevant"])
    return out


def run_matrix(products, founders, build, ask, *, workers: int = 3, sample: int = 6, on_result=None) -> list[dict]:
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_case, p, f, build, ask, sample=sample) for p in products for f in founders]
        for fut in concurrent.futures.as_completed(futures):
            if on_result:
                on_result(fut.result())
        return [fut.result() for fut in futures]


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _group(results: list[dict], field: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for r in results:
        groups.setdefault(r[field], []).append(r)
    rows = []
    for name, rs in groups.items():
        replies = sum(sum(r["replies"].values()) for r in rs)
        count = lambda o: sum(r["replies"].get(o, 0) for r in rs)  # noqa: E731
        rows.append({field: name, "cases": len(rs),
                     **{v: sum(1 for r in rs if r["verdict"] == v) for v in VERDICT_SCORE},
                     "avg_leads": round(sum(r["leads"] for r in rs) / len(rs), 1),
                     "relevant_pct": _pct(sum(r["relevant"] for r in rs), sum(r["judged"] for r in rs)),
                     "interested_pct": _pct(count("interested"), replies),
                     "annoyed_pct": _pct(count("annoyed"), replies)})
    return rows


def _fit(row: dict) -> str:
    kind, n = row["kind"], row["cases"]
    stats = f"{row['works']} of {n} cases work, averaging {row['avg_leads']} leads and {row['relevant_pct']}% relevant"
    if row["works"] == n:
        return f"Earshot fits {kind}: {stats}."
    if row["fails"] == n:
        return f"Earshot does not fit {kind}: every case fails ({stats})."
    return f"Earshot partly fits {kind}: {stats}."


def scorecard(results: list[dict]) -> dict:
    by_kind = _group(results, "kind")
    surprises = [{"product": r["product"], "founder": r["founder"], "expect": r["expect"], "verdict": r["verdict"]}
                 for r in results
                 if (r["expect"] == "strong" and r["verdict"] != "works")
                 or (r["expect"] == "none" and r["verdict"] != "fails")]
    return {"cases": len(results), "by_kind": by_kind, "by_founder": _group(results, "founder"),
            "surprises": surprises, "fit": [_fit(row) for row in by_kind]}


def derive_lessons(results: list[dict]) -> list[dict]:
    found = []

    def lesson(kind, pattern, fix, evidence):
        found.append({"kind": kind, "pattern": pattern, "fix": fix, "evidence": evidence})

    for row in _group(results, "kind"):
        rs = [r for r in results if r["kind"] == row["kind"]]
        if all(r["ok"] and r["verdict"] == "fails" for r in rs):
            lesson("no_ecosystem", f"no public tracker ecosystem for {row['kind']}",
                   "detect this at intake and tell the founder before spending credits",
                   {"kind": row["kind"], "products": sorted({r["product"] for r in rs}), "cases": len(rs)})
        judged, relevant = sum(r["judged"] for r in rs), sum(r["relevant"] for r in rs)
        if judged and relevant * 2 < judged:
            lesson("loose_matches", f"relevant matches below 50% for {row['kind']}",
                   "matches are loose: raise the match threshold or add negative signals",
                   {"kind": row["kind"], "relevant_pct": row["relevant_pct"]})

    ok = [r for r in results if r["ok"]]

    def score(founder, product):
        return next((VERDICT_SCORE[r["verdict"]] for r in ok if r["founder"] == founder and r["product"] == product), None)

    for founder in sorted({r["founder"] for r in ok} - {"detailed"}):
        pairs = [(score("detailed", p), score(founder, p)) for p in sorted({r["product"] for r in ok})]
        pairs = [(d, f) for d, f in pairs if d is not None and f is not None]
        if sum(f for _, f in pairs) < sum(d for d, _ in pairs):
            lesson("founder_degrades", f"{founder} descriptions degrade results",
                   "ask a follow-up question at intake",
                   {"founder": founder, "pairs": len(pairs), "detailed_score": sum(d for d, _ in pairs),
                    "founder_score": sum(f for _, f in pairs)})

    total = sum(r["leads"] for r in results)
    fired = collections.Counter()
    for r in results:
        fired.update(r["findings"])
    for rule, count in sorted(fired.items()):
        if total and count / total > 0.2:
            lesson("check_rule", f"check rule {rule} fires in over 20% of leads",
                   f"find the stage that produces {rule} and fix it there, not in the check",
                   {"rule": rule, "count": count, "leads": total})

    replies = collections.Counter()
    for r in results:
        replies.update(r["replies"])
    if replies and replies["annoyed"] / sum(replies.values()) > 0.25:
        lesson("annoyed_replies", "annoyed replies above 25% of simulated replies",
               "drafts read as generic or state unverified things: tighten the reviewer",
               {"annoyed": replies["annoyed"], "replies": sum(replies.values())})

    for product in sorted({r["product"] for r in results if not r["ok"]}):
        errors = sorted({r["error"] for r in results if r["product"] == product and not r["ok"]})
        lesson("pipeline_crash", f"pipeline crashed on {product}", f"fix the exception: {errors[0]}",
               {"product": product, "errors": errors})
    return found


def record_lessons(results: list[dict], *, path=lessons.DEFAULT_PATH) -> list[dict]:
    return [lessons.add(x["kind"], x["pattern"], x["fix"], x["evidence"], path=path)
            for x in derive_lessons(results)]


def _table(rows: list[dict], label: str) -> str:
    cols = [label, "cases", "works", "thin", "fails", "avg_leads", "relevant_pct", "interested_pct", "annoyed_pct"]
    cells = [cols] + [[str(r[c]) for c in cols] for r in rows]
    widths = [max(len(row[i]) for row in cells) for i in range(len(cols))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths)) for row in cells)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m app.simulate")
    ap.add_argument("--products", default="all")
    ap.add_argument("--founders", default="detailed")
    ap.add_argument("--sample", type=int, default=6)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", default="data/sim/latest.json")
    args = ap.parse_args(argv)

    def pick(items, spec):
        wanted = None if spec == "all" else spec.split(",")
        chosen = [i for i in items if wanted is None or i["key"] in wanted]
        if wanted and len(chosen) != len(set(wanted)):
            ap.error(f"unknown key in {spec!r}; known: {', '.join(i['key'] for i in items)}")
        return chosen

    chosen_products, chosen_founders = pick(PRODUCTS, args.products), pick(FOUNDERS, args.founders)
    from app import pipeline  # lazy: importing it needs the service keys

    def show(r):
        print(f"{r['product']:<14} {r['founder']:<15} {r['verdict']:<6} leads={r['leads']:<3} "
              f"relevant={r['relevant']}/{r['judged']} {r['error']}", flush=True)

    results = run_matrix(chosen_products, chosen_founders, pipeline.build_leads,
                         pipeline.ask, workers=args.workers, sample=args.sample, on_result=show)
    card = scorecard(results)
    print("\n" + _table(card["by_kind"], "kind") + "\n\n" + _table(card["by_founder"], "founder"))
    print("\n" + "\n".join(card["fit"]))
    for s in card["surprises"]:
        print(f"surprise: {s['product']} with {s['founder']} expected {s['expect']}, got {s['verdict']}")
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ran_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                               "results": results, "scorecard": card}, indent=2, default=str))
    print(f"\n{len(record_lessons(results))} lessons recorded; results in {out}")


if __name__ == "__main__":
    main()
