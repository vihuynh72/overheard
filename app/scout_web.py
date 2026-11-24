"""Second Scout: people who complain about contracts, invoicing, collections and revenue on forums and review sites.

Pure and injectable: `find_voices` takes a `search` callable, so tests and the pipeline never need a key.
Signals have the same shape as the GitHub ones (`repo` holds the source host), plus kind="web".
"""
import hashlib
import os
import re
from datetime import datetime
from urllib.parse import urlparse

SOURCES = {
    "hn": ["news.ycombinator.com"],
    "reddit": ["reddit.com"],
    "indiehackers": ["indiehackers.com"],
    "devto": ["dev.to"],
    "stackoverflow": ["stackoverflow.com"],
    "smallbiz": ["reddit.com", "community.quickbooks.intuit.com", "community.xero.com", "quora.com"],
    "reviews": ["g2.com", "capterra.com", "trustradius.com"],
}
PROCESS_AREAS = ["contracts", "invoicing", "collections", "revenue reporting", "usage metering"]

MAX_QUERIES = 12
MIN_CONTENT = 80
# Hosts that publish marketing, not people.
VENDOR_HOSTS = {"stripe.com", "chargebee.com", "zuora.com", "recurly.com", "paddle.com", "orb.dev", "metronome.com",
                "flexprice.io", "freshbooks.com", "bill.com", "docusign.com"}
VENDOR_PATHS = ("/pricing", "/product", "/features", "/blog/")


def _domains() -> list[str]:
    return sorted({d for ds in SOURCES.values() for d in ds})


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", s.lower()))


def queries(pains: list[str], areas: list[str] | None = None) -> list[dict]:
    out = [{"pain": p, "query": f"{p.strip().rstrip('.?!')} - how do you deal with this?"} for p in pains if p.strip()]
    for area in areas or []:
        if not pains:
            break
        aw = _words(area)
        # max() keeps the first pain on ties, so the result is deterministic.
        pain = max(pains, key=lambda p: len(aw & _words(p)))
        out.append({"pain": pain, "query": f"struggling with {area}: {pain.strip().rstrip('.?!')}"})
    return out[:MAX_QUERIES]


def _host(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _on(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _is_vendor(url: str) -> bool:
    host, path = _host(url), urlparse(url).path.lower()
    if _on(host, VENDOR_HOSTS):
        return True
    return any(p in path for p in VENDOR_PATHS) and not _on(host, _domains())


def _author(url: str) -> str:
    host, path = _host(url), urlparse(url).path
    if _on(host, ["reddit.com"]):
        m = re.match(r"^/(?:user|u)/([A-Za-z0-9_-]+)", path)
    elif host in ("x.com", "twitter.com"):
        m = re.match(r"^/([A-Za-z0-9_]{1,15})/status/", path)
    else:
        m = None
    return m.group(1) if m else ""


def _date(s) -> str:
    try:
        return datetime.fromisoformat(str(s).strip().replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:  # RFC 2822, e.g. "Mon, 03 Mar 2025 10:00:00 GMT"
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(str(s)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _tavily_search(per_query: int):
    def search(query: str, domains: list[str]) -> list[dict]:
        import tavily  # imported at call time so a missing key or package costs nothing
        client = tavily.TavilyClient(os.environ["TAVILY_API_KEY"])
        return client.search(query=query, include_domains=domains, max_results=per_query,
                             search_depth="basic")["results"]
    return search


def find_voices(pains: list[str], areas: list[str] | None = None, *, search=None,
                per_query: int = 5, min_score: float = 0.45) -> list[dict]:
    if search is None:
        if not os.environ.get("TAVILY_API_KEY"):
            return []
        search = _tavily_search(per_query)
    domains = _domains()
    best: dict[str, dict] = {}
    for q in queries(pains, areas):
        try:
            results = search(q["query"], domains)
        except Exception:  # one failed query never stops the sweep; shortcut: not logged, so no key can leak via an error string
            continue
        for r in results or []:
            url = (r.get("url") or "").strip()
            content = (r.get("content") or "").strip()
            try:
                score = float(r.get("score"))
            except (TypeError, ValueError):
                continue
            if not url or score < min_score or len(content) < MIN_CONTENT or _is_vendor(url):
                continue
            if url in best and best[url]["match"] >= round(score, 2):
                continue
            best[url] = {"id": "web:" + hashlib.sha1(url.encode()).hexdigest()[:10], "repo": _host(url), "url": url,
                         "title": (r.get("title") or "").strip(), "body": content[:1500], "author": _author(url),
                         "created": _date(r["published_date"]) if r.get("published_date") else "",
                         "pain": q["pain"], "match": round(score, 2), "kind": "web"}
    return sorted(best.values(), key=lambda v: -v["match"])


def as_people(voices: list[dict]) -> list[tuple[str, list[dict]]]:
    people: dict[str, list[dict]] = {}
    for v in voices:
        slot = "u/" if v["repo"].endswith("reddit.com") else ""
        key = f"{v['repo']}/{slot}{v['author']}" if v.get("author") else v["id"]
        people.setdefault(key, []).append(v)
    return list(people.items())
