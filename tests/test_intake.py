"""Intake: a website or repository in, product text out. Readers are fakes: nothing touches the network."""
import os

os.environ.setdefault("GRAPH_PATH", "/tmp/earshot-intake-test.kuzu")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import intake, main, pipeline  # noqa: E402


@pytest.mark.parametrize("raw,kind,url,repo", [
    ("flexprice.io", "site", "https://flexprice.io", ""),
    ("  https://flexprice.io/pricing/ ", "site", "https://flexprice.io/pricing", ""),
    ("http://www.Flexprice.io", "site", "https://www.flexprice.io", ""),
    ("github.com/flexprice/flexprice", "repo", "https://github.com/flexprice/flexprice", "flexprice/flexprice"),
    ("https://github.com/flexprice/flexprice/tree/main", "repo", "https://github.com/flexprice/flexprice", "flexprice/flexprice"),
    ("https://www.github.com/flexprice/flexprice.git", "repo", "https://github.com/flexprice/flexprice", "flexprice/flexprice"),
    ("flexprice/flexprice", "repo", "https://github.com/flexprice/flexprice", "flexprice/flexprice"),
])
def test_normalize_accepts(raw, kind, url, repo):
    assert intake.normalize(raw) == {"kind": kind, "url": url, "repo": repo}


@pytest.mark.parametrize("raw", [
    "", "   ", "two words.io", "ftp://flexprice.io", "javascript:alert(1)", "https://user:pw@flexprice.io",
    "https://user@flexprice.io", "http://127.0.0.1", "http://10.0.0.5/admin", "http://[::1]/", "http://2130706433",
    "http://127.1", "localhost", "http://localhost/x", "intranet", "https://foo.local", "https://flexprice.io:8080",
    "https://flexprice.io:99999", "github.com/flexprice", "github.com", "a/b/c", "../etc", "flexprice/..",
    "-bad.io", "x" * 200, "https://" + "a" * 195 + ".io",
])
def test_normalize_rejects(raw):
    with pytest.raises(ValueError) as e:
        intake.normalize(raw)
    assert e.value.args[0] and "Traceback" not in e.value.args[0]


def _pages(**by_path):
    """A fake extract: every path in by_path that is asked for comes back, the rest are 'failed'."""
    def extract(urls):
        return [{"url": u, "raw_content": by_path[u.split("//")[1]]} for u in urls if u.split("//")[1] in by_path]
    return extract


def test_site_reads_home_and_the_pages_that_exist():
    asked = []
    ex = _pages(**{"flexprice.io": "Usage billing for AI.", "flexprice.io/pricing": "Free then $99."})

    def spy(urls):
        asked.append(urls)
        return ex(urls)
    r = intake.read_product("flexprice.io", extract=spy)
    assert asked == [["https://flexprice.io", "https://flexprice.io/pricing", "https://flexprice.io/docs", "https://flexprice.io/about"]]
    assert r["status"] == "ok" and r["name_hint"] == "flexprice" and r["repo"] == ""
    assert r["sources"] == ["https://flexprice.io", "https://flexprice.io/pricing"]
    assert r["source_text"] == "https://flexprice.io\nUsage billing for AI.\n\nhttps://flexprice.io/pricing\nFree then $99."


def test_site_with_a_path_also_reads_that_page_and_drops_www_from_the_hint():
    seen = []
    intake.read_product("https://www.flexprice.io/blog", extract=lambda urls: seen.append(urls) or [{"url": urls[0], "raw_content": "x"}])
    assert "https://www.flexprice.io/blog" in seen[0]
    assert intake.read_product("www.flexprice.io", extract=lambda u: [{"url": u[0], "raw_content": "x"}])["name_hint"] == "flexprice"


def test_nothing_readable():
    for rows in ([], None, [{"url": "https://a.io", "raw_content": "  "}, {"url": "https://a.io"}]):
        assert intake.read_product("a.io", extract=lambda u, rows=rows: rows) == {"status": "error", "reason": "could not read that site"}

    def boom(urls):
        raise RuntimeError("tvly-SECRET exploded")
    r = intake.read_product("a.io", extract=boom)
    assert r["status"] == "error" and "SECRET" not in r["reason"]


