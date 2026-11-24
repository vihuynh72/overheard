import hashlib

from app import scout_web as w

LONG = "We keep chasing late invoices by hand and our usage billing is a spreadsheet nightmare every month. " * 2


def hit(url, score=0.8, content=LONG, **kw):
    return {"url": url, "title": "t", "content": content, "score": score, **kw}


def fake(table):
    calls = []

    def search(query, domains):
        calls.append((query, domains))
        return table(query) if callable(table) else table
    search.calls = calls
    return search


def test_queries_one_per_pain_no_site_operator():
    qs = w.queries(["late invoices pile up", "usage metering is wrong"])
    assert [q["pain"] for q in qs] == ["late invoices pile up", "usage metering is wrong"]
    assert all("site:" not in q["query"] and "late invoices pile up" in qs[0]["query"] for q in qs)


def test_queries_area_matches_most_related_pain_and_is_deterministic():
    pains = ["customers pay late and nobody chases", "we cannot meter usage per customer"]
    qs = w.queries(pains, ["usage metering", "collections"])
    assert len(qs) == 4
    assert qs[2]["pain"] == pains[1] and "usage metering" in qs[2]["query"]
    assert qs[3]["pain"] == pains[0]  # tie / no overlap falls back to the first pain
    assert qs == w.queries(pains, ["usage metering", "collections"])


def test_queries_capped_at_12():
    assert len(w.queries([f"pain {i}" for i in range(20)], w.PROCESS_AREAS)) == 12


