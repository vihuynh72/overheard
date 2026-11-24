import json

import pytest

from app import sources as s

BODY = "We need usage billing and our invoices are wrong every month because metering drops events. " * 2


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    monkeypatch.setattr(s, "last", {"hn_requests": 0, "hn_failed": 0, "reddit_ok": 0, "reddit_blocked": False})
    monkeypatch.delenv("BRIGHTDATA_API_KEY", raising=False)
    monkeypatch.delenv("BRIGHTDATA_ZONE", raising=False)


class Resp:
    def __init__(self, data=None, status=200, text=None):
        self.data, self.status_code, self.text = data, status, text if text is not None else json.dumps(data)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        if self.data is None:
            raise ValueError("not json")
        return self.data


def test_keywords_drop_stopwords_keep_the_specific_words_in_order():
    assert s.keywords("usage-based billing invoices are wrong") == ["usage", "billing", "invoices"]
    assert s.keywords("need credit-based pricing with quotas") == ["credit", "pricing", "quotas"]
    assert s.keywords("it is not") == []
    assert s.keywords("Metering events double counted") == s.keywords("metering events double counted")


def hit(oid, text=BODY, author="ada", **kw):
    return {"objectID": oid, "author": author, "created_at": "2026-02-03T04:05:06Z", "comment_text": text,
            "story_title": "Ask HN: billing", **kw}


def test_hn_voices_shape_html_stripped_short_and_off_topic_and_launches_dropped():
    calls = []

    def get(url, params, timeout):
        calls.append((url, params, timeout))
        return Resp({"hits": [hit(1, "<p>" + BODY.replace("invoices", "<i>invoices</i>") + "&amp;</p>"),
                              hit(2, "usage billing invoices"),  # too short
                              hit(3, "usage billing " + "x" * 200),  # misses a keyword
                              hit(4, BODY, title="Show HN: my billing tool", story_title=None),
                              hit(5, BODY, author="")]})
    [v] = s.hn_voices(["usage-based billing invoices are wrong"], get=get, now=1_800_000_000)
    assert v == {"id": v["id"], "repo": "news.ycombinator.com", "url": "https://news.ycombinator.com/item?id=1",
                 "title": "Ask HN: billing", "body": v["body"], "author": "ada", "created": "2026-02-03",
                 "pain": "usage-based billing invoices are wrong", "match": 0.5, "kind": "web",
                 "profile": "https://news.ycombinator.com/user?id=ada"}
    assert "<" not in v["body"] and v["body"].endswith("&") and v["id"].startswith("web:")
    url, params, timeout = calls[0]
    assert params["query"] == "usage billing invoices" and params["tags"] == "(story,comment)" and timeout == 10
    assert params["numericFilters"] == f"created_at_i>{1_800_000_000 - s.TWO_YEARS}"


def test_hn_voices_never_raises_counts_failures_and_caps_requests():
    calls = []

    def get(*a, **k):
        calls.append(1)
        raise RuntimeError("down")
    pains = [f"usage billing invoices number{i}" for i in range(10)]
    assert s.hn_voices(pains, get=get) == []
    assert len(calls) == 6 and s.last["hn_requests"] == 6 and s.last["hn_failed"] == 6


def listing(author="bob", created=1746500000, text="post text", comment=None):
    post = {"kind": "Listing", "data": {"children": [{"data": {"author": author, "created_utc": created, "selftext": text}}]}}
    comments = {"kind": "Listing", "data": {"children": [{"data": comment or {}}]}}
    return [post, comments]


