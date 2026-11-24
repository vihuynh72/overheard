"""Web sources that publish the author and the date as data, so a forum voice is a named person with a date.

Hacker News through the public Algolia API, Reddit through its public post JSON. No keys, bounded requests,
and nothing here raises: a failure is counted in `last` so the run log can say what was not heard.
"""
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

HN_SEARCH = "https://hn.algolia.com/api/v1/search"
HN_ITEM = "https://news.ycombinator.com/item?id="
HN_USER = "https://news.ycombinator.com/user?id="
MIN_TEXT = 120
TWO_YEARS = 2 * 365 * 86400
UA = {"User-Agent": "earshot-hackathon/0.1"}
MAX_REDDIT = 10
NOT_AUTHORS = {"", "[deleted]", "automoderator"}
STOPWORDS = set("""a an and are as at be been but by can cannot do does for from get has have how i in is it its
just my need needs no not of on or our so than that the their them then there they this to too up us very was we
were what when where which who why will with without you your wrong bad broken hard keep keeps lot lots many
much every each always never really""".split())

SELLER_TITLE = re.compile(r"^\s*(show|launch) hn\b", re.I)

last = {"hn_requests": 0, "hn_failed": 0, "reddit_ok": 0, "reddit_blocked": False,
        "gh_requests": 0, "gh_failed": 0, "so_requests": 0, "so_failed": 0}


def keywords(pain: str, n: int = 3) -> list[str]:
    """The n most specific words of a pain: stopwords out, longest first (first seen on ties), in sentence order."""
    words = [w for w in dict.fromkeys(re.findall(r"[a-z0-9]+", pain.lower())) if len(w) >= 3 and w not in STOPWORDS]
    keep = set(sorted(words, key=lambda w: -len(w))[:n])  # sorted() is stable, so ties keep sentence order
    return [w for w in words if w in keep]


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def _vid(url: str) -> str:
    return "web:" + hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:10]


def hn_voices(pains: list[str], *, get=httpx.get, max_queries: int = 6, per_query: int = 8, now=None) -> list[dict]:
    """Comments and stories from the last two years that use every keyword of a pain (two or three of them)."""
    since = int((now or time.time()) - TWO_YEARS)
    best: dict[str, dict] = {}
    for pain in [p for p in pains if p.strip()][:max_queries]:
        kws = keywords(pain)
        if len(kws) < 2:
            continue
        last["hn_requests"] += 1
        try:
            r = get(HN_SEARCH, params={"query": " ".join(kws), "tags": "(story,comment)", "hitsPerPage": per_query,
                                       "numericFilters": f"created_at_i>{since}"}, timeout=10)
            r.raise_for_status()
            hits = r.json().get("hits") or []
        except Exception:  # counted, never raised: HN being down must not stop a run
            last["hn_failed"] += 1
            continue
        for h in hits:
            body = _text(h.get("comment_text") or h.get("story_text") or "")
            author = (h.get("author") or "").strip()
            if len(body) < MIN_TEXT or not author or not h.get("objectID"):
                continue
            title = _text(h.get("story_title") or h.get("title") or "")
            covered = sum(k in body.lower() for k in kws)
            # A launch post is a seller, and a post missing a keyword was mostly about something else (measured live).
            if covered < len(kws) or SELLER_TITLE.match(title):
                continue
            url = HN_ITEM + str(h["objectID"])
            # Keyword coverage, not a meaning match, so it is capped at 0.5, below a good Moss or Tavily match.
            match = round(0.5 * covered / len(kws), 2)
            if url in best and best[url]["match"] >= match:
                continue
            best[url] = {"id": _vid(url), "repo": "news.ycombinator.com", "url": url,
                         "title": title, "body": body[:1500],
                         "author": author, "created": (h.get("created_at") or "")[:10], "pain": pain,
                         "match": match, "kind": "web", "profile": HN_USER + author}
    return sorted(best.values(), key=lambda v: -v["match"])


