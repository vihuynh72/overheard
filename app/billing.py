"""Credit gate and usage metering. Local wallet without a key, Flexprice with one.

Flexprice never blocks anything itself: gate() is where enrichment stops. In flexprice mode the
events are priced on a subscribed plan (scripts/flexprice_setup.py), so Flexprice's own real-time
wallet balance falls as we record usage. It lags by up to ~15s (measured 0.2-15s), so each event's
cost is held in _pending until the balance has dropped by that much or PENDING_TTL passes.
"""
import os
import time
import uuid
from datetime import datetime, timezone

import httpx

COSTS = {"lead.enriched": 2.0, "outreach.sent": 1.0, "graph.query": 0.1}
LOW_WATER = 15.0  # below this, weak-fit (tier C) work is paused
PENDING_TTL = 30.0  # seconds; about twice the slowest measured wallet drawdown
DEFAULT_BASE = "https://us.api.flexprice.io/v1"

_local: float | None = None  # local wallet; None until first read so LOCAL_CREDITS applies
_last: float | None = None   # last balance read from Flexprice
_pending: list[list[float]] = []  # [cost, sent_at] per event the wallet may not show yet
_ledger: list[dict] = []


def reset() -> None:
    global _local, _last
    _local, _last = None, None
    _pending.clear()
    _ledger.clear()


def mode() -> str:
    keys = ("FLEXPRICE_API_KEY", "FLEXPRICE_CUSTOMER_ID", "FLEXPRICE_WALLET_ID")
    return "flexprice" if all(os.environ.get(k) for k in keys) else "local"


def _now() -> float:
    return time.monotonic()


def _pending_total() -> float:
    return sum(c for c, _ in _pending)


def _call(method: str, path: str, client: httpx.Client | None, **kw) -> httpx.Response:
    base = os.environ.get("FLEXPRICE_BASE_URL") or DEFAULT_BASE
    headers = {"x-api-key": os.environ["FLEXPRICE_API_KEY"]}
    c = client or httpx.Client(timeout=5)
    try:
        r = c.request(method, base.rstrip("/") + path, headers=headers, **kw)
        r.raise_for_status()
        return r
    finally:
        if client is None:
            c.close()


def _local_credits() -> float:
    global _local
    if _local is None:
        try:
            _local = float(os.environ.get("LOCAL_CREDITS", 60))
        except ValueError:
            _local = 60.0
    return _local


def balance(*, client: httpx.Client | None = None) -> dict:
    global _last
    if mode() == "local":
        return {"credits": _local_credits(), "mode": "local", "stale": False}
    try:
        r = _call("GET", f"/wallets/{os.environ['FLEXPRICE_WALLET_ID']}/balance/real-time", client)
        fresh = float(r.json()["real_time_balance"])
    except Exception:
        # No read yet means no known figure: report 0 so the gate fails closed.
        return {"credits": (_last or 0.0) - _pending_total(), "mode": "flexprice", "stale": True}
    drop = (_last - fresh) if _last is not None else 0.0  # Flexprice has now counted this much
    _last = fresh
    _pending[:] = [p for p in _pending if _now() - p[1] < PENDING_TTL]
    while drop > 1e-9 and _pending:  # oldest first; a partial drop shrinks the oldest entry
        take = min(drop, _pending[0][0])
        drop -= take
        _pending[0][0] -= take
        if _pending[0][0] <= 1e-9:
            _pending.pop(0)
    return {"credits": fresh - _pending_total(), "mode": "flexprice", "stale": False}


def gate(event: str, lead: str = "", tier: str = "", *, client: httpx.Client | None = None) -> dict:
    cost = COSTS.get(event)
    if cost is None:
        return {"allowed": False, "reason": "Unknown event", "cost": 0.0, "credits": balance(client=client)["credits"]}
    credits = balance(client=client)["credits"]
    reason = ""
    if credits < cost:
        reason = "Out of credits"
    elif tier == "C" and credits < LOW_WATER:
        reason = "Low balance: weak-fit leads are paused"
    return {"allowed": not reason, "reason": reason, "cost": cost, "credits": credits}


def record(event: str, lead: str = "", *, client: httpx.Client | None = None, **props) -> dict:
    global _local
    cost = COSTS.get(event, 0.0)
    m = mode()
    ok = event in COSTS
    if ok and m == "local":
        _local = _local_credits() - cost
    elif ok:
        body = {
            "event_name": event,
            "external_customer_id": os.environ["FLEXPRICE_CUSTOMER_ID"],
            "event_id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "earshot",
            "properties": {"lead": lead, "credits": str(cost), **{k: str(v) for k, v in props.items()}},
        }
        try:
            _call("POST", "/events", client, json=body)
            _pending.append([cost, _now()])
        except Exception:
            ok = False
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, "lead": lead,
             "credits": cost, "mode": m, "ok": ok}
    _ledger.append(entry)
    return entry


def ledger() -> list[dict]:
    return _ledger[::-1]


def cost_by_lead() -> dict[str, float]:
    out: dict[str, float] = {}
    for e in _ledger:
        if e["ok"]:
            out[e["lead"]] = out.get(e["lead"], 0.0) + e["credits"]
    return out


def top_up(credits: float) -> dict:
    global _local
    if mode() != "local":
        return {"ok": False, "reason": "Top up in the Flexprice dashboard"}
    _local = _local_credits() + credits
    return {"ok": True, "credits": _local}