def test_reddit_post_parses_post_and_comment_permalinks():
    seen = []

    def get(url, **k):
        seen.append((url, k["headers"]["User-Agent"], k["timeout"]))
        return Resp(listing(comment={"author": "cat", "created_utc": 1746600000, "body": "a comment"}))
    got = s.reddit_post("https://www.reddit.com/r/saas/comments/abc/slug/?utm=x", get=get)
    assert got == {"author": "bob", "created": "2025-05-06", "body": "post text", "profile": "https://www.reddit.com/user/bob"}
    assert seen[0] == ("https://www.reddit.com/r/saas/comments/abc/slug.json", "earshot-hackathon/0.1", 6)
    assert s.reddit_post("https://old.reddit.com/r/saas/comments/abc/slug/c1/", get=get)["author"] == "cat"
    assert s.reddit_post("https://www.reddit.com/user/bob/", get=get) is None  # not a post
    assert s.last["reddit_ok"] == 2


def test_reddit_deleted_and_automoderator_skipped():
    for name in ("[deleted]", "AutoModerator"):
        assert s.reddit_post("https://reddit.com/r/a/comments/b/c", get=lambda u, **k: Resp(listing(author=name))) is None
    assert not s.last["reddit_blocked"]


def test_reddit_gives_up_for_the_run_after_one_refusal():
    calls = []

    def get(url, **k):
        calls.append(url)
        return Resp(None, status=200, text="<html>blocked</html>")
    for _ in range(5):
        assert s.reddit_post("https://reddit.com/r/a/comments/b/c", get=get) is None
    assert len(calls) == 1 and s.last["reddit_blocked"]


def test_url_date():
    assert s.url_date("https://x.com/blog/2025/03/04/post") == "2025-03-04"
    assert s.url_date("https://x.com/2024/11/") == "2024-11-01"
    assert s.url_date("https://x.com/r/2025/post") == "" and s.url_date("https://x.com/2025/13/") == ""


def test_unlock_is_off_without_key_and_reads_the_body_not_the_status(monkeypatch):
    assert s.unlock("https://reddit.com/x.json", post=lambda *a, **k: 1 / 0) is None
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "k")
    monkeypatch.setenv("BRIGHTDATA_ZONE", "web_unlocker1")
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, json=json)
        return Resp(None, status=200, text='{"error":"bad_endpoint"}')
    assert s.unlock("https://reddit.com/x.json", post=post) is None
    assert sent == {"url": "https://api.brightdata.com/request",
                    "json": {"zone": "web_unlocker1", "url": "https://reddit.com/x.json", "format": "raw"}}
    assert s.unlock("u", post=lambda *a, **k: Resp(None, text='[{"ok":1}]')) == '[{"ok":1}]'


def _issue(n=1, **kw):
    return {"html_url": f"https://github.com/acme/shop/issues/{n}", "number": n, "title": "Invoices <b>wrong</b>",
            "body": "<!-- template -->" + BODY, "user": {"login": "ada", "type": "User"}, "author_association": "NONE",
            "created_at": "2026-03-04T05:06:07Z", "repository_url": "https://api.github.com/repos/acme/shop", **kw}


def _gh(items):
    calls = []

    def get(path, **params):
        calls.append((path, params))
        return {"items": items} if not isinstance(items, Exception) and items is not None else items
    get.calls = calls
    return get


def test_github_wide_shape_recency_and_filters():
    items = [_issue(1), _issue(2, pull_request={}), _issue(3, user={"login": "dependabot[bot]", "type": "User"}),
             _issue(4, user={"login": "robo", "type": "Bot"}), _issue(5, body="too short"),
             _issue(6, author_association="MEMBER"),
             _issue(7, repository_url="https://api.github.com/repos/watched/tracker"),
             _issue(8, repository_url="https://api.github.com/repos/flexprice/flexprice"),
             _issue(9, user={"login": "lago-dev", "type": "User"}), {"junk": 1}]
    get = _gh(items)
    got = s.github_wide_voices(["usage-based billing invoices are wrong"], get=get, skip_repos=["Watched/Tracker"],
                               sellers=["Flexprice", "Lago"], now=1_800_000_000)
    assert got == [dict(id="acme/shop#1", repo="acme/shop", url="https://github.com/acme/shop/issues/1",
                        title="Invoices wrong", body=BODY.strip(), author="ada", created="2026-03-04")]
    [(path, params)] = get.calls
    assert path == "/search/issues" and params["per_page"] == 15
    assert params["q"] == "usage billing invoices is:issue in:title,body created:>=2025-01-15"


