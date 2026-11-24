import json

import httpx

from app import mailer

LEAD = {"login": "x", "name": "Ada", "email": "ada@example.com"}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_no_key_is_skipped(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    assert mailer.send(LEAD, "s", "b") == {"status": "skipped", "reason": "no RESEND_API_KEY"}


def test_sends_to_the_demo_inbox_never_the_lead(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_secret")
    monkeypatch.delenv("DEMO_INBOX", raising=False)
    seen = {}

    def handler(req):
        seen.update(json.loads(req.content), auth=req.headers["authorization"])
        return httpx.Response(200, json={"id": "em_1"})

    out = mailer.send(LEAD, "Subject", "Body", client=_client(handler))
    assert out == {"status": "sent", "id": "em_1", "to": mailer.SINK}
    assert seen["to"] == [mailer.SINK] and "ada@example.com" not in seen["to"]
    assert seen["auth"] == "Bearer re_secret" and "written for ada@example.com" in seen["text"]
    assert "demo inbox" in mailer.describe(out)


def test_demo_inbox_override(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_secret")
    monkeypatch.setenv("DEMO_INBOX", "me@example.org")
    out = mailer.send(LEAD, "s", "b", client=_client(lambda r: httpx.Response(200, json={"id": "e"})))
    assert out["to"] == "me@example.org"


def test_errors_never_raise_or_leak_the_key(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_secret")
    out = mailer.send(LEAD, "s", "b", client=_client(lambda r: httpx.Response(403, json={"message": "re_secret"})))
    assert out == {"status": "error", "reason": "Resend HTTP 403"}

    def boom(req):
        raise httpx.ConnectTimeout("re_secret")

    out = mailer.send(LEAD, "s", "b", client=_client(boom))
    assert out["status"] == "error" and "re_secret" not in json.dumps(out)
    assert "not sent" in mailer.describe(out)