def test_no_reader_configured(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    r = intake.read_product("flexprice.io")
    assert r["status"] == "error" and "no page reader" in r["reason"]


def test_bad_target_is_an_error_not_a_raise():
    r = intake.read_product("http://127.0.0.1", extract=lambda u: [])
    assert r["status"] == "error" and "IP address" in r["reason"]


def test_text_is_trimmed_to_12000_with_every_page_kept():
    big = "w" * 50000
    r = intake.read_product("a.io", extract=_pages(**{"a.io": big, "a.io/pricing": big, "a.io/docs": big}))
    assert len(r["source_text"]) <= 12000 and len(r["sources"]) == 3
    assert "https://a.io/docs" in r["source_text"]  # a long home page does not crowd the others out


def test_repo_without_homepage_never_needs_the_page_reader(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    got = []
    r = intake.read_product("github.com/flexprice/flexprice", fetch_repo=lambda repo: got.append(repo) or
                            {"description": "Open-source billing.", "readme": "# Flexprice\nMetering.", "homepage": ""})
    assert got == ["flexprice/flexprice"]
    assert r == {"status": "ok", "source_text": "https://github.com/flexprice/flexprice\nOpen-source billing.\n\n# Flexprice\nMetering.",
                 "sources": ["https://github.com/flexprice/flexprice"], "repo": "flexprice/flexprice", "name_hint": "flexprice"}


def test_repo_with_homepage_also_reads_the_site():
    r = intake.read_product("flexprice/flexprice", extract=_pages(**{"flexprice.io": "The site."}),
                            fetch_repo=lambda repo: {"description": "d", "readme": "r", "homepage": "https://flexprice.io/"})
    assert r["sources"] == ["https://github.com/flexprice/flexprice", "https://flexprice.io"]
    assert r["repo"] == "flexprice/flexprice" and "The site." in r["source_text"]


def test_repo_homepage_that_is_unusable_is_skipped():
    for home in ("http://localhost:3000", "not a url", "https://github.com/flexprice/flexprice"):
        r = intake.read_product("flexprice/flexprice", extract=lambda u: [{"url": "https://x.io", "raw_content": "x"}],
                                fetch_repo=lambda repo, home=home: {"description": "d", "readme": "", "homepage": home})
        assert r["status"] == "ok" and r["sources"] == ["https://github.com/flexprice/flexprice"]


def test_repo_that_cannot_be_read_or_is_empty():
    def gone(repo):
        raise RuntimeError("404 with Bearer ghp_SECRET")
    r = intake.read_product("a/b", fetch_repo=gone)
    assert r["status"] == "error" and "ghp_" not in r["reason"] and "SECRET" not in r["reason"]
    assert intake.read_product("a/b", fetch_repo=lambda repo: {"description": "", "readme": "", "homepage": ""})["status"] == "error"


def _site(text):
    return intake.read_product("flexprice.io", extract=lambda u: [{"url": "https://flexprice.io", "raw_content": text}])


def test_linked_repo_one_link():
    assert _site("Star us: https://github.com/acme-labs/tool-x.git ok")["repo"] == "acme-labs/tool-x"


def test_linked_repos_prefer_owner_or_name_matching_the_site():
    text = ("built on https://github.com/golang/go and https://github.com/golang/go and https://github.com/golang/go "
            "see https://github.com/some-fork/flexprice-docs and https://github.com/flexprice/flexprice "
            "and https://github.com/flexprice/flexprice/issues/4")
    assert _site(text)["repo"] == "flexprice/flexprice"  # matches the site, and is the most linked of the matches
    assert _site("https://github.com/Flexprice-Labs/a https://github.com/other/flexprice-sdk")["repo"] == "Flexprice-Labs/a"  # tie: first seen


def test_linked_repos_without_a_match_are_not_guessed():
    assert _site("https://github.com/golang/go and https://github.com/rust-lang/rust")["repo"] == ""
    assert _site("no links at all")["repo"] == ""


def test_github_site_sections_are_not_repos():
    assert _site("https://github.com/sponsors/x https://github.com/features/actions https://github.com/orgs/flexprice/people")["repo"] == ""


def test_linked_repo_is_found_even_when_it_falls_past_the_trim():
    r = intake.read_product("flexprice.io", extract=lambda u: [{"url": "https://flexprice.io", "raw_content": "w" * 20000 + " github.com/flexprice/flexprice"}])
    assert len(r["source_text"]) == 12000 and "github.com" not in r["source_text"] and r["repo"] == "flexprice/flexprice"


def test_no_reason_carries_a_token(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TOKEN123")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_TOKEN123")

    def boom(*a):
        raise RuntimeError("tvly-TOKEN123 ghp_TOKEN123")
    for r in (intake.read_product("a.io", extract=boom), intake.read_product("a/b", fetch_repo=boom),
              intake.read_product("a/b"), intake.read_product("x y"), intake.read_product("a.io", extract=lambda u: [])):
        assert "TOKEN123" not in str(r)


# --- the HTTP side: RunIn and the run thread ------------------------------------

@pytest.fixture
def api(monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)) or pipeline.state.update(running=False))
    monkeypatch.setattr(main.autopilot, "after_run", lambda: None)

    class Inline:  # runs the thread's work before start() returns
        def __init__(self, target, args, daemon): self.target, self.args = target, args
        def start(self): self.target(*self.args)
    monkeypatch.setattr(main.threading, "Thread", Inline)
    monkeypatch.setitem(pipeline.state, "running", False)
    monkeypatch.setitem(pipeline.state, "error", "")
    monkeypatch.setattr(main, "MIN_RUN_GAP_SECONDS", 0)  # these tests start several runs in a row
    main.reset_run_budget()
    return TestClient(main.app), calls


