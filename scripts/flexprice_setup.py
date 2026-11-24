"""Create the Flexprice objects that make wallet drawdown real. Idempotent.

Usage: FLEXPRICE_API_KEY=... [FLEXPRICE_BASE_URL=...] [FLEXPRICE_CUSTOMER_ID=earshot-demo] python scripts/flexprice_setup.py
Each event gets a metered feature (with a COUNT meter), a usage price on one plan, and the
customer is subscribed to that plan. Only usage priced on a subscribed plan draws a wallet down.
"""
import os
import sys

import httpx

BASE = (os.environ.get("FLEXPRICE_BASE_URL") or "https://us.api.flexprice.io/v1").rstrip("/")
CUSTOMER = os.environ.get("FLEXPRICE_CUSTOMER_ID", "earshot-demo")  # external id or cust_ id
PLAN_KEY = "earshot-credits"
# event -> (feature name, USD per event); keep in step with COSTS in app/billing.py
EVENTS = {
    "lead.enriched": ("Leads Enriched", "2"),
    "outreach.sent": ("Outreach Sent", "1"),
    "graph.query": ("Graph Queries Evaluated", "0.1"),
}


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def call(c: httpx.Client, method: str, path: str, body: dict) -> dict:
    try:
        r = c.request(method, BASE + path, json=body)
    except httpx.HTTPError as e:
        die(f"{method} {path}: {e.__class__.__name__}")
    if r.status_code >= 400:
        die(f"{method} {path} returned {r.status_code}: {r.text[:300]}")
    return r.json()


def find_or_create(c, label, search_path, search_body, create_path, create_body):
    items = call(c, "POST", search_path, {**search_body, "limit": 50}).get("items") or []
    if items:
        print(f"{label}: {items[0]['id']} (already existed)")
        return items[0]
    obj = call(c, "POST", create_path, create_body)
    print(f"{label}: {obj['id']} (created)")
    return obj


def main() -> None:
    key = os.environ.get("FLEXPRICE_API_KEY")
    if not key:
        die("FLEXPRICE_API_KEY is not set")
    with httpx.Client(headers={"x-api-key": key}, timeout=20) as c:
        plan = find_or_create(c, "plan Overheard Credits", "/plans/search", {"lookup_key": PLAN_KEY},
                              "/plans", {"name": "Overheard Credits", "lookup_key": PLAN_KEY,
                                         "description": "Usage-priced plan drawn from a prepaid wallet"})
        for event, (name, amount) in EVENTS.items():
            feat = find_or_create(
                c, f"feature {name}", "/features/search", {"lookup_key": event},
                "/features", {"name": name, "lookup_key": event, "type": "metered",
                              "unit_singular": "event", "unit_plural": "events",
                              "meter": {"name": name, "event_name": event, "aggregation": {"type": "COUNT"},
                                        "reset_usage": "BILLING_PERIOD"}})
            find_or_create(
                c, f"price {name} {amount} USD", "/prices/search",
                {"entity_type": "PLAN", "entity_ids": [plan["id"]], "meter_ids": [feat["meter_id"]]},
                "/prices", {"entity_type": "PLAN", "entity_id": plan["id"], "type": "USAGE",
                            "meter_id": feat["meter_id"], "billing_model": "FLAT_FEE", "amount": amount,
                            "currency": "usd", "billing_period": "MONTHLY", "billing_period_count": 1,
                            "invoice_cadence": "ARREAR",
                            "price_unit_type": "FIAT", "display_name": name})
        cust_field = "customer_id" if CUSTOMER.startswith("cust_") else "external_customer_id"
        find_or_create(c, f"subscription {CUSTOMER} -> plan", "/subscriptions/search",
                       {cust_field: CUSTOMER, "plan_id": plan["id"], "subscription_status": ["active"]},
                       "/subscriptions", {cust_field: CUSTOMER, "plan_id": plan["id"], "currency": "usd",
                                          "billing_period": "MONTHLY", "billing_period_count": 1,
                                          "start_date": "2026-11-01T00:00:00Z"})


if __name__ == "__main__":
    main()
