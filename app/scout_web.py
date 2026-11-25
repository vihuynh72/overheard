"""Second Scout: people who complain about contracts, invoicing, collections and revenue on forums and review sites.

Pure and injectable: `find_voices` takes a `search` callable, so tests and the pipeline never need a key.
Signals have the same shape as the GitHub ones (`repo` holds the source host), plus kind="web".
"""
import hashlib
import os
import re
from datetime import datetime
from urllib.parse import urlparse

from app import sources

SOURCES = {
    "hn": ["news.ycombinator.com"],
    "reddit": ["reddit.com"],
    "indiehackers": ["indiehackers.com"],
    "devto": ["dev.to"],
    "stackoverflow": ["stackoverflow.com"],
    "smallbiz": ["reddit.com", "community.quickbooks.intuit.com", "community.xero.com", "quora.com"],
    "reviews": ["g2.com", "capterra.com", "trustradius.com"],
    "x": ["x.com", "twitter.com"],  # public posts only; the handle in the URL identifies the author
}
PROCESS_AREAS = ["contracts", "invoicing", "collections", "revenue reporting", "usage metering"]

MAX_QUERIES = 12
MIN_CONTENT = 80
# Hosts that publish marketing, not people.
VENDOR_HOSTS = {"stripe.com", "chargebee.com", "zuora.com", "recurly.com", "paddle.com", "orb.dev", "metronome.com",
                "flexprice.io", "freshbooks.com", "bill.com", "docusign.com"}
VENDOR_PATHS = ("/pricing", "/product", "/features", "/blog/")
LOGIN_HOSTS = {"linkedin.com"}  # needs a login to read, so no evidence link a human could open
MAX_DOMAINS = 8
_HOSTNAME = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$")
_PRIVATE_TLDS = {"local", "internal", "localhost", "test", "example", "invalid", "lan"}


def _domains() -> list[str]:
    return sorted({d for ds in SOURCES.values() for d in ds})


def clean_domains(domains) -> list[str]:
    """The Planner's channel hosts, made safe to search: bare public hostnames, no vendors, no login walls, at most 8."""
    out: list[str] = []
    for d in domains or []:
        h = re.split(r"[/?#]", re.sub(r"^[a-z][a-z0-9+.-]*://", "", str(d).strip().lower()), maxsplit=1)[0]
        h = h[4:] if h.startswith("www.") else h
        if (not _HOSTNAME.match(h) or h.rsplit(".", 1)[1] in _PRIVATE_TLDS
                or _on(h, LOGIN_HOSTS | VENDOR_HOSTS) or h in out):
            continue
        out.append(h)
    return out[:MAX_DOMAINS]


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def drop_sellers(voices: list[dict], names: list[str]) -> list[dict]:
    """A post by the product's own company or a competitor is not a buyer. Names under four characters match too much."""
    names = [n for n in map(_alnum, names) if len(n) >= 4]
    kept = []
    for v in voices:
        host, parts = _host(v["url"]), urlparse(v["url"]).path.strip("/").split("/")
        account = parts[0] if host in ("x.com", "twitter.com") else ""
        handles = (_alnum(v.get("author") or ""), _alnum(account))
        if not any(n in h for n in names for h in handles):
            kept.append(v)
    return kept


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


def _is_vendor(url: str, domains=None) -> bool:
    host, path = _host(url), urlparse(url).path.lower()
    if _on(host, VENDOR_HOSTS):
        return True
    return any(p in path for p in VENDOR_PATHS) and not _on(host, domains or _domains())


NOT_A_PERSON = {"i", "home", "search", "explore", "hashtag", "intent", "share"}  # X paths that are not an account


def _author(url: str) -> str:
    host, path = _host(url), urlparse(url).path
    if _on(host, ["reddit.com"]):
        m = re.match(r"^/(?:user|u)/([A-Za-z0-9_-]+)", path)
    elif host in ("x.com", "twitter.com"):
        m = re.match(r"^/([A-Za-z0-9_]{1,15})/status/", path)
    else:
        m = None
    name = m.group(1) if m else ""
    return "" if name.lower() in NOT_A_PERSON else name


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
                             search_depth="basic", time_range="year")["results"]  # recent posts only
    return search


last = {"queries": 0, "failed": 0}  # the most recent sweep, so the caller can say when searches failed


