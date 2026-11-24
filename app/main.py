"""HTTP API and the single-page UI. No auth: shortcut for the demo, add it before real users."""
import os
import threading
import time
from collections import deque
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel, Field, model_validator  # noqa: E402

import logging  # noqa: E402

# httpx logs every request URL at INFO, and Hunter takes its key in the query string: keep keys out of logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

from app import autopilot, billing, gmail, graphq, intake, mailer, mcp_server, pipeline, policy, store, voice  # noqa: E402

app = FastAPI(title="Overheard", lifespan=mcp_server.lifespan)
mcp_server.mount(app)  # /mcp: the same app for agents
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.middleware("http")
async def fresh_static(request, call_next):
    """Browsers must revalidate the page's scripts and styles, or a reload shows an old build."""
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in ("/", "/app"):
        response.headers["Cache-Control"] = "no-cache"
    return response


class RunIn(BaseModel):
    description: str = Field(default="", max_length=20000)
    product_repo: str = Field(default="", max_length=100, pattern=r"^$|^[\w.-]+/[\w.-]+$")
    target: str = Field(default="", max_length=200)  # a website or GitHub repository: Overheard reads the description itself

    @model_validator(mode="after")
    def _needs_one(self):
        if len(self.description) < 20 and not self.target.strip():
            raise ValueError("give a description of at least 20 characters, or a website or GitHub repository")
        return self


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


def _run(description: str, product_repo: str, target: str = "") -> None:
    sources = None
    if target and len(description) < 20:
        pipeline.state.update(log=[], events=[], error="")
        try:
            url = intake.normalize(target)["url"]
        except ValueError as e:
            pipeline.state.update(error=str(e), running=False)
            pipeline.say(f"Planner: {e}")
            return
        pipeline.say(f"Planner: reading {url} to learn what you sell")
        read = intake.read_product(target)
        if read["status"] != "ok":
            pipeline.state.update(error=read["reason"], running=False)
            pipeline.say(f"Planner: {read['reason']}")
            return
        description, sources = read["source_text"], read["sources"]
        product_repo = product_repo or read["repo"]
    pipeline.run(description, product_repo, review=autopilot.review_drafts, sources=sources,
                 keep_log=sources is not None)
    _graph.clear()  # the graph changed: the next read recomputes and meters the queries once
    try:
        autopilot.after_run()  # Reviewer, then Sender if autonomy has been earned
    except Exception as e:  # a failed review must not look like a clean run
        pipeline.state["error"] = f"{type(e).__name__}: {e}"
        pipeline.say(f"Failed after the run: {pipeline.state['error']}")


# The public copy has no sign-in, so a run budget stands between strangers and the owner's credits.
MAX_RUNS_PER_HOUR = int(os.environ.get("MAX_RUNS_PER_HOUR", "6"))
MIN_RUN_GAP_SECONDS = float(os.environ.get("MIN_RUN_GAP_SECONDS", "20"))
_starts: deque[float] = deque()  # time.monotonic() of each run that started in the last hour
_start_lock = threading.Lock()


def reset_run_budget() -> None:
    _starts.clear()


def _wait_phrase(seconds: float) -> str:
    seconds = max(1, int(seconds + 0.999))
    return f"{seconds} seconds" if seconds < 90 else f"{(seconds + 59) // 60} minutes"


def _refusal(now: float) -> str:
    """A plain sentence saying when to try again, or "" if a run may start now."""
    while _starts and now - _starts[0] >= 3600:
        _starts.popleft()
    if _starts and now - _starts[-1] < MIN_RUN_GAP_SECONDS:
        return f"A run just started. Try again in {_wait_phrase(MIN_RUN_GAP_SECONDS - (now - _starts[-1]))}."
    if len(_starts) >= MAX_RUNS_PER_HOUR:
        return (f"This copy allows {MAX_RUNS_PER_HOUR} runs an hour to protect its credits. "
                f"Try again in {_wait_phrase(3600 - (now - _starts[0]))}.")
    return ""


@app.post("/api/run", status_code=202)
def run(body: RunIn):
    """The one way a run starts: the web route and the MCP tool find_leads both come here."""
    with _start_lock:
        if pipeline.state["running"]:
            raise HTTPException(409, "a run is already in progress")
        now = time.monotonic()
        if reason := _refusal(now):  # a refused start spends no budget; the page shows a non-2xx detail as the reason
            raise HTTPException(429, reason)
        _starts.append(now)
        pipeline.state["running"] = True  # set here so a second click cannot race the thread start
    threading.Thread(target=_run, args=(body.description, body.product_repo, body.target.strip()), daemon=True).start()
    return {"started": True}


_graph: dict = {}  # cached graph insights for the current run; cleared when a run finishes


def graph_insights() -> dict:
    """Once per run (and once after startup): sync the derived edges, run the queries, meter each one."""
    if pipeline.state["running"]:  # the graph is half rewritten mid-run; wait for the finished one
        return {"counts": {}, "insights": [], "running": True}
    if not _graph:
        try:
            g = graphq.insights(store.q, pipeline.load_icp() or {},
                                on_query=lambda key: billing.record("graph.query", query=key))
        except Exception as e:  # graph reasoning must never take /api/state down with it
            return {"counts": {}, "insights": [], "error": f"{type(e).__name__}: {e}"}
        _graph.update(g)
    return _graph


@app.get("/api/graph/insights")
def get_graph_insights():
    return graph_insights()


@app.get("/api/state")
def state():
    leads = store.leads()
    return {"status": pipeline.state, "icp": pipeline.load_icp(), "leads": leads, "events": store.events(),
            "stages": store.STAGES, "checks": autopilot.findings(leads, autopilot.load()),
            "floor": autopilot.floor(leads), "expansions": autopilot.load()["expansions"], "map": autopilot.market_map(leads),
            "billing": {**billing.balance(), "low_water": billing.LOW_WATER, "costs": billing.COSTS,
                        "ledger": billing.ledger()[:100], "by_lead": billing.cost_by_lead()},
            "mail": {**gmail.status(), "resend": bool(os.environ.get("RESEND_API_KEY"))},
            "graph": graph_insights()}


@app.get("/api/gmail/connect")
def gmail_connect():
    if not gmail.configured():
        raise HTTPException(503, "Gmail is not set up: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are missing")
    return RedirectResponse(gmail.auth_url(gmail.new_state()))


@app.get("/api/gmail/callback")
def gmail_callback(state: str = "", code: str = ""):
    if not gmail.check_state(state) or not code:
        raise HTTPException(400, "This sign-in link is invalid or was already used. Connect Gmail again.")
    gmail.exchange(code)
    return RedirectResponse("/app#activity")


@app.post("/api/gmail/disconnect")
def gmail_disconnect():
    gmail.disconnect()
    return gmail.status()


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
    sent = mailer.send(full, subject, body)
    if sent["status"] == "sent":  # a credit is only spent on mail that actually left
        billing.record("outreach.sent", login, tier=lead["tier"])
    store.log(login, "rep", "approved", mailer.describe(sent))
    return {"ok": True}


@app.post("/api/leads/{login:path}/stage")
def set_stage(login: str, s: StageIn):
    _lead(login)
    if s.stage not in store.STAGES:
        raise HTTPException(422, "unknown stage")
    store.upsert("Person", "login", dict(login=login, stage=s.stage, stage_actor="rep"))
    store.log(login, "rep", "moved", s.stage)
    return {"ok": True}
