import re

from app import scoring

_PLACEHOLDER = re.compile(r"\[[^\]]+\]|\{\{[^}]*\}\}")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SUFFIX = re.compile(r"(,\s*inc\.?|\s+inc\.?|\s+llc|\s+ltd)$")
_UNDECIDED_OK = ("Matched", "Closed/Lost")


def check_leads(leads: list[dict], stages: list[str]) -> list[dict]:
    """Findings for a run; an empty list means every lead passed every rule."""
    out = []
    for lead in leads:
        login = lead.get("login", "")

        def flag(rule, detail):
            out.append({"login": login, "rule": rule, "detail": detail})

        signals = lead.get("signals") or []
        if not signals or any(not str(s.get("url", "")).startswith("https://") for s in signals):
            flag("no_evidence", "no signals, or a signal without an https url")
        sc = lead.get("score")
        if not isinstance(sc, int) or isinstance(sc, bool) or not 0 <= sc <= 100:
            flag("score_range", f"score {sc!r} is not an int in 0..100")
        elif lead.get("tier") != scoring.tier(sc):
            flag("tier_mismatch", f"tier {lead.get('tier')!r} but score {sc} is {scoring.tier(sc)}")
        if not lead.get("reason"):
            flag("no_reason", "reason is empty")
        subject, body = lead.get("subject") or "", lead.get("body") or ""
        if not subject or not body:
            flag("empty_draft", "subject or body is empty")
        if len(subject.split()) > 12:
            flag("long_subject", f"{len(subject.split())} words, max 12")
        if len(body.split()) > 130:
            flag("long_body", f"{len(body.split())} words, max 130")
        if _PLACEHOLDER.search(subject) or _PLACEHOLDER.search(body):
            flag("placeholder", "draft contains a bracketed placeholder")
        stage = lead.get("stage")
        if stage not in stages:
            flag("bad_stage", f"stage {stage!r} is not a known stage")
        if stage not in _UNDECIDED_OK and lead.get("draft_status") == "pending":
            flag("unreviewed_contact", f"stage {stage!r} reached with no human decision on the draft")
        email = lead.get("email")
        if email and not _EMAIL.match(email):
            flag("bad_email", f"{email!r} is not a plausible address")
        weak = [s.get("id", "?") for s in signals if s.get("match", 0) < 0.3]
        if weak:
            flag("weak_match", f"match below 0.3 on {', '.join(weak)}")
    return out


def _norm(name: str) -> str:
    return _SUFFIX.sub("", name.strip().lstrip("@").strip().lower()).strip()


def rediscovery(ranked: list[str], known: list[str], k: int) -> dict:
    top = {_norm(n) for n in ranked[:k]}
    found = [n for n in known if _norm(n) in top]
    missed = [n for n in known if _norm(n) not in top]
    recall = round(len(found) / len(known), 2) if known else 0.0
    return {"k": k, "known": len(known), "found": found, "missed": missed, "recall": recall}