def reddit_post(url: str, *, get=httpx.get) -> dict | None:
    """Author, date and text of a Reddit post or comment from its public JSON. After one refusal, none for the run."""
    if last["reddit_blocked"]:
        return None
    path = urlparse(url).path.rstrip("/")
    parts = path.strip("/").split("/")
    if "comments" not in parts:
        return None
    i = parts.index("comments")
    pick = 1 if len(parts) > i + 3 else 0  # /r/<sub>/comments/<id>/<slug>/<comment id>: a comment, second listing
    target = f"https://www.reddit.com{path}.json"
    try:
        r = get(target, headers=UA, timeout=6, follow_redirects=True)
        r.raise_for_status()
        d = r.json()[pick]["data"]["children"][0]["data"]
    except Exception:  # 403, 429 or an HTML page: try the unlocker once, else stop asking Reddit this run
        try:
            d = json.loads(unlock(target) or "")[pick]["data"]["children"][0]["data"]
        except Exception:
            last["reddit_blocked"] = True
            return None
    author = (d.get("author") or "").strip()
    if author.lower() in NOT_AUTHORS:
        return None
    last["reddit_ok"] += 1
    created = datetime.fromtimestamp(float(d.get("created_utc") or 0), timezone.utc).strftime("%Y-%m-%d") \
        if d.get("created_utc") else ""
    return {"author": author, "created": created, "body": _text(d.get("selftext") or d.get("body") or ""),
            "profile": f"https://www.reddit.com/user/{author}"}


_URL_DATE = re.compile(r"/(20\d\d)/(0[1-9]|1[0-2])(?:/(0[1-9]|[12]\d|3[01]))?(?:/|$)")


def url_date(url: str) -> str:
    """A date written in the URL path (/2025/03/ or /2025/03/04/); the first of the month when no day. Never guessed."""
    m = _URL_DATE.search(urlparse(url).path)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3) or '01'}" if m else ""


def unlock(url: str, *, post=httpx.post) -> str | None:
    """Bright Data Web Unlocker as a last-resort fetch. None unless BRIGHTDATA_API_KEY and BRIGHTDATA_ZONE are set."""
    key, zone = os.environ.get("BRIGHTDATA_API_KEY"), os.environ.get("BRIGHTDATA_ZONE")
    if not key or not zone:
        return None
    try:
        r = post("https://api.brightdata.com/request", headers={"Authorization": f"Bearer {key}"},
                 json={"zone": zone, "url": url, "format": "raw"}, timeout=30)
    except Exception:
        return None
    body = r.text or ""
    # Bright Data can answer 200 with an error body, so the body decides, not the status.
    if r.status_code >= 400 or any(s in body[:500].lower() for s in ("bad_endpoint", "kyc", "zone not found")):
        return None
    return body


GH_REPO = re.compile(r"/repos/([^/]+)/([^/]+)$")
MAINTAINERS = ("MEMBER", "OWNER", "COLLABORATOR")
MAX_WIDE = 60  # issues added to the meaning match per run


