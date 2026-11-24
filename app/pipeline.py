"""Intake -> ICP -> GitHub signals -> Moss pain match -> enrich -> qualify -> graph."""
import asyncio
import datetime
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

import anthropic
import httpx
from moss import DocumentInfo, MossClient, QueryOptions
from pydantic import BaseModel

from app import billing, checks, enrich, reviewer, scoring, scout_web, store

MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")
INDEX = "issues"
MIN_MATCH = 0.3  # below this a Moss hit is noise (measured on the first 84 issues)
MIN_FIT = 40  # below this the Qualifier itself doubts the lead; lesson from the first simulation (loose matches)
MAX_LEADS = 25  # shortcut: caps LLM calls per run; raise when runs are queued, not live
ICP_PATH = "data/icp.json"

state = {"running": False, "log": [], "events": [], "error": ""}


def _n(n: int, one: str, many: str = "") -> str:
    """A count with its noun: 1 draft, 4 drafts."""
    return f"{n} {one if n == 1 else many or one + 's'}"


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


class Channel(BaseModel):
    domain: str  # a bare public host such as "news.ycombinator.com"
    kind: Literal["forum", "community", "reviews", "social", "tracker"]
    why: str  # one sentence: why this buyer writes there


class Learned(BaseModel):
    pains: list[str]


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
    channels: list[Channel]
    process_areas: list[str]


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
sentence a founder would understand.
`channels` are the four to six public places where THIS buyer describes THIS kind of problem in
their own words, chosen for the buyer and not for software in general: engineers write in issue
trackers, Hacker News and the relevant subreddits; finance or operations staff in accounting and
operations communities and on review sites; shop owners in seller forums; consumers in the consumer
communities for that category. `domain` is a real, well-known bare host (for example
"news.ycombinator.com"), never a vendor's own site, never LinkedIn or any site that needs a login to
read. `kind` is forum, community, reviews, social or tracker. `why` is one sentence on why this
buyer writes there. `process_areas` are three to five short names of the jobs this product touches,
in the buyer's own words."""

LEARN_SYSTEM = """You are given pain statements already being searched for, and the real posts that matched them best.
Write up to three additional pain statements in the wording these real people used: their terms,
their level of detail, never marketing words. Each must differ in substance from every existing
statement, not paraphrase it. One plain sentence each. Return an empty list if the posts add nothing new."""


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


class Rewrite(BaseModel):
    subject: str
    body: str


REWRITE_SYSTEM = """You rewrite one outreach email so that it says only what the evidence shows.
You are given the evidence (what this person wrote in public), your earlier draft, and the sentences
an independent reviewer found the evidence does not support. Remove or soften each flagged sentence.
Add no new claim about the person, their company, their numbers or their timeline. Keep the same
voice, the same ask and the same subject unless the subject itself overreaches; keep it short.
No sign-off, no signature, no bracketed placeholders."""


# --- GitHub ----------------------------------------------------------------

def _token() -> str:
    if os.getenv("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True).stdout.strip()
    except FileNotFoundError:  # a server without the gh CLI reads public issues unauthenticated (60 requests an hour)
        return ""


def gh(path: str, **params):
    r = httpx.get("https://api.github.com" + path, params=params, timeout=30,
                  headers={"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {t}"} if (t := _token()) else {})})
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

async def match_pains(issues: list[dict], pains: list[str], index: str = INDEX,
                      refine=None) -> dict[str, tuple[str, float]]:
    """Returns {issue id: (best matching pain, score)} for hits above MIN_MATCH.

    `refine(best_so_far, issues_by_id) -> list[str]` runs once between two query rounds on the same index:
    the statements it returns are queried too and the best score per issue wins. If it fails, round one stands.
    """
    moss = MossClient(os.environ["MOSS_PROJECT_ID"], os.environ["MOSS_PROJECT_KEY"])
    if any(ix.name == index for ix in await moss.list_indexes()):
        await moss.delete_index(index)
    await moss.create_index(index, [DocumentInfo(id=i["id"], text=f"{i['title']}\n{i['body']}") for i in issues])
    try:
        await moss.load_index(index)
        best: dict[str, tuple[str, float]] = {}

        async def query(statements: list[str]) -> None:
            for pain in statements:
                res = await moss.query(index, pain, QueryOptions(top_k=20))
                for d in res.docs:
                    if d.score >= MIN_MATCH and d.score > best.get(d.id, ("", 0))[1]:
                        best[d.id] = (pain, d.score)

        await query(pains)
        if refine:
            try:
                await query(list(refine(best, {i["id"]: i for i in issues}) or [])[:3])
            except Exception:  # the extra round is a bonus: never fail a run because of it
                pass
        return best
    finally:
        # The index is only needed for this run, and the free plan holds three: always give the slot back.
        await moss.delete_index(index)


