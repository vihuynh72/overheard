# Specification coverage

Checked on 2026-11-24 against the code and the running app's `GET /api/state` (6 leads from the Flexprice run).
Status is Built, Partly or Not built. "Board" and "Leads" are views on the `/app` page.

## Module 1: Product intake and ICP

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Chat and structured form intake | Partly | `app/intake.py`, `/` and `/app` | One field: the product's website. No chat and no form. The site is read for us (principle 2). |
| Extract features, constraints | Built | `app/intake.py`, `app/pipeline.py` | Read from the site text and stored as the product description. |
| Extract existing customers and wins | Not built | | Not asked for and not inferred. |
| Extract pricing and monetization | Partly | `app/intake.py` | The site's pricing page is read when it exists. No structured price fields. |
| Target industries (NAICS/SIC) | Partly | `data/icp.json` `industries` | Plain-language industries. No NAICS or SIC codes. |
| Company size tiers | Built | `icp.company_size` | Plain-language bands. |
| Personas, titles, seniority | Built | `icp.personas` | |
| Trigger events | Built | `icp.triggers` | Inferred, not matched to live events such as funding. |
| Field confidence 0.00 to 1.00 | Partly | `app/pipeline.py` `Scored` | Industries, company size, personas and triggers each carry one confidence (Flexprice industries: 0.88). Other fields have none. |
| ICP expansion, accept/adjust/dismiss | Built | `POST /api/expansion`, `icp.expansion` | Accept and dismiss work; one segment accepted today. Adjust is not a separate action. |

## Module 2: Discovery

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Accounts and role-matched buyers | Built | `app/pipeline.py`, Leads view | People are found by what they wrote, then given a role and fit. |
| Websites, filings, press, job posts | Partly | `app/pipeline.py`, `app/scout_web.py` | Public GitHub issue trackers and web forums (Tavily). No filings, press or job posts. |
| Mandatory inline citations | Built | every lead's `signals[].url` | No evidence link, no lead (principle 1). All 6 leads link to their post. |
| Negative signal filtering | Built | `icp.negative_signals`, `app/checks.py` | Applied by the Qualifier model and the lead rules. |
| Competitor categories | Built | `icp.competitors` | Six competitors with category; two have public trackers that are searched. |
| Positioning and value proposition | Built | `icp.competitors[].positioning` | One sentence each. |
| Public pricing tiers | Not built | | |
| Advantages and differentiators | Partly | `/app` market map (`autopilot.market_map`) | Short, model-written. |

## Module 3: Knowledge graph

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Native graph store | Built | `app/store.py` (Kùzu 0.11.3) | |
| Nodes Company, Person, Product, Competitor, Signal | Built | `app/store.py` `SCHEMA` | Competitor is a `Repo` with `kind = competitor` linked to `Product` by `COMPETES_WITH`. `Pain` is added too. Competitors without a public repo are only in the ICP, not the graph. |
| Edges works_at, competes_with, matched_to | Built | `app/graphq.py` `sync` | `MATCHED_TO` and `COMPETES_WITH` are derived after each run and on startup. |
| Edges contacted_via, replied_to | Partly | `Person.stage`, `Event` nodes | Stored as a stage and an audit event, not as edges. |
| Edge previously_employed_at | Not built | | We have no employment history data. |
| Multi-hop queries | Built | `app/graphq.py`, `GET /api/graph/insights`, `graph` in `/api/state` | Five queries. On today's graph: 6 of 6 people found on a competitor's tracker; 4 pairs at different or unknown companies share a pain; no company has two people. |
| Warm intro paths | Partly | `graphq.account_depth` | Same-company paths only. No education or past employment. Empty on today's graph. |
| Job requisitions to buying cycles | Not built | | No job post source. |
| Competitor displacement | Built | `graphq.displacement` | From what people wrote on competitor trackers, not from renewal or churn data. |
| Continuous signal ingestion | Partly | `app/autopilot.py` | Each run rebuilds the graph from fresh posts. No scheduled refresh. |
| Graph shown in the interface | Partly | `static/app.js` | The `graph` block is new in `/api/state`; the interface does not render it yet. |

## Module 4: Enrichment and outreach

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Enrichment vendors | Partly | `app/enrich.py` | Hunter only (finder, domain search, verifier) plus Tavily to find a company domain. No Apollo, Clearbit or Prospeo. |
| Email with deliverability status | Partly | `Person.email_status` | Hunter's verification status. No separate MX check. 1 of 6 leads has a verified email today; weak-fit leads are skipped to save credits. |
| LinkedIn URL | Partly | `Person.linkedin_url` | Kept when a source gives one. Not validated. |
| Domain and HQ | Partly | `Person.domain`, `Person.location` | Domain yes. Location is the GitHub profile's, not HQ. |
| Multi-touch Email and LinkedIn | Partly | `app/pipeline.py` Writer | One email per person. No LinkedIn message, no sequence. |
| Weave trigger signals in copy | Built | drafts, `app/reviewer.py` | Every claim must trace to the person's post; a second model checks it. |
| Persona tone, length, CTA | Partly | `app/checks.py` | Lead and draft rules are enforced on every run. No per-persona tone. |
| HITL approve, edit, reject | Built | `POST /api/leads/{login}/decision`, lead detail in `/app` | Nothing is sent without approval unless autonomy is earned. |

