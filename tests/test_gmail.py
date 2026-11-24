import base64
import email
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app import gmail

SECRET = "gsecret-xyz"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", SECRET)
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    gmail.disconnect()
    yield
    gmail.disconnect()


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def _google(profile_status=200, seen=None):
    def handler(req):
        (seen if seen is not None else []).append(req)
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-1", "expires_in": 3600})
        if req.url.path.endswith("/profile"):
            return httpx.Response(profile_status, json={"emailAddress": "me@example.org"})
        return httpx.Response(200, json={"id": "m1"})
    return handler


def _no_secrets(out):
    s = json.dumps(out)
    assert not any(x in s for x in ("at-1", "at-2", "rt-1", SECRET))


def test_auth_url_parameters():
    q = parse_qs(urlparse(gmail.auth_url("st")).query)
    assert q["scope"] == [gmail.SCOPE] and q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert q["response_type"] == ["code"] and q["state"] == ["st"] and q["client_id"] == ["cid"]
    assert q["redirect_uri"] == ["http://localhost:8765/api/gmail/callback"]
    assert SECRET not in gmail.auth_url("st")


def test_state_is_single_use():
    s = gmail.new_state()
    assert gmail.check_state(s) and not gmail.check_state(s) and not gmail.check_state("forged")


def test_exchange_success():
    out = gmail.exchange("code", client=_client(_google()))
    assert out == {"status": "connected", "address": "me@example.org"}
    assert gmail.status() == {"configured": True, "connected": True, "address": "me@example.org"}
    _no_secrets(out); _no_secrets(gmail.status())


def test_exchange_profile_403_leaves_address_empty():
    out = gmail.exchange("code", client=_client(_google(profile_status=403)))
    assert out["status"] == "connected" and out["address"] == "" and "403" in out["note"]
    assert gmail.status()["connected"]


def test_exchange_failure_never_raises_or_leaks():
    out = gmail.exchange("code", client=_client(lambda r: httpx.Response(400, json={"error": SECRET})))
    assert out == {"status": "error", "reason": "Google token HTTP 400"} and not gmail.status()["connected"]

    def boom(req):
        raise httpx.ConnectTimeout(SECRET)
    out = gmail.exchange("code", client=_client(boom))
    assert out == {"status": "error", "reason": "ConnectTimeout"}


def test_send_not_connected_is_skipped():
    assert gmail.send("a@b.c", "s", "b") == {"status": "skipped", "reason": "Gmail not connected"}


def test_send_builds_base64url_message_with_bearer():
    seen = []
    gmail.exchange("code", client=_client(_google(seen=seen)))
    out = gmail.send("me@example.org", "Hello", "Body text", client=_client(_google(seen=seen)))
    assert out == {"status": "sent", "id": "m1", "to": "me@example.org", "via": "gmail"}
    req = seen[-1]
    assert req.url.path.endswith("/messages/send") and req.headers["authorization"] == "Bearer at-1"
    raw = json.loads(req.content)["raw"]
    assert "+" not in raw and "/" not in raw
    msg = email.message_from_bytes(base64.urlsafe_b64decode(raw))
    assert msg["To"] == "me@example.org" and msg["Subject"] == "Hello" and "Body text" in msg.get_payload()
    _no_secrets(out)


def test_send_refreshes_near_expiry():
    gmail.exchange("code", client=_client(_google()))
    gmail._mem["expires"] = time.time() + 30  # inside the 60-second window
    seen = []

    def handler(req):
        seen.append(req)
        if req.url.host == "oauth2.googleapis.com":
            assert parse_qs(req.content.decode())["grant_type"] == ["refresh_token"]
            return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})
        return httpx.Response(200, json={"id": "m2"})
    out = gmail.send("me@example.org", "s", "b", client=_client(handler))
    assert out["status"] == "sent" and seen[-1].headers["authorization"] == "Bearer at-2"
    assert gmail._mem["refresh"] == "rt-1"  # a refresh response without a new refresh token keeps the old one


def test_send_errors_never_leak():
    gmail.exchange("code", client=_client(_google()))
    out = gmail.send("x@y.z", "s", "b", client=_client(lambda r: httpx.Response(401, json={"e": "at-1"})))
    assert out == {"status": "error", "reason": "Gmail HTTP 401"}
    gmail._mem["expires"] = 0
    out = gmail.send("x@y.z", "s", "b", client=_client(lambda r: httpx.Response(400, json={"e": SECRET})))
    assert out == {"status": "error", "reason": "Google refresh HTTP 400"}
    _no_secrets(out)
