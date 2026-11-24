"""Independent reviewer: a different model checks every claim a draft makes about the recipient.

`judge(state, questions) -> {id: P(yes)}` is injected. Nothing here raises out of review()
or findings(), and the SubQ key never appears in returned text.
"""
import os
import re

import httpx

SUBQ_URL = "https://api.subq.ai/v1/systemone"
MODEL = "subq-snap-1.2"
MAX_QUESTIONS = 128
_BREAK = re.compile(r"(?<=[.?!])\s+")
_ABBREV = re.compile(r"\b(e\.g|i\.e|vs|mr|mrs|ms|dr)\.$", re.I)
_YOU = re.compile(r"\byou(?:r|'re|'ve)?\b", re.I)
_GREETING = re.compile(r"^(hi|hello|hey|dear)\b[^,]*,\s*", re.I)
_CRITERIA = {"true": "Every fact in the sentence appears in the evidence.",
             "false": "The sentence states or implies something the evidence does not show."}


def split(body: str) -> list[str]:
    out: list[str] = []
    for line in (body or "").splitlines():
        merge = False
        for piece in _BREAK.split(line.strip()):
            if merge and out:
                out[-1] += " " + piece
            else:
                out.append(piece)
            merge = bool(_ABBREV.search(piece))
    return [s.strip() for s in out if s.strip()]


def _word(term: str, text: str) -> bool:
    return bool(term.strip()) and bool(re.search(rf"(?<!\w){re.escape(term.strip())}(?!\w)", text, re.I))


def about_recipient(sentence: str, lead: dict) -> bool:
    s = _GREETING.sub("", sentence.strip(), count=1).strip()
    if not s or s.endswith("?"):
        return False
    name = (lead.get("name") or "").strip()
    first = name.split()[0] if name else ""  # fail closed: "Derek" alone counts as the recipient
    return bool(_YOU.search(s)) or any(_word(t, s) for t in (name, first, lead.get("company") or ""))


def evidence(lead: dict) -> str:
    lines = [f"{k}: {lead[k]}" for k in ("name", "company", "role", "location") if lead.get(k)]
    for sig in lead.get("signals") or []:
        lines.append(f"issue in {sig.get('repo', '')} on {sig.get('created', '')}: "
                     f"{sig.get('title', '')}. {sig.get('excerpt', '')}")
    return "\n".join(lines)


def review(lead: dict, judge) -> dict:
    out = {"login": lead.get("login", ""), "verdict": "pass", "claims": [], "unsupported": []}
    claims = [s for s in split(lead.get("body") or "") if about_recipient(s, lead)]
    if not claims:
        return out
    questions = {f"q{i}": f'Is this sentence fully supported by the evidence, with nothing added? "{s}"'
                 for i, s in enumerate(claims)}
    try:
        probs = judge(evidence(lead), questions)
        scored = [{"sentence": s, "supported": float(probs.get(f"q{i}", 0.0))}  # missing answer fails closed
                  for i, s in enumerate(claims)]
    except Exception as e:  # contract: review never raises; str(e) could carry a key
        return {"login": out["login"], "verdict": "unchecked", "claims": [], "unsupported": [],
                "reason": type(e).__name__}
    out["claims"] = scored
    out["unsupported"] = [c["sentence"] for c in scored if not c["supported"] >= 0.5]  # NaN fails closed
    out["verdict"] = "fail" if out["unsupported"] else "pass"
    return out


def findings(leads: list[dict], judge) -> list[dict]:
    out = []
    for lead in leads:
        r = review(lead, judge)
        if r["verdict"] == "unchecked":
            out.append({"login": r["login"], "rule": "review_unavailable", "detail": r["reason"]})
        out += [{"login": r["login"], "rule": "unsupported_claim", "detail": s} for s in r["unsupported"]]
    return out


def snap_judge(state: str, questions: dict[str, str], *, client: httpx.Client | None = None) -> dict[str, float]:
    key = os.environ.get("SUBQ_API_KEY")
    if not key:
        raise RuntimeError("no SUBQ_API_KEY")
    sent = dict(list(questions.items())[:MAX_QUESTIONS])
    if not sent:
        return {}
    payload = {"model": MODEL, "state": state,
               "questions": {i: {"type": "noul", "instructions": q, "criteria": _CRITERIA}
                             for i, q in sent.items()}}
    r = (client or httpx).post(SUBQ_URL, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=20)
    if not 200 <= r.status_code < 300:
        raise RuntimeError(f"SubQ HTTP {r.status_code}")
    answers = r.json()["answers"]
    probs = {i: float((answers.get(i) or {}).get("noul", 0.0)) for i in sent}
    return {**{i: 0.0 for i in questions}, **probs}  # questions past the cap fail closed
