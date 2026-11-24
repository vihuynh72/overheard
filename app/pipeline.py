"""Intake -> ICP -> GitHub signals -> Moss pain match -> enrich -> qualify -> graph."""
import asyncio
import datetime
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

import anthropic
import httpx
from moss import DocumentInfo, MossClient, QueryOptions
from pydantic import BaseModel

from app import billing, checks, enrich, scoring, scout_web, store

MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
INDEX = "issues"
MIN_MATCH = 0.3  # below this a Moss hit is noise (measured on the first 84 issues)
MIN_FIT = 40  # below this the Qualifier itself doubts the lead; lesson from the first simulation (loose matches)
MAX_LEADS = 25  # shortcut: caps LLM calls per run; raise when runs are queued, not live
ICP_PATH = "data/icp.json"

state = {"running": False, "log": [], "events": [], "error": ""}


def say(msg: str) -> None:
    """Log a step. "Scout → Qualifier: text" is also recorded as a handoff the Floor view can draw."""
    state["log"].append(msg)
    m = re.match(r"^(\w+)(?: → (\w+))?: (.*)$", msg, re.S)
    state["events"].append({
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"),
        "from": m.group(1).lower() if m else "system", "to": (m.group(2) or m.group(1)).lower() if m else "",
        "text": m.group(3) if m else msg})


# --- LLM -----------------------------------------------------------------

def ask(schema, system: str, user: str):
    r = anthropic.Anthropic().beta.messages.parse(
        model=MODEL, max_tokens=16000, system=system,
        messages=[{"role": "user", "content": user}],
        output_format=schema, output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    )
    if r.stop_reason == "refusal" or r.parsed_output is None:
        raise RuntimeError(f"model returned no usable output (stop_reason={r.stop_reason})")
    return r.parsed_output


class Scored(BaseModel):
    values: list[str]
    confidence: float


class Expansion(BaseModel):
    segment: str
    reasoning: str


class Competitor(BaseModel):
    name: str
    category: str  # direct | indirect | alternative
    positioning: str
    github_repo: str  # "owner/name" of its public issue tracker, or "" if closed source


class ICP(BaseModel):
    product: str
    industries: Scored
    company_size: Scored
    personas: Scored
    triggers: Scored
    pains: list[str]
    negative_signals: list[str]
    expansion: list[Expansion]
    competitors: list[Competitor]
    tracker_fit: bool
    tracker_fit_reason: str


ICP_SYSTEM = """You define the ideal customer profile for a B2B product from its description.
Confidence is 0.00-1.00 and reflects how directly the description supports the field.
`pains` are 5 search statements, each phrased the way a frustrated engineer would describe the
problem in a bug report or forum post, never in the vendor's marketing words.
`negative_signals` are traits that make a company a poor fit.
For competitors, give `github_repo` only when you are confident the project is open source and
you know its exact owner/name; otherwise leave it empty.
`tracker_fit` says whether this method can work at all: true only when the buyers are developers or
technical founders AND open-source projects in this space have public issue trackers where those
buyers describe their problems. It is false for consumer apps, local services, products bought by
non-technical staff, and descriptions too vague to name a buyer. `tracker_fit_reason` is one plain
sentence a founder would understand."""


class Qualification(BaseModel):
    fit: int  # 0-100
    production_user: bool
    role: str
    reason: str
    subject: str
    body: str


QUALIFY_SYSTEM = """You qualify one sales lead for the product whose ICP is given.
The lead is a person who opened public GitHub issues on a competing or related project.
Judge only from the evidence given. `production_user` is true only if the issues show real
production use (customers, scale, invoices, outages), not a hobby install or drive-by suggestion.
`fit` is 0-100 against the ICP and its negative signals. Using a similar tool is not the same as
having the problem: an ordinary bug, a setup question, or a request about that tool's internals is
evidence only if this product would plausibly remove the problem, and otherwise scores below 30. `reason` is one sentence that names the
evidence. `role` is your best reading of their job from the profile, or "unknown".
Then draft a first outreach email: subject under 8 words, body under 90 words, plain and specific.
Refer to the problem they described in their own issue. State nothing about them or their company
that the evidence does not show. No flattery, no fake familiarity, one clear ask.
End after the ask: no sign-off, no signature, and no bracketed placeholders such as [Name]."""


