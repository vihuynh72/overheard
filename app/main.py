"""HTTP API and the single-page UI. No auth: shortcut for the demo, add it before real users."""
import os
import threading
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from app import autopilot, billing, mailer, pipeline, policy, store, voice  # noqa: E402

app = FastAPI(title="Earshot")
app.mount("/static", StaticFiles(directory="static"), name="static")


class RunIn(BaseModel):
    description: str = Field(min_length=20, max_length=20000)
    product_repo: str = Field(default="", max_length=100, pattern=r"^$|^[\w.-]+/[\w.-]+$")


class Decision(BaseModel):
    action: Literal["approve", "reject"]
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=5000)
    reason: str = Field(default="", max_length=500)


class StageIn(BaseModel):
    stage: str


@app.get("/")
def landing():
    return FileResponse("static/landing.html" if os.path.exists("static/landing.html") else "static/index.html")


@app.get("/app")
def index():
    return FileResponse("static/index.html")


def _run(description: str, product_repo: str) -> None:
    pipeline.run(description, product_repo, review=autopilot.review_drafts)
    try:
        autopilot.after_run()  # Reviewer, then Sender if autonomy has been earned
    except Exception as e:  # a failed review must not look like a clean run
        pipeline.state["error"] = f"{type(e).__name__}: {e}"
        pipeline.say(f"Failed after the run: {pipeline.state['error']}")


@app.post("/api/run", status_code=202)
def run(body: RunIn):
    if pipeline.state["running"]:
        raise HTTPException(409, "a run is already in progress")
    pipeline.state["running"] = True  # set here so a second click cannot race the thread start
    threading.Thread(target=_run, args=(body.description, body.product_repo), daemon=True).start()
    return {"started": True}


@app.get("/api/state")
def state():
    leads = store.leads()
    return {"status": pipeline.state, "icp": pipeline.load_icp(), "leads": leads, "events": store.events(),
            "stages": store.STAGES, "checks": autopilot.findings(leads, autopilot.load()),
            "floor": autopilot.floor(leads), "expansions": autopilot.load()["expansions"], "map": autopilot.market_map(leads),
            "billing": {**billing.balance(), "low_water": billing.LOW_WATER, "costs": billing.COSTS,
                        "ledger": billing.ledger()[:100], "by_lead": billing.cost_by_lead()}}


class ExpansionIn(BaseModel):
    segment: str = Field(min_length=1, max_length=300)
    action: Literal["accept", "dismiss"]


@app.post("/api/expansion")
def expansion(body: ExpansionIn):
    """The founder's call on an adjacent segment the Planner suggested."""
    st = autopilot.load()
    st["expansions"][body.segment] = body.action
    autopilot.save(st)
    return st["expansions"]


class Autonomy(BaseModel):
    level: Literal["shadow", "supervised", "autopilot"]


@app.post("/api/autonomy")
def autonomy(body: Autonomy):
    """Ask for a level. The gates decide whether it is granted; the answer says which ones blocked it."""
    return autopilot.set_level(body.level)


class VoiceIn(BaseModel):
    text: str = Field(max_length=2000)
    context: dict = {}


@app.post("/api/voice")
def hear(body: VoiceIn):
    """Spoken words to one allowed action; the page carries it out through the same routes as a click."""
    return voice.interpret(body.text, body.context, pipeline.ask)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@app.post("/api/speak")
def speak(body: SpeakIn):
    try:
        return Response(voice.speak(body.text), media_type="audio/mpeg")
    except RuntimeError as e:  # voice.speak's messages never carry the key
        raise HTTPException(503, str(e))


@app.post("/api/policy")
def set_policy(body: dict):
    st = autopilot.load()
    try:
        st["policy"] = policy.validate({**st["policy"], **body})
    except ValueError as e:
        raise HTTPException(422, str(e))
    autopilot.save(st)
    return st["policy"]


class TopUp(BaseModel):
    credits: float = Field(gt=0, le=1000)


@app.post("/api/billing/top-up")
def top_up(body: TopUp):
    return billing.top_up(body.credits)


def _lead(login: str) -> dict:
    rows = store.q("MATCH (p:Person {login: $login}) RETURN p.subject AS subject, p.body AS body, p.tier AS tier", login=login)
    if not rows:
        raise HTTPException(404, "no such lead")
    return rows[0]


@app.post("/api/leads/{login:path}/decision")  # path: a web lead's login is "host/handle"
def decide(login: str, d: Decision):
    lead = _lead(login)
    st, leads = autopilot.load(), store.leads()
    full = next(l for l in leads if l["login"] == login)
    if full["draft_status"] == "pending":
        autopilot.record_human(full, d.action, st, autopilot.findings(leads, st))
    if d.action == "reject":
        store.upsert("Person", "login", dict(login=login, draft_status="rejected", stage="Closed/Lost", stage_actor="rep"))
        store.log(login, "rep", "rejected", d.reason)
        rule = policy.suggest_rule(full, d.reason) if d.reason.strip() else None
        same = ("field", "op", "value", "action")
        if rule and not any(all(r.get(k) == rule[k] for k in same) for r in st["rules"]):
            st["rules"].append(rule)  # st is the state record_human just saved, so its decision stays
            autopilot.save(st)
            store.log(login, "agent", "learned", rule["reason"])
        return {"ok": True}
    gate = billing.gate("outreach.sent", login, lead["tier"])
    if not gate["allowed"]:
        raise HTTPException(402, f"{gate['reason']}. Top up credits to continue.")
    subject, body = d.subject or lead["subject"], d.body or lead["body"]
    if (subject, body) != (lead["subject"], lead["body"]):
        store.log(login, "rep", "edited draft")
    store.upsert("Person", "login", dict(login=login, subject=subject, body=body, draft_status="approved",
                                         stage="Contacted", stage_actor="rep"))
    # Nothing is transmitted: real sending needs a verified address and the lead's consent to be contacted.
    billing.record("outreach.sent", login, tier=lead["tier"])
    store.log(login, "rep", "approved", mailer.describe(mailer.send(full, subject, body)))
    return {"ok": True}


@app.post("/api/leads/{login:path}/stage")
def set_stage(login: str, s: StageIn):
    _lead(login)
    if s.stage not in store.STAGES:
        raise HTTPException(422, "unknown stage")
    store.upsert("Person", "login", dict(login=login, stage=s.stage, stage_actor="rep"))
    store.log(login, "rep", "moved", s.stage)
    return {"ok": True}