def test_github_wide_request_cap_dedupe_and_issue_cap():
    get = _gh([_issue(n) for n in range(1, 16)])
    got = s.github_wide_voices([f"usage billing invoices wrong number{n}" for n in range(9)], get=get)
    assert len(get.calls) == 5 and len(got) == 15  # five searches at most; the same issue is kept once
    many_items = iter([[_issue(n + 100 * k) for n in range(15)] for k in range(1, 6)])
    got = s.github_wide_voices(["usage billing invoices"] * 5, get=lambda path, **p: {"items": next(many_items)})
    assert len(got) == s.MAX_WIDE


def test_github_wide_failure_is_counted_and_never_raises():
    def boom(path, **params):
        raise RuntimeError("down")
    assert s.github_wide_voices(["usage billing invoices"], get=boom) == [] and s.last["gh_failed"] == 1
    assert s.github_wide_voices(["usage billing invoices"], get=lambda path, **p: None) == []  # gh() on a non-200
    assert s.last == {**s.last, "gh_requests": 1, "gh_failed": 1}
    assert s.github_wide_voices(["usage billing invoices"], get=lambda path, **p: {}) == [] and s.last["gh_failed"] == 0


def _q(n=1, **kw):
    return {"link": f"https://stackoverflow.com/questions/{n}/x", "title": "Usage billing &amp; invoices",
            "body": "<p>" + BODY + "</p>", "creation_date": 1_770_000_000, "is_answered": False,
            "owner": {"display_name": "Grace H", "user_id": 42, "user_type": "registered",
                      "link": "https://stackoverflow.com/users/42/grace-h"}, **kw}


def _so(data, status=200):
    calls = []

    def get(url, **kw):
        calls.append((url, kw))
        return Resp(data, status)
    get.calls = calls
    return get


def test_so_shape_html_stripped_and_filters():
    gone = {"display_name": "user99", "user_type": "does_not_exist"}
    get = _so({"items": [_q(1), _q(2, body="<p>short</p>"), _q(3, owner=gone),
                         _q(4, body="<p>" + "nothing related to the topic at all here. " * 5 + "</p>", title="x")]})
    [v] = s.so_voices(["usage-based billing invoices are wrong"], get=get, now=1_800_000_000)
    assert v == {"id": s._vid(v["url"]), "repo": "stackoverflow.com", "url": "https://stackoverflow.com/questions/1/x",
                 "title": "Usage billing & invoices", "body": BODY.strip(), "author": "Grace H", "created": "2026-02-02",
                 "pain": "usage-based billing invoices are wrong", "match": 0.5, "kind": "web",
                 "profile": "https://stackoverflow.com/users/42/grace-h", "login": "so:42"}
    [(url, kw)] = get.calls
    assert url == s.SO_SEARCH and kw["params"]["q"] == "usage billing invoices" and kw["params"]["site"] == "stackoverflow"
    assert kw["params"]["fromdate"] == 1_800_000_000 - s.TWO_YEARS and kw["params"]["filter"] == "withbody"


def test_so_request_cap_and_failure_counted():
    get = _so({"items": [_q(1)]})
    assert len(s.so_voices(["usage billing invoices"] * 9, get=get)) == 1 and len(get.calls) == 4
    assert s.so_voices(["usage billing invoices"], get=_so({}, 429)) == [] and s.last["so_failed"] == 1

    def boom(url, **kw):
        raise RuntimeError("down")
    assert s.so_voices(["usage billing invoices"] * 2, get=boom) == [] and s.last["so_failed"] == 2


def test_so_backoff_stops_calling_for_the_run():
    get = _so({"items": [_q(1)], "backoff": 10})
    assert len(s.so_voices(["usage billing invoices"] * 4, get=get)) == 1 and len(get.calls) == 1
