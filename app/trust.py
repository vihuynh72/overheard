"""Which autonomy level the system has earned: earned from evidence, lost on a mistake."""

LEVELS = ["shadow", "supervised", "autopilot"]


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def agreement(decisions: list[dict], window: int = 20) -> dict:
    recent = decisions[-window:] if window > 0 else []
    # release pairs with approve, hold/drop pairs with reject
    agree = sum((d["agent"] == "release") == (d["human"] == "approve") for d in recent)
    n = len(recent)
    return {
        "n": n, "agree": agree, "rate": round(agree / n, 2) if n else 0.0,
        "false_release": sum(d["agent"] == "release" and d["human"] == "reject" for d in recent),
        "false_hold": sum(d["agent"] != "release" and d["human"] == "approve" for d in recent),
    }


def _relevant_pct(simulation: dict | None) -> float | None:
    """Case-weighted relevance over kinds with at least one usable (works or thin) case."""
    kinds = [k for k in (simulation or {}).get("by_kind", [])
             if k.get("cases") and (k.get("works", 0) + k.get("thin", 0)) > 0]
    cases = sum(k["cases"] for k in kinds)
    return sum(k["relevant_pct"] * k["cases"] for k in kinds) / cases if cases else None


def gates(decisions: list[dict], findings: list[dict], simulation: dict | None, lessons: list[dict],
          *, min_decisions: int = 8, min_rate: float = 0.9, min_relevant_pct: int = 60) -> list[dict]:
    a = agreement(decisions)
    enough = a["n"] >= min_decisions
    pct = _relevant_pct(simulation)
    came_back = sum(l.get("status") == "open" and bool(l.get("regressed")) for l in lessons)
    return [
        {"key": "self_check", "label": "Self-check is clean", "layer": "checked",
         "value": _count(len(findings), "problem", "problems"), "target": "0 problems",
         "passed": not findings},
        {"key": "agreement", "label": "Agent matches your decisions", "layer": "checked",
         "value": (f"{a['agree']} of {a['n']} matched your decision" if enough
                   else f"{a['n']} of {min_decisions} decisions needed"),
         "target": f"{round(min_rate * 100)}% of at least {min_decisions}",
         "passed": enough and a["rate"] >= min_rate},
        {"key": "false_release", "label": "No release you would have stopped", "layer": "enforced",
         "value": _count(a["false_release"], "message", "messages") + " you would have stopped",
         "target": "0", "passed": a["false_release"] == 0},
        {"key": "simulation", "label": "Simulation finds relevant leads", "layer": "checked",
         "value": ("not run yet" if simulation is None else
                   "no usable cases" if pct is None else f"{round(pct)}% relevant"),
         "target": f"{min_relevant_pct}% relevant",
         "passed": pct is not None and pct >= min_relevant_pct},
        {"key": "regressions", "label": "No fixed mistake came back", "layer": "enforced",
         "value": _count(came_back, "fixed mistake", "fixed mistakes") + " came back",
         "target": "0", "passed": came_back == 0},
    ]


def level(requested: str, gate_list: list[dict]) -> dict:
    if requested not in LEVELS:
        raise ValueError(f"Unknown level {requested!r}; use one of {', '.join(LEVELS)}")
    blocked = [g["label"] for g in gate_list if not g["passed"]] if requested == "autopilot" else []
    allowed = not blocked
    granted = requested if allowed else "supervised"
    note = (f"Running at {granted}." if allowed else
            f"Autopilot is not earned yet, so you still approve every message: {'; '.join(blocked)}.")
    return {"level": granted, "requested": requested, "allowed": allowed,
            "blocked_by": blocked, "note": note}


def demote(current: str, gate_list: list[dict]) -> dict | None:
    if current != "autopilot":
        return None
    failed = next((g for g in gate_list if g["layer"] == "enforced" and not g["passed"]), None)
    if failed is None:
        return None
    return {"level": "supervised",
            "reason": f"{failed['label']} failed ({failed['value']}), so autopilot is paused."}


def to_policy_mode(level_name: str) -> str:
    return "autopilot" if level_name == "autopilot" else "supervised"
