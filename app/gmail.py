"""Send as the founder through their own Gmail, over OAuth.

Tokens live only in this module's memory: never written to disk, never logged, gone on restart.
Nothing here raises, and no returned string carries a token or the client secret.
"""
import base64
import os
import secrets
import time
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
PROFILE = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
SEND = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
SCOPE = "https://www.googleapis.com/auth/gmail.send"

_mem: dict = {}  # access, refresh, expires, address
_states: set[str] = set()


def configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))


def _redirect() -> str:
    return os.environ.get("GOOGLE_REDIRECT_URI") or "http://localhost:8765/api/gmail/callback"


def new_state() -> str:
    s = secrets.token_urlsafe(24)
    _states.add(s)
    return s


def check_state(state: str) -> bool:
    if state in _states:
        _states.discard(state)  # single use
        return True
    return False


def auth_url(state: str) -> str:
    return AUTH + "?" + urlencode({
        "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""), "redirect_uri": _redirect(), "response_type": "code",
        "scope": SCOPE, "access_type": "offline", "prompt": "consent", "state": state})


def _store(tok: dict) -> None:
    _mem["access"] = tok["access_token"]
    _mem["expires"] = time.time() + int(tok.get("expires_in", 3600))
    if tok.get("refresh_token"):
        _mem["refresh"] = tok["refresh_token"]


def exchange(code: str, *, client: httpx.Client | None = None) -> dict:
    c = client or httpx
    try:
        r = c.post(TOKEN, timeout=15, data={
            "code": code, "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            "redirect_uri": _redirect(), "grant_type": "authorization_code"})
        if r.status_code >= 300:
            return {"status": "error", "reason": f"Google token HTTP {r.status_code}"}
        _store(r.json())
        p = c.get(PROFILE, timeout=15, headers={"Authorization": f"Bearer {_mem['access']}"})
    except (httpx.HTTPError, KeyError, ValueError) as e:  # str(e) can carry request details
        return {"status": "error", "reason": type(e).__name__}
    # gmail.send alone may not read the profile (403): connected, address unknown
    _mem["address"] = p.json().get("emailAddress", "") if p.status_code < 300 else ""
    out = {"status": "connected", "address": _mem["address"]}
    if not _mem["address"]:
        out["note"] = f"address unknown (profile HTTP {p.status_code})"
    return out


def status() -> dict:
    return {"configured": configured(), "connected": bool(_mem.get("access")), "address": _mem.get("address", "")}


def _fresh(c) -> str | None:
    """A usable access token, refreshing it when it is within 60 seconds of expiry. Returns an error reason or None."""
    if time.time() < _mem.get("expires", 0) - 60:
        return None
    if not _mem.get("refresh"):
        return "token expired and no refresh token"
    r = c.post(TOKEN, timeout=15, data={
        "refresh_token": _mem["refresh"], "client_id": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", ""), "grant_type": "refresh_token"})
    if r.status_code >= 300:
        return f"Google refresh HTTP {r.status_code}"
    _store(r.json())
    return None


def send(to: str, subject: str, body: str, *, client: httpx.Client | None = None) -> dict:
    if not _mem.get("access"):
        return {"status": "skipped", "reason": "Gmail not connected"}
    c = client or httpx
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject[:300]
    if _mem.get("address"):
        msg["From"] = _mem["address"]
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        if err := _fresh(c):
            return {"status": "error", "reason": err}
        r = c.post(SEND, timeout=15, headers={"Authorization": f"Bearer {_mem['access']}"}, json={"raw": raw})
        if r.status_code >= 300:
            return {"status": "error", "reason": f"Gmail HTTP {r.status_code}"}
        return {"status": "sent", "id": r.json().get("id", ""), "to": to, "via": "gmail"}
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return {"status": "error", "reason": type(e).__name__}


def disconnect() -> None:
    _mem.clear()