def find_voices(pains: list[str], areas: list[str] | None = None, *, search=None, hn=None, reddit=None, more=None,
                per_query: int = 5, min_score: float = 0.45, domains: list[str] | None = None,
                deep: bool = False) -> list[dict]:
    """Tavily results, plus Hacker News records with an author and a date, plus Reddit authors from the post JSON.

    `deep` is for buyers with no issue trackers, where the web is the only source: each pain is also asked in
    the buyer's own words, each query is asked again of Reddit alone (the one forum that names its posters),
    and more results per query are read at a lower relevance bar. The Qualifier still judges every post.

    `hn` and `reddit` default to the live sources only when `search` is not injected, so a test never reaches out.
    """
    sources.last.update(hn_requests=0, hn_failed=0, reddit_ok=0, reddit_blocked=False, reddit_read=0)
    if search is None:
        hn, reddit = hn or sources.hn_voices, reddit or sources.reddit_post
        more = [sources.so_voices] if more is None else more
        search = _tavily_search(10 if deep else per_query) if os.environ.get("TAVILY_API_KEY") else None
    domains = clean_domains(domains) or _domains()  # the Planner's channels, else every known source
    best: dict[str, dict] = {}
    qs = [{**q, "on": domains} for q in queries(pains, areas)] if search else []  # no Tavily key: Hacker News alone
    if deep and search:
        min_score = min(min_score, 0.3)
        qs += [{"pain": p, "query": p.strip(), "on": domains} for p in pains if p.strip()]
        if any(d.endswith("reddit.com") or "reddit.com/" in d for d in domains):
            qs += [{**q, "on": ["reddit.com"]} for q in list(qs)]
    last.update(queries=len(qs), failed=0)
    for q in qs:
        try:
            results = search(q["query"], q["on"])
        except Exception:  # one failed query never stops the sweep; counted in `last`, never its message (it could carry the key)
            last["failed"] += 1
            continue
        for r in results or []:
            url = (r.get("url") or "").strip()
            content = (r.get("content") or "").strip()
            try:
                score = float(r.get("score"))
            except (TypeError, ValueError):
                continue
            if not url or score < min_score or len(content) < MIN_CONTENT or _is_vendor(url, domains):
                continue
            if url in best and best[url]["match"] >= round(score, 2):
                continue
            best[url] = {"id": "web:" + hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:10], "repo": _host(url), "url": url,
                         "title": (r.get("title") or "").strip(), "body": content[:1500], "author": _author(url),
                         "created": (_date(r["published_date"]) if r.get("published_date") else "") or sources.url_date(url),
                         "pain": q["pain"], "match": round(score, 2), "kind": "web"}
    for v in best.values():  # a Reddit post found by Tavily carries no author or date; its public JSON does
        if reddit and v["repo"].endswith("reddit.com") and not v["author"] \
                and sources.last["reddit_ok"] + sources.last.get("reddit_read", 0) < sources.MAX_REDDIT * (2 if deep else 1):
            if got := reddit(v["url"]) or sources.reddit_reader(v["url"]):
                v.update(author=got["author"], created=v["created"] or got["created"], profile=got["profile"])
    if hn and "news.ycombinator.com" in domains:
        for v in hn(pains):  # the structured record wins over a Tavily result for the same item
            best[v["url"]] = v
    for source in more or []:  # other sources that publish the author and date; one failing never affects another
        try:
            for v in source(pains):
                best[v["url"]] = v
        except Exception:
            continue
    return sorted(best.values(), key=lambda v: -v["match"])


GH_ISSUE = re.compile(r"^https://github\.com/([^/]+/[^/]+)/(issues|discussions)/(\d+)")
MAX_GH_LOOKUPS = 5


def github_voices(voices: list[dict], trackers, gh) -> list[dict]:
    """A GitHub issue found by web search has a named author, but not in its URL.

    When its tracker is already being read, the issue is found there with its author, so the web copy is dropped.
    Otherwise GitHub is asked once for the author (at most MAX_GH_LOOKUPS a run). Never raises.
    """
    read, out, asked = {str(t).lower() for t in trackers}, [], 0
    for v in voices:
        m = GH_ISSUE.match(v.get("url") or "")
        if m and m[1].lower() in read:
            continue
        if m and m[2] == "issues" and not v.get("author") and asked < MAX_GH_LOOKUPS:
            asked += 1
            try:
                got = gh(f"/repos/{m[1]}/issues/{m[3]}") or {}
                if login := (got.get("user") or {}).get("login"):
                    v.update(author=login, created=v.get("created") or (got.get("created_at") or "")[:10])
            except Exception:  # the post stays evidence with no named author
                pass
        out.append(v)
    return out


def as_people(voices: list[dict]) -> list[tuple[str, list[dict]]]:
    people: dict[str, list[dict]] = {}
    for v in voices:
        slot = "u/" if v["repo"].endswith("reddit.com") else ""
        if not v.get("author"):
            key = v["id"]
        elif v.get("login"):
            key = v["login"]  # the source gave a stable id ("so:<user id>"): named, so no no-author hold
        elif v["repo"] == "news.ycombinator.com":
            key = "hn:" + v["author"]  # named, so app.policy's no-author hold (login "web:…") does not apply
        else:
            key = f"{v['repo']}/{slot}{v['author']}"
        people.setdefault(key, []).append(v)
    return list(people.items())
