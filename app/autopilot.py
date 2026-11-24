"""Earned autonomy: the state behind the Floor view, and the Sender.

Everything that decides is a pure function elsewhere (policy, trust, reviewer, checks).
This module holds the state they need, joins their answers, and acts on them.
"""
import datetime
import json
import os

from app import billing, checks, lessons, mailer, pipeline, policy, reviewer, store, trust

STATE_PATH = "data/autopilot.json"
SIM_PATH = "data/sim/latest.json"
AGENTS = ["planner", "scout", "qualifier", "enricher", "writer", "reviewer", "sender"]


def load() -> dict:
    st = json.load(open(STATE_PATH)) if os.path.exists(STATE_PATH) else {}
    return {"requested": "supervised", "policy": dict(policy.DEFAULT_POLICY), "rules": [], "decisions": [],
            "reviews": {}, "expansions": {}, **st}


def save(st: dict) -> None:
    os.makedirs("data", exist_ok=True)
    json.dump(st, open(STATE_PATH, "w"), indent=2)


def _simulation() -> dict | None:
    if not os.path.exists(SIM_PATH):
        return None
    d = json.load(open(SIM_PATH))
    return {"ran_at": d.get("ran_at"), **d["scorecard"]}


def findings(leads: list[dict], st: dict) -> list[dict]:
    """Rule checks plus the independent Reviewer's verdicts for leads still waiting on a decision."""
    out = checks.check_leads(leads, store.STAGES)
    pending = {l["login"] for l in leads if l["draft_status"] == "pending"}
    for login, r in st["reviews"].items():
        if login not in pending:
            continue
        out += [{"login": login, "rule": "unsupported_claim", "detail": s} for s in r.get("unsupported", [])]
        if r.get("verdict") == "unchecked":
            out.append({"login": login, "rule": "review_unavailable", "detail": r.get("reason", "")})
    return out


def trust_state(leads: list[dict], st: dict, found: list[dict]) -> dict:
    gate_list = trust.gates(st["decisions"], found, _simulation(), lessons.all())
    return {**trust.level(st["requested"], gate_list), "gates": gate_list, "agreement": trust.agreement(st["decisions"])}


def _decide(lead: dict, st: dict, found: list[dict], mode: str) -> dict:
    # The trust gates already require real human decisions, so they stand in for "first batch approved".
    pol = policy.validate({**st["policy"], "mode": mode, "approved_first_batch": True})
    sent = sum(1 for e in billing.ledger() if e["event"] == "outreach.sent" and e["ok"])
    return policy.decide(lead, pol, st["rules"], found, sent, datetime.date.today())