def learn_pains(pains: list[str], best: dict, issues_by_id: dict) -> list[str]:
    """Up to three statements in the words the best-matching real posts used, each new against `pains`."""
    top = sorted(best, key=lambda k: -best[k][1])[:8]
    if not top:
        return []
    posts = "\n\n".join(f"{issues_by_id[k]['title']}\n{issues_by_id[k]['body'][:300]}" for k in top)
    got = ask(Learned, LEARN_SYSTEM, "Statements already searched:\n" + "\n".join(f"- {p}" for p in pains)
              + f"\n\nBest-matching real posts:\n{posts}").pains
    seen = {p.strip().lower() for p in pains}
    return [p.strip() for p in got if p.strip() and p.strip().lower() not in seen][:3]


# --- Pipeline ----------------------------------------------------------------

def _same_org(company: str, product: str, product_repo: str) -> bool:
    """True when a lead's company is the seller itself: its own staff are not prospects."""
    c = re.sub(r"[^a-z0-9]", "", company.lower())
    own = {re.sub(r"[^a-z0-9]", "", x.lower()) for x in (product.split()[0] if product else "", product_repo.split("/")[0])}
    return bool(c) and c in own - {""}


def load_icp() -> dict | None:
    return json.load(open(ICP_PATH)) if os.path.exists(ICP_PATH) else None