def test_run_needs_a_description_or_a_target(api):
    c, calls = api
    assert c.post("/api/run", json={}).status_code == 422
    assert c.post("/api/run", json={"description": "too short", "target": "  "}).status_code == 422
    assert c.post("/api/run", json={"target": "x" * 201}).status_code == 422
    assert c.post("/api/run", json={"description": "d" * 20001}).status_code == 422
    assert c.post("/api/run", json={"description": "d" * 25, "product_repo": "bad repo"}).status_code == 422
    assert calls == [] and pipeline.state["running"] is False


def test_run_with_a_description_is_unchanged(api, monkeypatch):
    c, calls = api
    monkeypatch.setattr(main.intake, "read_product", lambda t: pytest.fail("a typed description is not read from a site"))
    assert c.post("/api/run", json={"description": "d" * 25, "product_repo": "o/r"}).status_code == 202
    (args, kw), = calls
    assert args[:2] == ("d" * 25, "o/r") and kw["sources"] is None and not kw["keep_log"]


def test_run_with_a_target_reads_the_site_first(api, monkeypatch):
    c, calls = api
    monkeypatch.setattr(main.intake, "read_product", lambda t: {"status": "ok", "source_text": "page text " * 5,
                        "sources": ["https://flexprice.io"], "repo": "flexprice/flexprice", "name_hint": "flexprice"})
    assert c.post("/api/run", json={"target": " flexprice.io "}).status_code == 202
    (args, kw), = calls
    assert args[:2] == ("page text " * 5, "flexprice/flexprice") and kw["sources"] == ["https://flexprice.io"] and kw["keep_log"]
    assert pipeline.state["log"][0] == "Planner: reading https://flexprice.io to learn what you sell"
    calls.clear()
    c.post("/api/run", json={"target": "flexprice.io", "product_repo": "mine/own"})
    assert calls[0][0][1] == "mine/own"  # the request's repository wins over the detected one


def test_run_with_an_unreadable_target_stops_with_the_reason(api, monkeypatch):
    c, calls = api
    monkeypatch.setattr(main.intake, "read_product", lambda t: {"status": "error", "reason": "could not read that site"})
    assert c.post("/api/run", json={"target": "flexprice.io"}).status_code == 202
    assert calls == [] and pipeline.state["error"] == "could not read that site" and pipeline.state["running"] is False
    assert pipeline.state["log"][-1] == "Planner: could not read that site"
    c.post("/api/run", json={"target": "http://127.0.0.1"})
    assert "IP address" in pipeline.state["error"] and pipeline.state["running"] is False


def test_a_run_already_in_progress_is_a_409(api):
    c, calls = api
    pipeline.state["running"] = True
    assert c.post("/api/run", json={"target": "flexprice.io"}).status_code == 409
    assert calls == []
    pipeline.state["running"] = False
