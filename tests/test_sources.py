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