def record_human(lead: dict, human: str, st: dict, found: list[dict]) -> None:
    """Remember what the agent would have done at the moment the human decided: this is how trust is earned."""
    agent = _decide(lead, st, found, "autopilot")["action"]
    st["decisions"].append({"login": lead["login"], "agent": agent, "human": human,
                            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")})
    save(st)


def review_drafts(leads: list[dict]) -> None:
    """The Reviewer: a different model from the Writer checks each claim about the recipient against the evidence.

    Called with fresh leads, whose signals still hold the full issue text; the stored excerpt is too short to judge by.
    """
    st = load()
    todo = [{**l, "signals": [{**s, "excerpt": s["body"]} for s in l["signals"]]} for l in leads]
    st["reviews"] = {l["login"]: reviewer.review(l, reviewer.snap_judge) for l in todo}
    bad = sum(1 for r in st["reviews"].values() if r["verdict"] == "fail")
    unchecked = sum(1 for r in st["reviews"].values() if r["verdict"] == "unchecked")
    pipeline.say(f"Reviewer: checked {len(todo) - unchecked} drafts against the evidence with a second model; "
                 f"{bad} make a claim the evidence does not show" + (f"; {unchecked} could not be checked" if unchecked else ""))
    save(st)


def run_sender(st: dict | None = None) -> int:
    """Release what the policy releases, only on autopilot. Nothing is transmitted in this build."""
    st = st or load()
    leads = store.leads()
    found = findings(leads, st)
    ts = trust_state(leads, st, found)
    drop = trust.demote(st["requested"], ts["gates"])
    if drop:
        st["requested"] = drop["level"]
        save(st)
        pipeline.say(f"Sender: stepped down to supervised. {drop['reason']}")
        return 0
    if ts["level"] != "autopilot":
        return 0
    released = held = 0
    for lead in leads:
        if lead["draft_status"] != "pending":
            continue
        d = _decide(lead, st, found, "autopilot")
        gate = billing.gate("outreach.sent", lead["login"], lead["tier"])
        if d["action"] != "release" or not gate["allowed"]:
            held += 1
            continue
        store.upsert("Person", "login", dict(login=lead["login"], draft_status="approved", stage="Contacted", stage_actor="agent"))
        billing.record("outreach.sent", lead["login"], tier=lead["tier"])
        sent = mailer.describe(mailer.send(lead, lead["subject"], lead["body"]))
        store.log(lead["login"], "agent", "released", f"inside policy, passed review; {sent}")
        released += 1
    if released or held:
        pipeline.say(f"Sender: released {released} messages inside your policy; {held} held for you")
    return released


def after_run() -> None:
    if store.leads() and not pipeline.state["error"]:
        run_sender(load())


def set_level(level_name: str) -> dict:
    st = load()
    if level_name not in trust.LEVELS:
        raise ValueError("unknown level")
    st["requested"] = level_name
    save(st)
    run_sender(st)
    return trust_state(store.leads(), load(), findings(store.leads(), load()))


def floor(leads: list[dict]) -> dict:
    """Everything the Floor view draws."""
    st = load()
    found = findings(leads, st)
    ts = trust_state(leads, st, found)
    events = pipeline.state.get("events", [])
    seen = [e["to"] or e["from"] for e in events]
    agents = []
    for key in AGENTS:
        mine = [e for e in events if key in (e["from"], e["to"])]
        working = pipeline.state["running"] and seen and seen[-1] == key
        agents.append({"key": key, "name": key.capitalize(), "count": len(mine), "did": mine[-1]["text"] if mine else "",
                       "state": "blocked" if pipeline.state["error"] and seen and seen[-1] == key
                       else "working" if working else "done" if mine else "idle"})
    inbox = []
    for lead in leads:
        if lead["draft_status"] != "pending":
            continue
        d = _decide(lead, st, found, policy.MODES[1] if ts["level"] == "autopilot" else "supervised")
        if d["action"] != "release":
            inbox.append({"login": lead["login"], "name": lead["name"], "reasons": d["reasons"]})
    return {"agents": agents, "handoffs": [e for e in events if e["from"] != e["to"] and e["to"]],
            "trust": ts, "inbox": inbox, "lessons": lessons.all(), "simulation": _simulation(), "policy": st["policy"], "rules": st["rules"]}


def market_map(leads: list[dict]) -> dict:
    pains, people, companies, repos, edges = {}, [], {}, {}, []
    for lead in leads:
        people.append({"id": lead["login"], "name": lead["name"], "score": lead["score"], "tier": lead["tier"],
                       "company": lead["company"], "stage": lead["stage"]})
        if lead["company"]:
            companies.setdefault(lead["company"], {"id": lead["company"]})
            edges.append({"from": lead["login"], "to": lead["company"]})
        for s in lead["signals"]:
            pid = pains.setdefault(s["pain"], {"id": f"p{len(pains)}", "text": s["pain"]})["id"]
            repos.setdefault(s["repo"], {"id": s["repo"], "kind": "competitor"})
            for edge in ({"from": pid, "to": lead["login"]}, {"from": lead["login"], "to": s["repo"]}):
                if edge not in edges:
                    edges.append(edge)
    return {"pains": list(pains.values()), "people": people, "companies": list(companies.values()),
            "repos": list(repos.values()), "edges": edges}