# --- GitHub ----------------------------------------------------------------

def _token() -> str:
    return os.getenv("GITHUB_TOKEN") or subprocess.run(
        ["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()


def gh(path: str, **params):
    r = httpx.get("https://api.github.com" + path, params=params, timeout=30,
                  headers={"Authorization": f"Bearer {_token()}", "Accept": "application/vnd.github+json"})
    return r.json() if r.status_code == 200 else None


def _clean(body: str) -> str:
    """Drop issue-template scaffolding so the excerpt and the search index hold the author's words."""
    body = re.sub(r"(?s:<!--.*?-->)|\*\*[^*\n]{0,120}\*\*|^#{1,6} .*$", " ", body, flags=re.M)
    return re.sub(r"\s+", " ", body).strip()


def fetch_issues(repo: str, pages: int = 3) -> list[dict]:
    out = []
    for page in range(1, pages + 1):
        res = gh("/search/issues", q=f"repo:{repo} is:issue", sort="created", order="desc", per_page=100, page=page)
        items = (res or {}).get("items", [])
        for i in items:
            # Maintainers are not leads; bots have no inbox.
            if i["user"]["type"] != "User" or i["author_association"] in ("MEMBER", "OWNER", "COLLABORATOR"):
                continue
            out.append(dict(id=f"{repo}#{i['number']}", repo=repo, url=i["html_url"], title=i["title"],
                            body=_clean(i.get("body") or "")[:1500], author=i["user"]["login"], created=i["created_at"][:10]))
        if len(items) < 100:
            break
    return out


# --- Moss ------------------------------------------------------------------

async def match_pains(issues: list[dict], pains: list[str], index: str = INDEX) -> dict[str, tuple[str, float]]:
    """Returns {issue id: (best matching pain, score)} for hits above MIN_MATCH."""
    moss = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
    if any(ix.name == index for ix in await moss.list_indexes()):
        await moss.delete_index(index)
    await moss.create_index(index, [DocumentInfo(id=i["id"], text=f"{i['title']}\n{i['body']}") for i in issues])
    try:
        await moss.load_index(index)
        best: dict[str, tuple[str, float]] = {}
        for pain in pains:
            res = await moss.query(index, pain, QueryOptions(top_k=20))
            for d in res.docs:
                if d.score >= MIN_MATCH and d.score > best.get(d.id, ("", 0))[1]:
                    best[d.id] = (pain, d.score)
        return best
    finally:
        # The index is only needed for this run, and the free plan holds three: always give the slot back.
        await moss.delete_index(index)


# --- Pipeline ----------------------------------------------------------------

def _same_org(company: str, product: str, product_repo: str) -> bool:
    """True when a lead's company is the seller itself: its own staff are not prospects."""
    c = re.sub(r"[^a-z0-9]", "", company.lower())
    own = {re.sub(r"[^a-z0-9]", "", x.lower()) for x in (product.split()[0] if product else "", product_repo.split("/")[0])}
    return bool(c) and c in own - {""}


def load_icp() -> dict | None:
    return json.load(open(ICP_PATH)) if os.path.exists(ICP_PATH) else None


def build_leads(description: str, product_repo: str = "", *, say=say, contact: bool = True,
                index: str = INDEX) -> tuple[dict, list[dict]]:
    """One full pass with no side effects on the graph: returns (icp, leads). Each lead carries its signals.

    `contact=False` skips paid email lookups and the credit gate, for simulations.
    """
    say("Planner: inferring the customer profile and pain statements")
    icp = ask(ICP, ICP_SYSTEM, description)

    if not icp.tracker_fit:
        # Lesson from the first simulation: stop before spending anything when the method cannot work.
        raise RuntimeError(f"Earshot is not a fit for this product: {icp.tracker_fit_reason}")

    repos = {}
    if product_repo:
        repos[product_repo] = "product"
    for c in icp.competitors:
        if c.github_repo and gh(f"/repos/{c.github_repo}"):  # drop repos the model made up
            repos[c.github_repo] = "competitor"
    say(f"Planner → Scout: watch {len(repos)} public issue trackers ({', '.join(repos) or 'none found'})")

    issues = []
    for repo in repos:
        found = fetch_issues(repo)
        say(f"Scout: {repo} has {len(found)} issues from outside users")
        issues += found
    hits = asyncio.run(match_pains(issues, icp.pains, index)) if issues else {}
    by_author: dict[str, list[dict]] = {}
    for i in issues:
        if i["id"] in hits:
            i["pain"], i["match"] = hits[i["id"]]
            by_author.setdefault(i["author"], []).append(i)
    # A third of the cap is kept for web voices, so the GitHub authors cannot crowd them out.
    voices = scout_web.find_voices(icp.pains, scout_web.PROCESS_AREAS)
    web = scout_web.as_people(voices)[:MAX_LEADS // 3]
    if voices:
        say(f"Scout: found {len(voices)} posts on forums and review sites describing a target pain")
    if not issues and not web:
        raise RuntimeError("no public issues or posts found to search")
    ranked = sorted(by_author.items(), key=lambda kv: -max(s["match"] for s in kv[1]))[:MAX_LEADS - len(web)] + web
    say(f"Scout → Qualifier: {len(hits)} of {len(issues)} issues describe a target pain, from {len(by_author)} people; "
        f"passing the top {len(ranked)}" + (f", {len(web)} of them from the web" if web else ""))

    icp_text = json.dumps(icp.model_dump(exclude={"competitors", "expansion"}))

    def qualify(item):
        login, signals = item
        web = signals[0].get("kind") == "web"
        profile = {} if web else gh(f"/users/{login}") or {}  # a forum handle has no GitHub profile
        evidence = "\n\n".join(f"[{s['repo']} {s['created']}] {s['title']}\n{s['body']}" for s in signals)
        keep = {k: profile.get(k) for k in ("name", "company", "bio", "blog", "location", "followers")}
        prompt = (f"ICP:\n{icp_text}\n\nProfile:\n{json.dumps(keep)}\n\n"
                  f"{'Public forum or review posts' if web else 'Issues'}:\n{evidence}")
        return login, signals, profile, prompt, ask(Qualification, QUALIFY_SYSTEM, prompt)

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(qualify, ranked))

    say("Qualifier → Enricher: scored; looking up a business email for the strong leads" if contact
        else "Qualifier: scored (contact lookup off for this run)")
    today = datetime.date.today()
    leads, weak = [], 0
    # Strongest first, so a low balance pauses the weak leads and not the strong ones.
    for login, signals, profile, prompt, ql in sorted(results, key=lambda r: -r[4].fit):
        top, newest = max(s["match"] for s in signals), max(s["created"] for s in signals)
        web = signals[0].get("kind") == "web"
        company = (profile.get("company") or "").lstrip("@").strip()
        name = profile.get("name") or (signals[0]["author"] or signals[0]["repo"] if web else "")
        if ql.fit < MIN_FIT:
            weak += 1
            continue
        if _same_org(company, icp.product, product_repo):
            say(f"Qualifier: dropped {name or login}, who works at {company}, the product's own company")
            continue
        pre = scoring.tier(scoring.score(ql.fit, top, newest, today))
        public = profile.get("email") or ""
        if web:
            found = {"email": "", "email_status": "", "steps": ["web post: no contact lookup"]}
        elif not contact:
            found = {"email": public, "email_status": "", "steps": ["contact lookup off for this run"]}
        elif not (gate := billing.gate("lead.enriched", login, pre))["allowed"]:
            found = {"email": public, "email_status": "", "steps": [f"enrichment not run: {gate['reason']}"]}
        elif pre == "C" and not public:
            # A paid email search is only worth it for a lead we would actually write to.
            found = {"email": "", "email_status": "", "steps": ["weak fit: email search skipped to save credits"]}
        else:
            found = enrich.enrich(name, company, public)
            billing.record("lead.enriched", login, tier=pre)
        score = scoring.score(ql.fit, top, newest, today, found.get("email_status") or "")
        leads.append(dict(
            login=login, name=name or login,
            url=signals[0]["url"] if web else profile.get("html_url") or f"https://github.com/{login}",
            company=company, email=found.get("email") or "", email_status=found.get("email_status") or "",
            domain=found.get("domain") or "", linkedin_url=found.get("linkedin_url") or "",
            position=found.get("position") or "", enrich=" · ".join(found["steps"]), newest=newest,
            blog=profile.get("blog"), bio=profile.get("bio"), location=profile.get("location"),
            followers=profile.get("followers") or 0, role=ql.role, fit=ql.fit, production=ql.production_user,
            reason=ql.reason, score=score, tier=scoring.tier(score), stage="Matched", stage_actor="agent",
            subject=ql.subject, body=ql.body, draft_status="pending", signals=signals, _prompt=prompt))

    verified = sum(1 for l in leads if l["email_status"] == "valid")
    say(f"Enricher → Writer: {len(leads)} leads kept, {verified} with an address verified by Hunter")
    say(f"Writer → Reviewer: {len(leads)} messages drafted from each person's own words")
    if weak:
        say(f"Qualifier: dropped {weak} people whose issue does not show a problem this product solves")

    # Check, then fix once. A draft that still breaks a rule after one retry is left for the human to see.
    fixable = {"placeholder", "long_body", "long_subject", "empty_draft"}
    broken = {}
    for f in checks.check_leads(leads, store.STAGES):
        if f["rule"] in fixable:
            broken.setdefault(f["login"], []).append(f"{f['rule']}: {f['detail']}")
    if broken:
        say(f"Reviewer → Writer: {len(broken)} drafts broke a writing rule; rewriting each once")

        def redraft(lead):
            ql = ask(Qualification, QUALIFY_SYSTEM, lead["_prompt"] + "\n\nYour last draft broke these rules; "
                     "keep your judgment of the lead and rewrite only the subject and body:\n" + "\n".join(broken[lead["login"]]))
            lead["subject"], lead["body"] = ql.subject, ql.body

        with ThreadPoolExecutor(8) as pool:
            list(pool.map(redraft, [l for l in leads if l["login"] in broken]))
    for lead in leads:
        lead.pop("_prompt")
        for s in lead["signals"]:
            s["excerpt"] = s["body"][:300]
    return {**icp.model_dump(), "description": description, "product_repo": product_repo, "repos": repos}, leads


def run(description: str, product_repo: str = "", review=None) -> None:
    """The live run: build the leads, then write them to the graph the app reads."""
    state.update(running=True, log=[], events=[], error="")
    try:
        billing.reset()
        icp, leads = build_leads(description, product_repo)
        json.dump(icp, open(ICP_PATH, "w"), indent=2)
        if review:
            review(leads)  # while the leads still carry the full issue text the Writer saw
        store.reset()
        for repo, kind in icp["repos"].items():
            store.upsert("Repo", "name", dict(name=repo, kind=kind))
        for lead in leads:
            signals = lead.pop("signals")
            store.upsert("Person", "login", lead)
            if lead["company"]:
                store.upsert("Company", "name", dict(name=lead["company"]))
                store.link("Person", "login", lead["login"], "WORKS_AT", "Company", "name", lead["company"])
            for s in signals:
                if s.get("kind") == "web":
                    store.upsert("Repo", "name", dict(name=s["repo"], kind="web"))
                store.upsert("Signal", "id", dict(id=s["id"], url=s["url"], title=s["title"], excerpt=s["excerpt"],
                                                  created=s["created"], pain=s["pain"], match=s["match"]))
                store.link("Person", "login", lead["login"], "RAISED", "Signal", "id", s["id"])
                store.link("Signal", "id", s["id"], "ABOUT", "Repo", "name", s["repo"])
            store.log(lead["login"], "agent", "matched", lead["reason"])
        left = checks.check_leads(store.leads(), store.STAGES)
        say(f"Reviewer: self-check found {len(left)} problems across {len(leads)} leads"
            + (f" ({', '.join(sorted({f['rule'] for f in left}))})" if left else ""))
        say(f"Done: {len(leads)} leads scored and drafted")
    except Exception as e:  # surfaced in the UI; the run must always release the lock
        state["error"] = f"{type(e).__name__}: {e}"
        say(f"Failed: {state['error']}")
    finally:
        state["running"] = False