def test_no_key_no_search_returns_empty(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert w.find_voices(["late invoices"]) == []


def test_signal_shape_and_domains_passed():
    s = fake([hit("https://www.reddit.com/user/ada/comments/1", 0.8123, published_date="2025-03-04T10:00:00Z")])
    [v] = w.find_voices(["late invoices"], search=s)
    assert v == {"id": "web:" + hashlib.sha1(b"https://www.reddit.com/user/ada/comments/1").hexdigest()[:10],
                 "repo": "reddit.com", "url": "https://www.reddit.com/user/ada/comments/1", "title": "t",
                 "body": LONG.strip()[:1500], "author": "ada", "created": "2025-03-04",
                 "pain": "late invoices", "match": 0.81, "kind": "web"}
    assert "reddit.com" in s.calls[0][1] and "g2.com" in s.calls[0][1]


def test_score_threshold_and_body_trim():
    s = fake([hit("https://dev.to/a", 0.44), hit("https://dev.to/b", 0.45, content="x" * 3000)])
    [v] = w.find_voices(["p"], search=s)
    assert v["url"] == "https://dev.to/b" and len(v["body"]) == 1500


def test_dedupe_by_url_keeps_higher_score():
    table = {"a": [hit("https://dev.to/a", 0.5)], "b": [hit("https://dev.to/a", 0.9)]}
    s = fake(lambda q: table["a"] if "one" in q else table["b"])
    [v] = w.find_voices(["one", "two"], search=s)
    assert v["match"] == 0.9
    s = fake(lambda q: table["b"] if "one" in q else table["a"])
    assert w.find_voices(["one", "two"], search=s)[0]["match"] == 0.9


def test_short_content_dropped():
    assert w.find_voices(["p"], search=fake([hit("https://dev.to/a", content="too short")])) == []


def test_vendor_pages_dropped():
    s = fake([hit("https://stripe.com/docs/billing"), hit("https://acme.io/pricing"), hit("https://acme.io/blog/x"),
              hit("https://acme.io/features/y"), hit("https://acme.io/product"),
              hit("https://reddit.com/r/saas/blog/ok"), hit("https://community.xero.com/t/1"),
              hit("https://news.ycombinator.com/item?id=1")])
    urls = {v["url"] for v in w.find_voices(["p"], search=s)}
    assert urls == {"https://reddit.com/r/saas/blog/ok", "https://community.xero.com/t/1",
                    "https://news.ycombinator.com/item?id=1"}


def test_author_patterns():
    assert w._author("https://www.reddit.com/user/ada/") == "ada"
    assert w._author("https://old.reddit.com/u/bob_1/comments/x") == "bob_1"
    assert w._author("https://reddit.com/r/saas/comments/abc/title/") == ""
    assert w._author("https://news.ycombinator.com/item?id=42") == ""
    assert w._author("https://x.com/carol/status/123") == "carol"
    assert w._author("https://x.com/home") == ""
    assert w._author("https://dev.to/dave/post") == ""


def test_created_parsing():
    assert w._date("2025-03-04") == "2025-03-04"
    assert w._date("Tue, 04 Mar 2025 10:00:00 GMT") == "2025-03-04"
    assert w._date("last Tuesday") == ""
    [v] = w.find_voices(["p"], search=fake([hit("https://dev.to/a", published_date="garbage")]))
    assert v["created"] == ""


def test_raising_search_is_skipped():
    def search(q, d):
        if "boom" in q:
            raise RuntimeError("sekrit-key leaked?")
        return [hit("https://dev.to/a")]
    [v] = w.find_voices(["boom", "fine"], search=search)
    assert v["pain"] == "fine"


def test_sorted_by_match_desc():
    s = fake([hit("https://dev.to/a", 0.5), hit("https://dev.to/b", 0.9), hit("https://dev.to/c", 0.7)])
    assert [v["match"] for v in w.find_voices(["p"], search=s)] == [0.9, 0.7, 0.5]


def test_as_people_groups_by_author_else_signal_id():
    s = fake([hit("https://www.reddit.com/user/ada/comments/1", 0.9), hit("https://reddit.com/u/ada/comments/2", 0.8),
              hit("https://news.ycombinator.com/item?id=1", 0.7), hit("https://x.com/carol/status/9", 0.6)])
    people = dict(w.as_people(w.find_voices(["p"], search=s)))
    assert len(people["reddit.com/u/ada"]) == 2
    assert len(people["x.com/carol"]) == 1
    anon = [k for k in people if k.startswith("web:")]
    assert len(anon) == 1 and people[anon[0]][0]["repo"] == "news.ycombinator.com"


def test_default_search_uses_tavily_client_at_call_time(monkeypatch):
    import sys
    import types
    seen = {}

    class Client:
        def __init__(self, key):
            seen["key"] = key

        def search(self, **kw):
            seen["kw"] = kw
            return {"results": [hit("https://dev.to/a")]}
    monkeypatch.setitem(sys.modules, "tavily", types.SimpleNamespace(TavilyClient=Client))
    monkeypatch.setenv("TAVILY_API_KEY", "sekrit-tavily")
    [v] = w.find_voices(["p"], per_query=3)
    assert seen["key"] == "sekrit-tavily" and seen["kw"]["max_results"] == 3 and seen["kw"]["search_depth"] == "basic"
    assert seen["kw"]["time_range"] == "year"
    assert "dev.to" in seen["kw"]["include_domains"] and "sekrit-tavily" not in str(v)


def test_clean_domains_strips_scheme_www_path_and_lowercases():
    got = w.clean_domains(["HTTPS://www.News.YCombinator.com/item?id=1", "reddit.com/r/saas", "  g2.com  "])
    assert got == ["news.ycombinator.com", "reddit.com", "g2.com"]


def test_clean_domains_drops_login_vendor_and_non_hostnames():
    got = w.clean_domains(["linkedin.com", "uk.linkedin.com", "stripe.com", "billing.stripe.com", "localhost",
                           "192.168.0.1", "intranet.local", "not a host", "host:8080", "", "dev.to", "dev.to"])
    assert got == ["dev.to"]


def test_clean_domains_caps_at_eight_and_empty_is_empty():
    assert len(w.clean_domains([f"site{i}.com" for i in range(12)])) == 8
    assert w.clean_domains(None) == [] and w.clean_domains([]) == []


def test_find_voices_searches_only_given_domains_and_falls_back():
    s = fake([hit("https://news.ycombinator.com/item?id=1")])
    w.find_voices(["p"], search=s, domains=["https://www.news.ycombinator.com/", "linkedin.com"])
    assert s.calls[0][1] == ["news.ycombinator.com"]
    for empty in (None, [], ["linkedin.com"]):
        s = fake([hit("https://dev.to/a")])
        w.find_voices(["p"], search=s, domains=empty)
        assert s.calls[0][1] == w._domains()


def test_vendor_path_rule_uses_the_chosen_domains():
    s = fake([hit("https://forum.example-shop.com/features/x"), hit("https://acme.io/features/y")])
    urls = {v["url"] for v in w.find_voices(["p"], search=s, domains=["forum.example-shop.com"])}
    assert urls == {"https://forum.example-shop.com/features/x"}


def _voice(url, author=""):
    return {"url": url, "author": author, "repo": w._host(url)}


def test_drop_sellers_by_handle_and_x_account_segment():
    voices = [_voice("https://reddit.com/r/x/1", "Acme_Support"), _voice("https://x.com/rival_co/status/1"),
              _voice("https://twitter.com/Acme/status/2"), _voice("https://x.com/buyer/status/3", "buyer"),
              _voice("https://news.ycombinator.com/item?id=1")]
    kept = w.drop_sellers(voices, ["Acme", "Rival Co"])
    assert [v["url"] for v in kept] == ["https://x.com/buyer/status/3", "https://news.ycombinator.com/item?id=1"]


def test_drop_sellers_ignores_names_under_four_characters_and_other_hosts_paths():
    voices = [_voice("https://reddit.com/r/x/1", "bobby"), _voice("https://x.com/acme/status/1"),
              _voice("https://g2.com/acme/reviews")]
    assert w.drop_sellers(voices, ["bob", "", "A c"]) == voices  # "bob" and "ac" are too short to match on
    assert [v["url"] for v in w.drop_sellers(voices, ["acme"])] == ["https://reddit.com/r/x/1", "https://g2.com/acme/reviews"]


def test_x_system_paths_are_not_authors():
    assert w._author("https://x.com/i/status/123") == ""
    assert w._author("https://x.com/ada_l/status/123") == "ada_l"