## Module 5: Dashboard

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Kanban with five stages | Partly | `static/app.js` `board()`, Board view | In progress today in `static/app.js` by another worker. Stages and moves work through `POST /api/leads/{login}/stage`. |
| AI vs rep attribution | Built | `Person.stage_actor`, `Event.actor` | Every stage change and decision says who did it. |
| Timestamps and audit log | Built | `Event` nodes, `/api/state` `events` | |
| Conversion by stage, industry, tier | Partly | funnel line in `/app` | Counts per stage and per tier. No rates by industry. |
| A/B variant analytics | Not built | | |

## Bonus: Band Desktop

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Planner, Builder, Reviewer, Security agents | Partly | `docs/band-run.md`, `scripts/band/` | Four real Band chats planned, wrote and reviewed one change. They ran read-only; an operator session relayed and applied the diff. |
| @mention handoffs, HITL on dispatch | Partly | `docs/band-run.md` | One handoff hit a permission prompt; it was cancelled, not approved. |
| Telemetry: streams, tokens, costs | Partly | `band chats watch` streams | Streams shown. No token or cost totals inside Overheard. |

## Bonus: Flexprice

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Metered Leads Enriched, Outreach Sent, Graph Queries | Built | `app/billing.py` `COSTS`, `/api/state` `billing.ledger` | `graph.query` is now fed per lead and once per executed graph query per run. |
| Credit gate on enrichment | Built | `billing.gate` in `app/pipeline.py` and `app/autopilot.py` | Below 15 credits, weak-fit work pauses; out of credits stops it. |
| Per-lead cost | Built | `billing.cost_by_lead` | Today: 2.1 credits for each enriched lead, 0.1 for the others. |

## Bonus: Security (Snyk)

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| SAST and SCA in CI | Partly | `.github/workflows/security.yml`, `docs/security.md` | pip-audit, bandit and gitleaks. Snyk job is ready but has not run: no token. |
| Scan outbound services | Partly | same | Covers `app/mailer.py` and `app/gmail.py` as code. No runtime scan. |

## Architecture tiers

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Neo4j or Kùzu | Built | `app/store.py` | Kùzu, embedded. |
| LLM and RAG | Built | `app/pipeline.py`, Moss | Claude Sonnet 5.5; Moss semantic search over issue text. |
| Tavily, Serper, Playwright | Partly | `app/intake.py`, `app/scout_web.py` | Tavily only. |
| Apollo, Hunter, Clearbit | Partly | `app/enrich.py` | Hunter only. |
| SendGrid, Gmail, LinkedIn | Partly | `app/mailer.py`, `app/gmail.py` | Resend to a test inbox (`delivered@resend.dev`). Gmail is coded but not connected. No LinkedIn. No reply webhooks. |
| Next.js, Tailwind, Radix | Not built | `static/` | Plain HTML, CSS and JS by choice: no build step. |

## Interface

| Spec asks for | Status | Where to see it | Honest note |
|---|---|---|---|
| Editorial plus dense grid | Built | `/app` | |
| Inline enrichment indicators | Partly | `static/app.js` | In progress today in `static/app.js`. |
| Live "agent thinking" feed | Built | `/app` activity list, `status.log` | Shows each step and check. Graph queries are not shown in it. |
| 0 to 100 score and tiers A/B/C | Built | `app/scoring.py`, Leads view | Today: two B, four C, no A. |

## Strongest evidence for each claim

**Verifiable.**
- Every person links to the post where they said it: `signals[].url`, all 6 leads today.
- A second model checks each claim in a draft against that post: `app/reviewer.py`. Today it flags 3 unsupported claims, and they are shown, not hidden.
- Graph insights carry the rows they are built from: `app/graphq.py`.

**Autonomous.**
- One input, the website; the Planner, Qualifier, Writer and Reviewer do the rest: `app/main.py` `_run`.
- Autonomy is earned through trust gates: `app/trust.py`. It has not been earned in a live run yet; every send so far was approved by a person.

**Self-improving.**
- Mistakes are written to a lessons ledger and checked across runs: `app/lessons.py`, `data/lessons.jsonl` (10 entries).
- A rejected draft becomes a learned rule (`app/main.py` decision route), and new pains read from posts are added to the next search: `icp.learned_pains`.
- The Reviewer allows one bounded rewrite per draft, kept only if a fresh review passes: `app/reviewer.py` `MAX_REWRITES_PER_DRAFT = 1`.

**Reliable.**
- 413 tests pass (`.venv/bin/python -m pytest -q`).
- Each sponsor tool is measured for alive, used and quality: `docs/eval.md`.
- Ten product types are simulated end to end: `app/simulate.py`.
- The run budget and credit gate cap spend: `app/main.py`, `app/billing.py`.
- A failing graph query cannot break `/api/state`: `tests/test_graphq.py`.

## What we do not claim

- We do not read filings, press or job posts.
- We do not send LinkedIn messages or multi-step sequences.
- No mail reaches a real lead in this build.
- Snyk has not run.
- Autopilot has not been earned in a live run.
- We have no reply data, so no conversion rates or A/B results.
- Warm paths are same-company only, and none exist on today's graph.
