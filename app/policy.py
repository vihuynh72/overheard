import collections
import datetime
import uuid

DEFAULT_POLICY = {
    "mode": "supervised", "min_score": 50, "require_verified_email": True,
    "require_production_use": False, "max_evidence_age_days": 730, "daily_send_limit": 20,
    "never_say": [], "approved_first_batch": False,
}
MODES = ("supervised", "autopilot")
FIELDS = ("company", "role", "location", "login", "name", "tier", "repo", "text")
OPS = ("equals", "contains", "not_contains")
ACTIONS = ("hold", "drop")


def validate(policy: dict) -> dict:
    p = {**DEFAULT_POLICY, **{k: v for k, v in policy.items() if k in DEFAULT_POLICY}}
    if p["mode"] not in MODES:
        raise ValueError(f"Unknown mode {p['mode']!r}; use 'supervised' or 'autopilot'")
    for key in ("min_score", "max_evidence_age_days", "daily_send_limit"):
        if not isinstance(p[key], int) or isinstance(p[key], bool):
            raise ValueError(f"{key} must be a whole number")
    if not 0 <= p["min_score"] <= 100:
        raise ValueError("min_score must be between 0 and 100")
    if p["max_evidence_age_days"] < 0 or p["daily_send_limit"] < 0:
        raise ValueError("Limits and ages cannot be negative")
    phrases = p["never_say"]
    if not isinstance(phrases, list) or any(not isinstance(s, str) or not s.strip() for s in phrases):
        raise ValueError("never_say must be a list of non-empty strings")
    p["never_say"] = [s.strip().lower()[:80] for s in phrases[:50]]
    for key in ("require_verified_email", "require_production_use", "approved_first_batch"):
        p[key] = bool(p[key])
    return p


def make_rule(field: str, op: str, value: str, action: str, reason: str, source: str = "founder") -> dict:
    if field not in FIELDS:
        raise ValueError(f"Unknown field {field!r}; use one of {', '.join(FIELDS)}")
    if op not in OPS:
        raise ValueError(f"Unknown operator {op!r}; use one of {', '.join(OPS)}")
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r}; use 'hold' or 'drop'")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A rule needs a value to compare against")
    return {"id": uuid.uuid4().hex[:8], "field": field, "op": op, "value": value.strip(),
            "action": action, "reason": reason, "source": source}


def _values(field: str, lead: dict) -> list[str]:
    signals = lead.get("signals") or []
    if field == "repo":
        return [str(s.get("repo") or "") for s in signals]
    if field == "text":
        parts = [lead.get("reason")] + [p for s in signals for p in (s.get("title"), s.get("excerpt"))]
        return ["\n".join(str(p) for p in parts if p)]
    return [str(lead.get(field) or "")]


def rule_matches(rule: dict, lead: dict) -> bool:
    if rule.get("field") not in FIELDS:
        return False
    want = rule["value"].strip().lower()
    have = [v.strip().lower() for v in _values(rule["field"], lead)]
    if rule["op"] == "equals":
        return want in have
    if rule["op"] == "contains":
        return any(want in v for v in have)
    return not any(want in v for v in have)


def _too_old(newest: str, limit: int, today: datetime.date) -> bool:
    try:
        return (today - datetime.date.fromisoformat(newest)).days > limit
    except (ValueError, TypeError):
        return True


def _no_named_author(lead: dict) -> bool:
    # The store keeps no kind or author on signals, but an authorless web voice is keyed "web:<hex>"
    # (scout_web.as_people) and a GitHub login cannot hold ":". Fresh signals still carry both fields.
    if str(lead.get("login") or "").strip().lower().startswith("web:"):
        return True
    return any(s.get("kind") == "web" and not str(s.get("author") or "").strip() for s in lead.get("signals") or [])


def decide(lead: dict, policy: dict, rules: list[dict], findings: list[dict],
           sent_today: int, today: datetime.date) -> dict:
    hits = [r for r in rules if rule_matches(r, lead)]
    drop = next((r for r in hits if r["action"] == "drop"), None)
    if drop:
        return {"action": "drop", "reasons": [drop["reason"]]}
    why = [r["reason"] for r in hits if r["action"] == "hold"]
    why += [f"Failed self-check: {f['rule']}" for f in findings if f.get("login") == lead.get("login")]
    if lead.get("score", 0) < policy["min_score"]:
        why.append(f"Score {lead.get('score', 0)} is below your minimum of {policy['min_score']}")
    if policy["require_verified_email"] and lead.get("email_status") != "valid":
        why.append("No verified email address")
    if _no_named_author(lead):
        why.append("No named author, so there is nobody to write to")
    if policy["require_production_use"] and not lead.get("production"):
        why.append("No sign of production use")
    if not lead.get("newest"):
        why.append("Evidence has no date, so its age is unknown")  # still held: unknown is not the same as recent
    elif _too_old(lead.get("newest"), policy["max_evidence_age_days"], today):
        why.append(f"Evidence is older than {policy['max_evidence_age_days']} days")
    draft = f"{lead.get('subject') or ''}\n{lead.get('body') or ''}".lower()
    why += [f"Draft contains a phrase you banned: {p}" for p in policy["never_say"] if p.lower() in draft]
    if sent_today >= policy["daily_send_limit"]:
        why.append(f"Daily send limit of {policy['daily_send_limit']} reached")
    if policy["mode"] == "supervised":
        why.append("You review every message in supervised mode")
    elif not policy["approved_first_batch"]:
        why.append("Waiting for you to approve the first batch")
    return {"action": "hold" if why else "release", "reasons": why}


def summarize(decisions: dict[str, dict]) -> dict:
    out = {a: sum(d["action"] == a for d in decisions.values()) for a in ("release", "hold", "drop")}
    counts = collections.Counter(r for d in decisions.values() if d["action"] != "release" for r in d["reasons"])
    out["top_reasons"] = [[text, n] for text, n in counts.most_common(5)]
    return out


def suggest_rule(lead: dict, founder_reason: str) -> dict | None:
    said = founder_reason.lower()
    why = f'You said: "{founder_reason.strip()}"'
    for trigger, word in (("agency", "agency"), ("consultan", "consultan"), ("hobby", "hobby"),
                          ("student", "student"), ("personal project", "personal project")):
        if trigger in said:
            return make_rule("text", "contains", word, "hold", why, source="suggested")
    company = (lead.get("company") or "").strip()
    if company and ("competitor" in said or "works at" in said):
        return make_rule("company", "equals", company, "drop", why, source="suggested")
    return None
