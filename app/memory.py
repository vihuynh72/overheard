"""What was already decided about a person, kept across runs.

A run wipes the graph, so without this a second scan of the same product shows the founder people they
already wrote to or rejected. One JSON line per decision: product, login, decision, date and the evidence
the person had at the time. A person comes back only when they have said something new.
"""
import datetime
import json
import os

DEFAULT_PATH = "data/memory.jsonl"
RESEND_AFTER_DAYS = 30  # a sent message keeps someone hidden this long even when they post again


def _key(product: str) -> str:
    return (product or "").strip().lower()


def record(product: str, lead: dict, decision: str, *, path=DEFAULT_PATH, today=None) -> None:
    """`decision` is "sent" or "rejected". `lead` carries its signals, whose ids are the evidence seen so far."""
    row = {"product": _key(product), "login": lead["login"], "decision": decision,
           "on": (today or datetime.date.today()).isoformat(),
           "seen": sorted(s["id"] for s in lead.get("signals") or [])}
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


def _latest(product: str, path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("product") == _key(product) and row.get("login"):
            prev = out.get(row["login"])
            row["seen"] = sorted(set(row.get("seen") or []) | set(prev["seen"] if prev else []))
            out[row["login"]] = row  # later lines win; evidence seen accumulates
    return out


def split(product: str, leads: list[dict], *, path=DEFAULT_PATH, today=None) -> tuple[list[dict], dict[str, int]]:
    """(leads to show, how many were held back by decision). A person returns only with evidence not seen before,
    and one already written to also waits RESEND_AFTER_DAYS."""
    known, today = _latest(product, path), today or datetime.date.today()
    keep, skipped = [], {"sent": 0, "rejected": 0}
    for lead in leads:
        row = known.get(lead["login"])
        if not row:
            keep.append(lead)
            continue
        fresh = any(s["id"] not in row["seen"] for s in lead.get("signals") or [])
        waited = (today - datetime.date.fromisoformat(row["on"])).days >= RESEND_AFTER_DAYS
        if fresh and (row["decision"] == "rejected" or waited):
            keep.append(lead)
        else:
            skipped[row["decision"] if row["decision"] in skipped else "rejected"] += 1
    return keep, skipped