def github_wide_voices(pains: list[str], *, get=None, skip_repos=(), sellers=(), max_queries: int = 5,
                       per_query: int = 15, now=None) -> list[dict]:
    """Issues from every public GitHub repository that use a pain's keywords, in the tracker-issue shape.

    They join the tracker issues, so the meaning match decides relevance and the author is looked up, scored and
    enriched exactly like a tracker lead. `get(path, **params)` returns parsed JSON or None (pipeline.gh).
    """
    last.update(gh_requests=0, gh_failed=0)
    if get is None:
        from app.pipeline import gh as get  # at call time: pipeline imports this module through scout_web
    since = datetime.fromtimestamp((now or time.time()) - TWO_YEARS, timezone.utc).strftime("%Y-%m-%d")
    skip = {str(r).lower() for r in skip_repos}
    names = [n for n in (re.sub(r"[^a-z0-9]", "", str(s).lower()) for s in sellers) if len(n) >= 4]
    out: dict[str, dict] = {}
    for pain in [p for p in pains if p.strip()][:max_queries]:
        kws = keywords(pain)
        if len(kws) < 2:
            continue
        last["gh_requests"] += 1
        try:
            res = get("/search/issues", q=f"{' '.join(kws)} is:issue in:title,body created:>={since}", per_page=per_query)
            if res is None:  # pipeline.gh answers None for anything but a 200
                raise LookupError("search refused")
            items = res.get("items")
        except Exception:  # counted, never raised: a refused search must not stop a run
            last["gh_failed"] += 1
            continue
        for i in items or []:
            try:
                user = i.get("user") or {}
                login, m = (user.get("login") or "").strip(), GH_REPO.search(i.get("repository_url") or "")
                body = _text(re.sub(r"(?s)<!--.*?-->", " ", i.get("body") or ""))
                # Pull requests, bots and maintainers are not buyers; a short body shows no problem.
                if ("pull_request" in i or not login or not m or login.endswith("[bot]") or user.get("type") == "Bot"
                        or i.get("author_association") in MAINTAINERS or len(body) < MIN_TEXT):
                    continue
                repo = f"{m[1]}/{m[2]}"
                handles = [re.sub(r"[^a-z0-9]", "", h.lower()) for h in (m[1], login)]
                if repo.lower() in skip or any(n in h for n in names for h in handles):
                    continue
                out.setdefault(i["html_url"], dict(id=f"{repo}#{i['number']}", repo=repo, url=i["html_url"],
                                                   title=_text(i.get("title") or ""), body=body[:1500], author=login,
                                                   created=(i.get("created_at") or "")[:10]))
            except Exception:  # one malformed item is skipped, not the search
                continue
    return list(out.values())[:MAX_WIDE]


SO_SEARCH = "https://api.stackexchange.com/2.3/search/advanced"


def so_voices(pains: list[str], *, get=httpx.get, max_queries: int = 4, per_query: int = 10, now=None) -> list[dict]:
    """Stack Overflow questions from the last two years that use a pain's keywords, each with its author and date."""
    last.update(so_requests=0, so_failed=0)
    since = int((now or time.time()) - TWO_YEARS)
    best: dict[str, dict] = {}
    for pain in [p for p in pains if p.strip()][:max_queries]:
        kws = keywords(pain)
        if len(kws) < 2:
            continue
        last["so_requests"] += 1
        try:
            r = get(SO_SEARCH, params={"order": "desc", "sort": "relevance", "q": " ".join(kws), "site": "stackoverflow",
                                       "filter": "withbody", "pagesize": per_query, "fromdate": since}, timeout=10)
            r.raise_for_status()
            data = r.json()
            items = data.get("items") or []
        except Exception:  # counted, never raised
            last["so_failed"] += 1
            continue
        for q in items:
            try:
                owner, url, body = q.get("owner") or {}, q.get("link") or "", _text(q.get("body") or "")
                author = _text(owner.get("display_name") or "")
                if (not url or not author or not owner.get("user_id") or owner.get("user_type") == "does_not_exist"
                        or len(body) < MIN_TEXT):
                    continue
                title = _text(q.get("title") or "")
                covered = sum(k in f"{title} {body}".lower() for k in kws)
                if covered < 2:
                    continue
                # Keyword coverage, not a meaning match, so it is capped at 0.5 like Hacker News.
                match = round(0.5 * covered / len(kws), 2)
                if url in best and best[url]["match"] >= match:
                    continue
                created = datetime.fromtimestamp(float(q["creation_date"]), timezone.utc).strftime("%Y-%m-%d")
                best[url] = {"id": _vid(url), "repo": "stackoverflow.com", "url": url, "title": title,
                             "body": body[:1500], "author": author, "created": created, "pain": pain, "match": match,
                             "kind": "web", "profile": owner.get("link") or url, "login": f"so:{owner['user_id']}"}
            except Exception:
                continue
        if data.get("backoff"):  # the API asked us to wait: no more calls this run
            break
    return sorted(best.values(), key=lambda v: -v["match"])
