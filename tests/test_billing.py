import json

import httpx
import pytest

from app import billing

KEY = "not-a-real-key"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("FLEXPRICE_API_KEY", "FLEXPRICE_BASE_URL", "FLEXPRICE_CUSTOMER_ID", "FLEXPRICE_WALLET_ID", "LOCAL_CREDITS"):
        monkeypatch.delenv(k, raising=False)
    billing.reset()
    yield
    billing.reset()


def flex_env(monkeypatch):
    monkeypatch.setenv("FLEXPRICE_API_KEY", KEY)
    monkeypatch.setenv("FLEXPRICE_CUSTOMER_ID", "cust_1")
    monkeypatch.setenv("FLEXPRICE_WALLET_ID", "wal_1")


def fake_flexprice(state):
    """Mock API: state['balance'] is what the wallet endpoint reports; state['fail'] breaks a path."""
    def handler(req: httpx.Request) -> httpx.Response:
        state.setdefault("seen", []).append(req)
        if state.get("fail", "\0") in req.url.path:
            return httpx.Response(500, text="boom")
        if req.method == "POST":
            return httpx.Response(202, json={"message": "accepted"})
        return httpx.Response(200, json={"real_time_balance": str(state["balance"])})
    return httpx.Client(transport=httpx.MockTransport(handler))


# local mode

def test_local_mode_defaults_to_60():
    assert billing.mode() == "local"
    assert billing.balance() == {"credits": 60.0, "mode": "local", "stale": False}


def test_local_gate_allows_then_denies_at_zero(monkeypatch):
    monkeypatch.setenv("LOCAL_CREDITS", "2")
    assert billing.gate("lead.enriched", "a")["allowed"]
    billing.record("lead.enriched", "a")
    g = billing.gate("lead.enriched", "b")
    assert (g["allowed"], g["reason"], g["credits"]) == (False, "Out of credits", 0.0)


def test_unknown_event_is_denied():
    assert billing.gate("nope")["reason"] == "Unknown event"
    assert billing.record("nope")["ok"] is False


def test_tier_c_pauses_below_low_water_but_tier_a_continues(monkeypatch):
    monkeypatch.setenv("LOCAL_CREDITS", "14")
    c = billing.gate("lead.enriched", "w", tier="C")
    assert (c["allowed"], c["reason"]) == (False, "Low balance: weak-fit leads are paused")
    assert billing.gate("lead.enriched", "s", tier="A")["allowed"]
    monkeypatch.setenv("LOCAL_CREDITS", "20")
    billing.reset()
    assert billing.gate("lead.enriched", "w", tier="C")["allowed"]


def test_record_decrements_and_top_up_resumes(monkeypatch):
    monkeypatch.setenv("LOCAL_CREDITS", "2")
    billing.record("lead.enriched", "a")
    assert billing.balance()["credits"] == 0.0
    assert not billing.gate("lead.enriched", "b")["allowed"]
    assert billing.top_up(10)["ok"]
    assert billing.balance()["credits"] == 10.0
    assert billing.gate("lead.enriched", "b")["allowed"]


def test_ledger_newest_first_and_cost_by_lead():
    billing.record("lead.enriched", "a")
    billing.record("outreach.sent", "a")
    billing.record("lead.enriched", "b")
    assert [e["lead"] for e in billing.ledger()] == ["b", "a", "a"]
    assert billing.ledger()[0]["mode"] == "local" and billing.ledger()[0]["ok"] is True
    assert billing.cost_by_lead() == {"a": 3.0, "b": 2.0}


# flexprice mode

def test_mode_needs_all_three(monkeypatch):
    monkeypatch.setenv("FLEXPRICE_API_KEY", KEY)
    assert billing.mode() == "local"
    flex_env(monkeypatch)
    assert billing.mode() == "flexprice"


def test_post_carries_key_and_string_properties(monkeypatch):
    flex_env(monkeypatch)
    state = {"balance": 50}
    entry = billing.record("lead.enriched", "acme", client=fake_flexprice(state), score=7, tier="A")
    req = state["seen"][0]
    body = json.loads(req.content)
    assert entry["ok"] and entry["mode"] == "flexprice"
    assert req.method == "POST" and req.url.path.endswith("/events")
    assert str(req.url).startswith("https://us.api.flexprice.io/v1/events")
    assert req.headers["x-api-key"] == KEY
    assert body["event_name"] == "lead.enriched" and body["external_customer_id"] == "cust_1"
    assert body["properties"] == {"lead": "acme", "credits": "2.0", "score": "7", "tier": "A"}
    assert all(isinstance(v, str) for v in body["properties"].values())
    assert body["event_id"] and body["timestamp"]


