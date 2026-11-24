import httpx
import pytest

from app import enrich as e

KEY = "sekrit-hunter-key"
FINDER = {"data": {"email": "ada@nozzle.io", "score": 94, "position": "CTO",
                   "linkedin_url": "https://linkedin.com/in/ada",
                   "sources": [{"uri": f"https://x.com/{i}"} for i in range(5)],
                   "verification": {"status": "valid"}}}
VERIFIER = {"data": {"status": "valid", "score": 99, "webmail": False, "disposable": False}}


@pytest.fixture(autouse=True)
def hunter_key(monkeypatch):
    monkeypatch.setenv("HUNTER_API_KEY", KEY)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def reply(finder=FINDER, verifier=VERIFIER, status=200):
    def h(req):
        body = finder if req.url.path.endswith("email-finder") else verifier
        return httpx.Response(status, json=body)
    return client(h)


def test_find_email_found_sends_params():
    seen = []

    def h(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=FINDER)

    r = e.find_email("Ada Lovelace", "nozzle.io", client=client(h))
    assert r == {"status": "found", "email": "ada@nozzle.io", "score": 94, "verification": "valid",
                 "position": "CTO", "linkedin_url": "https://linkedin.com/in/ada",
                 "sources": ["https://x.com/0", "https://x.com/1", "https://x.com/2"],
                 "source": "hunter"}
    assert seen == [{"domain": "nozzle.io", "full_name": "Ada Lovelace", "api_key": KEY}]


def test_find_email_not_found():
    c = reply(finder={"data": {"email": None}})
    assert e.find_email("A B", "x.io", client=c) == {"status": "not_found"}


def test_no_hunter_key(monkeypatch):
    monkeypatch.delenv("HUNTER_API_KEY")
    assert e.find_email("A B", "x.io") == {"status": "skipped", "reason": "no HUNTER_API_KEY"}
    assert e.verify_email("a@b.io") == {"status": "skipped", "reason": "no HUNTER_API_KEY"}


def test_http_500_and_timeout_never_leak_key():
    def boom(req):
        raise httpx.ConnectTimeout("timed out", request=req)

    for c in (client(lambda req: httpx.Response(500, text="no")), client(boom)):
        for r in (e.find_email("A B", "x.io", client=c), e.verify_email("a@b.io", client=c)):
            assert r["status"] == "error"
            assert KEY not in r["reason"]


def test_verify_email_ok():
    assert e.verify_email("ada@nozzle.io", client=reply()) == {
        "status": "valid", "score": 99, "webmail": False, "disposable": False, "source": "hunter"}


def test_verify_email_202_is_pending_without_retry():
    calls = []

    def h(req):
        calls.append(1)
        return httpx.Response(202, json={})

    assert e.verify_email("a@b.io", client=client(h)) == {"status": "pending"}
    assert len(calls) == 1


def test_company_domain_tavily_skips_directories():
    queries = []

    def search(q):
        queries.append(q)
        return [{"url": "https://www.linkedin.com/company/nozzle", "title": "li"},
                {"url": "https://github.com/nozzle", "title": "gh"},
                {"url": "https://www.nozzle.io/about", "title": "Nozzle"}]

    r = e.company_domain("Nozzle", search=search)
    assert r == {"status": "found", "domain": "nozzle.io", "url": "https://www.nozzle.io/about",
                 "title": "Nozzle", "source": "tavily"}
    assert queries == ['"Nozzle" official website']


def test_company_domain_only_directories_not_found():
    r = e.company_domain("Nozzle", search=lambda q: [{"url": "https://crunchbase.com/x", "title": "c"}])
    assert r == {"status": "not_found"}


def test_company_domain_already_a_domain_makes_no_search():
    def no_search(q):
        raise AssertionError("searched")

    for s in ("nozzle.io", "https://nozzle.io", "https://www.nozzle.io/"):
        r = e.company_domain(s, search=no_search)
        assert (r["status"], r["domain"], r["source"]) == ("found", "nozzle.io", "profile")


def test_company_domain_skips():
    assert e.company_domain("Nozzle") == {"status": "skipped", "reason": "no TAVILY_API_KEY"}
    assert e.company_domain("  ") == {"status": "skipped", "reason": "no company"}


def test_enrich_known_email():
    r = e.enrich("Ada", "", "ada@nozzle.io", client=reply())
    assert (r["email"], r["email_status"], r["domain"]) == ("ada@nozzle.io", "valid", "")
    assert r["steps"]


def test_enrich_full_path():
    search = lambda q: [{"url": "https://nozzle.io", "title": "Nozzle"}]  # noqa: E731
    r = e.enrich("Ada Lovelace", "Nozzle", search=search, client=reply())
    assert (r["email"], r["email_status"], r["domain"], r["position"]) == (
        "ada@nozzle.io", "valid", "nozzle.io", "CTO")
    assert r["steps"][-1] == "Hunter found an address, score 94, verified valid"


def test_enrich_verifies_when_finder_gave_no_status():
    finder = {"data": {**FINDER["data"], "verification": {"status": None}}}
    r = e.enrich("Ada Lovelace", "nozzle.io", client=reply(finder=finder))
    assert r["email_status"] == "valid"


def test_enrich_no_company():
    r = e.enrich("Ada Lovelace", "")
    assert r["email"] == "" and r["steps"] == ["no company on profile, skipped"]


def test_enrich_never_raises():
    def bad(q):
        raise RuntimeError(KEY)

    r = e.enrich("Ada", "Nozzle", search=bad)
    assert r["email"] == "" and KEY not in " ".join(r["steps"])
