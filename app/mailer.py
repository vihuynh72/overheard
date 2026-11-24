"""Real sending, redirected so no lead is ever emailed from this build.

Gmail first when the founder has connected it: the message goes to the founder's own address (or DEMO_INBOX).
Otherwise Resend to the demo inbox. The message is the one the agents wrote; only the recipient is swapped.
The lead's address is never used as a recipient. Never raises.
"""
import os

import httpx

from app import gmail

URL = "https://api.resend.com/emails"
SINK = "delivered@resend.dev"  # Resend's test address: accepted and logged, delivered to nobody


def send(lead: dict, subject: str, body: str, *, client: httpx.Client | None = None) -> dict:
    meant_for = lead.get("email") or lead.get("name") or lead.get("login") or "the lead"
    st = gmail.status()
    own = st["address"] or os.environ.get("DEMO_INBOX", "")
    if st["connected"] and own and own != lead.get("email"):
        out = gmail.send(own, subject, f"{body}\n\n--\nDemo redirect: written for {meant_for}, delivered to you only.", client=client)
        return {**out, "inbox": "founder" if own == st["address"] else "demo"}
    key = os.environ.get("RESEND_API_KEY")
    if not key:
        return {"status": "skipped", "reason": "no RESEND_API_KEY"}
    inbox = os.environ.get("DEMO_INBOX") or SINK
    if inbox == lead.get("email"):
        inbox = SINK  # the demo rule: never the lead
    try:
        r = (client or httpx).post(URL, timeout=15, headers={"Authorization": f"Bearer {key}"}, json={
            "from": os.environ.get("MAIL_FROM") or "Earshot <onboarding@resend.dev>",
            "to": [inbox],
            "subject": subject[:300],
            "text": f"{body}\n\n--\nDemo redirect: written for {meant_for}, delivered to the demo inbox only.",
        })
    except httpx.HTTPError as e:  # str(e) can carry request details
        return {"status": "error", "reason": type(e).__name__}
    if r.status_code >= 300:
        return {"status": "error", "reason": f"Resend HTTP {r.status_code}"}
    return {"status": "sent", "id": r.json().get("id", ""), "to": inbox}


def describe(result: dict) -> str:
    """One plain line for the audit log."""
    if result["status"] == "sent" and result.get("via") == "gmail":
        where = "the founder's own inbox" if result.get("inbox") == "founder" else "the demo inbox"
        return f"sent through Gmail to {where} ({result['to']}), not to the lead"
    if result["status"] == "sent":
        return f"sent through Resend to the demo inbox ({result['to']}), not to the lead"
    return f"not sent ({result['reason']}); decision recorded"