def test_base_url_override(monkeypatch):
    flex_env(monkeypatch)
    monkeypatch.setenv("FLEXPRICE_BASE_URL", "https://eu.api.flexprice.io/v1/")
    state = {"balance": 5}
    billing.balance(client=fake_flexprice(state))
    assert str(state["seen"][0].url) == "https://eu.api.flexprice.io/v1/wallets/wal_1/balance/real-time"
    assert state["seen"][0].headers["x-api-key"] == KEY


def test_pending_makes_a_burst_see_reduced_balance(monkeypatch):
    flex_env(monkeypatch)
    state = {"balance": 3}  # API keeps reporting the old figure: ingestion is async
    c = fake_flexprice(state)
    assert billing.gate("lead.enriched", "a", client=c)["allowed"]
    billing.record("lead.enriched", "a", client=c)
    g = billing.gate("lead.enriched", "b", client=c)
    assert g["credits"] == 1.0 and not g["allowed"] and g["reason"] == "Out of credits"


def test_pending_shrinks_when_api_balance_drops(monkeypatch):
    flex_env(monkeypatch)
    state = {"balance": 50}
    c = fake_flexprice(state)
    billing.balance(client=c)
    billing.record("lead.enriched", "a", client=c)  # pending 2
    assert billing.balance(client=c)["credits"] == 48.0
    state["balance"] = 48  # Flexprice caught up: do not subtract the 2 twice
    assert billing.balance(client=c)["credits"] == 48.0
    state["balance"] = 45  # a later drop beyond pending leaves pending at 0, not negative
    assert billing.balance(client=c)["credits"] == 45.0


def test_pending_expires_after_ttl(monkeypatch):
    flex_env(monkeypatch)
    now = [100.0]
    monkeypatch.setattr(billing, "_now", lambda: now[0])
    state = {"balance": 50}
    c = fake_flexprice(state)
    billing.balance(client=c)
    billing.record("lead.enriched", "a", client=c)  # wallet never moves (e.g. event dropped)
    now[0] += billing.PENDING_TTL - 1
    assert billing.balance(client=c)["credits"] == 48.0
    now[0] += 2
    assert billing.balance(client=c)["credits"] == 50.0  # released: no permanent double count


def test_partial_drop_releases_oldest_event_first(monkeypatch):
    flex_env(monkeypatch)
    state = {"balance": 50}
    c = fake_flexprice(state)
    billing.balance(client=c)
    billing.record("lead.enriched", "a", client=c)  # 2
    billing.record("outreach.sent", "a", client=c)  # 1
    state["balance"] = 48  # only the lead event has landed
    assert billing.balance(client=c)["credits"] == 47.0
    state["balance"] = 47
    assert billing.balance(client=c)["credits"] == 47.0


def test_failing_balance_returns_stale_figure(monkeypatch):
    flex_env(monkeypatch)
    state = {"balance": 40}
    c = fake_flexprice(state)
    assert billing.balance(client=c)["credits"] == 40.0
    state["fail"] = "balance"
    b = billing.balance(client=c)
    assert (b["credits"], b["stale"]) == (40.0, True)


def test_failing_post_is_not_ok_and_costs_nothing(monkeypatch):
    flex_env(monkeypatch)
    state = {"balance": 40, "fail": "/events"}
    c = fake_flexprice(state)
    entry = billing.record("lead.enriched", "a", client=c)
    assert entry["ok"] is False
    assert billing.balance(client=c)["credits"] == 40.0
    assert billing.cost_by_lead() == {}


def test_top_up_refused_in_flexprice_mode(monkeypatch):
    flex_env(monkeypatch)
    assert billing.top_up(10) == {"ok": False, "reason": "Top up in the Flexprice dashboard"}


def test_no_returned_value_contains_the_key(monkeypatch):
    flex_env(monkeypatch)
    state = {"balance": 5}
    c = fake_flexprice(state)
    out = [billing.balance(client=c), billing.gate("lead.enriched", "a", client=c),
           billing.record("lead.enriched", "a", client=c), billing.ledger(), billing.cost_by_lead()]
    state["fail"] = "balance"
    out += [billing.balance(client=c), billing.gate("lead.enriched", "a", client=c)]
    state["fail"] = "/events"
    out.append(billing.record("lead.enriched", "a", client=c))
    assert KEY not in json.dumps(out)
