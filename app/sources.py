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

last = {"hn_requests": 0, "hn_failed": 0, "reddit_ok": 0, "reddit_blocked": False}


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