def build_leads(description: str, product_repo: str = "", *, say=say, contact: bool = True,
                index: str = INDEX, sources: list[str] | None = None) -> tuple[dict, list[dict]]:
    """One full pass with no side effects on the graph: returns (icp, leads). Each lead carries its signals.

    `contact=False` skips paid email lookups and the credit gate, for simulations.
    """
    say("Planner: inferring the customer profile and pain statements")
    icp = ask(ICP, ICP_SYSTEM, description)

    if not icp.tracker_fit:
        # Lesson from the first simulation: stop before spending anything when the method cannot work.
        raise RuntimeError(f"Overheard is not a fit for this product: {icp.tracker_fit_reason}")

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
    learned: list[str] = []

    def refine(best, issues_by_id):  # the Planner wrote its statements before seeing one real post
        learned.extend(learn_pains(icp.pains, best, issues_by_id))
        return learned

    hits = asyncio.run(match_pains(issues, icp.pains, index, refine)) if issues else {}
    if learned:
        say("Scout: learned how these people phrase it: " + "; ".join(learned))
    by_author: dict[str, list[dict]] = {}
    for i in issues:
        if i["id"] in hits:
            i["pain"], i["match"] = hits[i["id"]]
            by_author.setdefault(i["author"], []).append(i)
    # A third of the cap is kept for web voices, so the GitHub authors cannot crowd them out.
    domains = scout_web.clean_domains([c.domain for c in icp.channels])
    if domains:
        say("Planner → Scout: listening on " + (", ".join(domains[:-1]) + " and " if len(domains) > 1 else "") + domains[-1])
    voices = scout_web.find_voices(icp.pains, icp.process_areas or scout_web.PROCESS_AREAS, domains=domains)
    voices = scout_web.github_voices(voices, repos, gh)
    if scout_web.last["failed"]:
        say(f"Scout: {scout_web.last['failed']} of {scout_web.last['queries']} web searches failed; those sources were not heard")
    src = scout_web.sources.last
    if hn_found := sum(1 for v in voices if v["repo"] == "news.ycombinator.com" and v.get("profile")):
        say(f"Scout: {hn_found} Hacker News posts, each with its author and date")
    if src["hn_failed"]:
        say(f"Scout: {src['hn_failed']} of {src['hn_requests']} Hacker News searches failed; those were not heard")
    if src["reddit_ok"]:
        say(f"Scout: read the author and date of {src['reddit_ok']} Reddit posts from Reddit itself")
    if src["reddit_blocked"]:
        say("Scout: Reddit refused a request, so the remaining Reddit posts keep no named author")
    sellers = [icp.product.split()[0] if icp.product else "", product_repo.split("/")[0]] + [c.name for c in icp.competitors]
    kept = scout_web.drop_sellers(voices, sellers)
    if len(kept) < len(voices):
        say(f"Scout: dropped {len(voices) - len(kept)} posts written by the product's own company or its competitors")
    voices = kept
    web = scout_web.as_people(voices)[:MAX_LEADS // 3]
    if voices:
        say(f"Scout: found {len(voices)} posts on forums and review sites describing a target pain")
    if not issues and not web:
        raise RuntimeError("no public issues or posts found to search")
    ranked = sorted(by_author.items(), key=lambda kv: -max(s["match"] for s in kv[1]))[:MAX_LEADS - len(web)] + web
    say(f"Scout → Qualifier: {len(hits)} of {len(issues)} issues describe a target pain, from {len(by_author)} people; "
        f"passing the top {len(ranked)}" + (f", {len(web)} of them from the web" if web else ""))

    icp_text = json.dumps(icp.model_dump(exclude={"competitors", "expansion", "channels", "process_areas"}))

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
        no_author = login.startswith("web:")  # scout_web.as_people keys an authorless post by its id
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
        elif pre == "C" and not public and not company and not profile.get("blog"):
            # We write to this person, so we look them up, unless the profile gives the search nothing to start from.
            found = {"email": "", "email_status": "", "steps": ["nothing on the profile to search from: lookup skipped"]}
        else:
            found = enrich.enrich(name, company, public, blog=profile.get("blog") or "")
            billing.record("lead.enriched", login, tier=pre)
        score = scoring.score(ql.fit, top, newest, today, found.get("email_status") or "")
        leads.append(dict(
            login=login, name=name or login,
            url=(signals[0].get("profile") or signals[0]["url"]) if web else profile.get("html_url") or f"https://github.com/{login}",
            company=company, email=found.get("email") or "", email_status=found.get("email_status") or "",
            domain=found.get("domain") or "", linkedin_url=found.get("linkedin_url") or "",
            position=found.get("position") or "", enrich=" · ".join(found["steps"]), newest=newest,
            blog=profile.get("blog"), bio=profile.get("bio"), location=profile.get("location"),
            followers=profile.get("followers") or 0, role=ql.role, fit=ql.fit, production=ql.production_user,
            reason=ql.reason, score=score, tier=scoring.tier(score), stage="Matched", stage_actor="agent",
            subject="" if no_author else ql.subject, body="" if no_author else ql.body,
            draft_status="no_author" if no_author else "pending", signals=signals, _prompt=prompt))

    verified = sum(1 for l in leads if l["email_status"] == "valid")
    say(f"Enricher → Writer: {len(leads)} leads kept, {verified} with an address verified by Hunter")
    drafted = sum(1 for l in leads if l["draft_status"] != "no_author")  # a post with no author gets no message
    say(f"Writer → Reviewer: {_n(drafted, 'message')} drafted from each person's own words")
    if weak:
        say(f"Qualifier: dropped {weak} people whose issue does not show a problem this product solves")
    if authorless := sum(1 for l in leads if l["draft_status"] == "no_author"):
        say(f"Writer: wrote nothing for {_n(authorless, 'post')} with no named author; there is nobody to write to, "
            "so they are kept as evidence only")

    # Check, then fix once. A draft that still breaks a rule after one retry is left for the human to see.
    fixable = {"placeholder", "long_body", "long_subject", "empty_draft"}
    broken = {}
    for f in checks.check_leads(leads, store.STAGES):
        if f["rule"] in fixable and not f["login"].startswith("web:"):
            broken.setdefault(f["login"], []).append(f"{f['rule']}: {f['detail']}")
    if broken:
        say(f"Reviewer → Writer: {_n(len(broken), 'draft')} broke a writing rule; rewriting each once")

        def redraft(lead):
            ql = ask(Qualification, QUALIFY_SYSTEM, lead["_prompt"] + "\n\nYour last draft broke these rules; "
                     "keep your judgment of the lead and rewrite only the subject and body:\n" + "\n".join(broken[lead["login"]]))
            lead["subject"], lead["body"] = ql.subject, ql.body

        with ThreadPoolExecutor(8) as pool:
            list(pool.map(redraft, [l for l in leads if l["login"] in broken]))
    cut = 0
    for lead in leads:  # before the Reviewer: a figure the person never wrote cannot be true of them
        lead["body"], lead["_guard_removed"] = reviewer.guard(lead["body"], reviewer.full_evidence(lead))
        cut += bool(lead["_guard_removed"])
    if cut:
        say(f"Reviewer: removed {_n(sum(len(l['_guard_removed']) for l in leads), 'sentence')} stating a number the person "
            f"never wrote, from {_n(cut, 'draft')}")
    for lead in leads:
        lead.pop("_prompt")
        for s in lead["signals"]:
            s["excerpt"] = s["body"][:300]
    out = {**icp.model_dump(), "description": description, "product_repo": product_repo, "repos": repos,
           "learned_pains": learned}
    if sources is not None:
        out["sources"] = sources  # the pages the description was read from
    return out, leads


def rewrite(lead: dict, flagged: list[str]) -> tuple[str, str]:
    """The Writer, once more, held to the evidence and the Reviewer's flagged sentences."""
    got = ask(Rewrite, REWRITE_SYSTEM, f"Evidence:\n{reviewer.evidence(lead)}\n\nYour draft:\nSubject: {lead['subject']}\n"
              f"{lead['body']}\n\nSentences the evidence does not support:\n" + "\n".join(f"- {s}" for s in flagged))
    broke = [f for f in checks.check_leads([{**lead, "subject": got.subject, "body": got.body}], store.STAGES)
             if f["rule"] in ("placeholder", "long_body", "long_subject", "empty_draft")]
    if broke:
        raise ValueError(f"rewrite broke a writing rule: {broke[0]['rule']}")
    return got.subject, got.body


def repair_drafts(leads: list[dict], judge=None) -> None:
    """After the Reviewer's first pass: rewrite each failed draft once and keep it only if a second review passes.

    Never raises: if anything here fails, the first-pass reviews and their holds stand.
    """
    from app import autopilot  # autopilot imports this module
    try:
        st = autopilot.load()
        for lead in leads:
            if lead.get("_guard_removed") and lead["login"] in st["reviews"]:
                st["reviews"][lead["login"]]["guard_removed"] = lead["_guard_removed"]
        n = reviewer.repair(leads, st["reviews"], rewrite, judge or reviewer.snap_judge)
        autopilot.save(st)
    except Exception as e:  # contract: the run never fails here
        say(f"Reviewer: could not try rewrites ({type(e).__name__}); the first review stands")
        return
    if n["rewritten"]:
        say(f"Reviewer → Writer: {_n(n['rewritten'], 'draft')} claimed more than the evidence shows; rewrote "
            f"{'it' if n['rewritten'] == 1 else 'them'} from the evidence. {n['passed']} now "
            f"{'passes' if n['passed'] == 1 else 'pass'}, {n['held']} held for you.")


def run(description: str, product_repo: str = "", review=None, sources: list[str] | None = None,
        keep_log: bool = False) -> None:
    """The live run: build the leads, then write them to the graph the app reads."""
    state.update(running=True, error="", **({} if keep_log else dict(log=[], events=[])))  # keep_log: the caller already logged
    try:
        billing.reset()
        icp, leads = build_leads(description, product_repo, sources=sources)
        json.dump(icp, open(ICP_PATH, "w"), indent=2)
        if review:
            review(leads)  # while the leads still carry the full issue text the Writer saw
            repair_drafts(leads)
        for lead in leads:
            lead.pop("_guard_removed", None)
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
        drafted = sum(1 for l in leads if l["draft_status"] != "no_author")
        say(f"Done: {_n(len(leads), 'person', 'people')} kept, {_n(drafted, 'message')} drafted")
    except Exception as e:  # surfaced in the UI; the run must always release the lock
        state["error"] = f"{type(e).__name__}: {e}"
        say(f"Failed: {state['error']}")
    finally:
        state["running"] = False
