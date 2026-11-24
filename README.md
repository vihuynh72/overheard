# Overheard

Overheard is a line of seven agents that finds people describing a problem in public, drafts a message that answers what they wrote, and holds it for the founder's approval. It is for a founder at a small or mid-sized company who sells to developers and has no list of target accounts. Every lead links to the post the person wrote, and in this build no message ever reaches a lead.

Built for HackwithBay 4.0 (San Francisco, 24 November 2026). Live copy: <https://earshot-production.up.railway.app>. Design document: [docs/architecture.md](docs/architecture.md). Decision history with reasons: [docs/log.md](docs/log.md). Band: [docs/band.md](docs/band.md) and the record of a real run, [docs/band-run.md](docs/band-run.md). Text for the submission form: [docs/submission.md](docs/submission.md).

## The idea

Most outbound tools start from a list of companies and then invent a reason to write. Overheard starts from a person's own public words about a problem. The Planner reads your site and decides who your buyers are and where they write (channels and process areas). The Scout reads public GitHub issues on your product's tracker and on your open-source competitors' trackers, and (with a Tavily key) forum and review-site posts from those channels. It matches posts by meaning to pain statements inferred from your product, then learns up to three more pain statements from the best real posts, in one extra round. It drops posts written by sellers, keeps the author, and quotes the post next to the draft.

Autonomy is earned from evidence, not toggled. The Sender can release a message without a per-message click only when five gates pass: a clean self-check, at least 90% agreement over at least 8 judged decisions, no release you would have stopped, a simulation that finds relevant leads, and no fixed mistake that came back. The agreement gate judges only calls that could do harm (an agreed call, or a release you rejected); a lead the agent held and you approved is reported but does not count against it. If an enforced gate fails, autopilot is switched off by code. See [docs/architecture.md](docs/architecture.md#5-trust-model).

## What you see in the app

The landing page is `/`. The app is `/app`: a paper-coloured page with three text links, Customer, People and Activity.

- **Arrival.** One field: your website. A GitHub repository or a typed description also work, behind "Describe it yourself instead". An example mode shows a finished result for a sample product without spending anything.
- **Progress.** While a run goes, a five-step checklist in plain words replaces the raw log.
- **Customer.** Who Overheard decided your buyer is, in plain language, and the evidence for it. If the method cannot work for your product, it says so here and stops.
- **People.** The ranked leads. Choose one to see what they wrote (linked, with the pain it matched), why they were kept, their contact steps and email status, and the draft. A single question card is the only place you act: approve, edit or reject. A rejection reason can become a standing rule.
- **Activity.** The run's steps and self-check findings, the autonomy level and which gates block it, the sending setup (Connect Gmail, or Resend), and the credit balance with a per-event ledger and a top-up.

Deleted today, and no longer in `static/`: the map, the agent creatures, the AI cursor, voice control, the icon rail, and the profile, proof and pipeline sections. `static/` now holds only `app.css`, `app.js`, `ask.css`, `ask.js`, `index.html`, `landing.css`, `landing.html`, `landing.js` and `tokens.css`.

Some server code outlived the pages that used it, and the interface does not call it: `POST /api/voice`, `POST /api/speak` (both in `app/voice.py`, which still needs an ElevenLabs key to speak), `POST /api/policy`, `POST /api/expansion` and `POST /api/leads/{login}/stage`. They work and are tested, but nothing in the current interface reaches them.

## For your own agent: MCP

An MCP server is mounted at `/mcp` on the same app, with six tools, all read-only except `find_leads`:

| Tool | What it does |
| --- | --- |
| `find_leads` | Starts a search for a website or repository. Shares the web route's lock and run budget. |
| `run_status` | Whether a run is going, its error, the last 12 steps. |
| `list_leads` | The people found, best first, with the strongest evidence for each. |
| `get_lead` | One lead in full: every post, the draft, the contact, why it is held. |
| `customer_profile` | Who Overheard decided to look for, and whether the method fits. |
| `trust` | The autonomy level and which gates block it. |

Approving, rejecting, autopilot, credits and sending are deliberately not exposed: an agent connecting here is an automated caller, and those are the founder's decisions or spend money. Connect Claude Code to the live copy:

```bash
claude mcp add --transport http earshot https://earshot-production.up.railway.app/mcp
```

## Quick start

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
cp .env.example .env        # then fill in .env
.venv/bin/uvicorn app.main:app --port 8765
```

Open <http://localhost:8765/>. A fresh checkout has no leads and no data: the `data/` folder is created at start and is not committed. Enter your website on the arrival screen (or open "Describe it yourself instead" and type a paragraph), then start the run. I have not timed a run precisely; expect a few minutes.

The minimum for a lead run from a typed description is `ANTHROPIC_API_KEY`, `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY`, and GitHub access (`GITHUB_TOKEN`, or the `gh` CLI logged in). Reading a website at intake also needs `TAVILY_API_KEY`. Every other service is optional.

## Environment variables

These are all the variables the code reads. `.env` is loaded by `app/main.py` at start. "Works without" says what the app does when the variable is missing.

| Variable | What it is for | Works without it? |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Read by the Anthropic SDK. Planner, Qualifier and Writer. | The app starts, but a run fails with an error shown in the UI. |
| `LLM_MODEL` | Model for every Claude call. Default `claude-sonnet-5-5`. | Yes. Leave it unset; do not set it empty. |
| `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY` | Moss search: matches issue text to pain statements by meaning. | No for GitHub discovery. The run fails once it has issues to match. |
| `GITHUB_TOKEN` | GitHub API calls for issues, repos and profiles. The run falls back to the output of `gh auth token`; repository intake uses only this variable and otherwise calls GitHub unauthenticated. | Locally, yes, if `gh` is logged in. On a server without `gh`, set it (it is set on the Railway copy). With neither, the code sends an empty bearer token; I did not test what GitHub does with that. |
| `TAVILY_API_KEY` | Reading your website at intake, the second Scout (forums and review sites), and the company website lookup for enrichment. | Yes. Web voices and domain lookup are skipped, and the step log says so. Intake from a website fails with "no page reader is configured"; intake from a GitHub repository and a typed description still work. |
| `HUNTER_API_KEY` | Email finder and verifier. | Yes. No lead gets an email, and the default policy holds every lead that has no verified address. |
| `SUBQ_API_KEY` | The second model that checks claims in each draft (SubQ Snap). | The app runs, but drafts with a claim about the recipient are marked "unchecked", which counts as a self-check failure, so autopilot cannot be earned. |
| `FLEXPRICE_API_KEY`, `FLEXPRICE_CUSTOMER_ID`, `FLEXPRICE_WALLET_ID` | Flexprice metering and the credit wallet. All three are needed. | Yes. Without all three, a local wallet is used and labelled "Local wallet". |
| `FLEXPRICE_BASE_URL` | Flexprice API base. Default `https://us.api.flexprice.io/v1`. | Yes. |
| `LOCAL_CREDITS` | Starting balance of the local wallet. Default 60. | Yes. |
| `RESEND_API_KEY` | Sending through Resend. | Yes. Approving records the decision and the activity log says "not sent (no RESEND_API_KEY)". |
| `DEMO_INBOX` | Where redirected messages go. Default `delivered@resend.dev`, Resend's test address. | Yes. |
| `MAIL_FROM` | Sender on Resend messages. Default `Overheard <onboarding@resend.dev>`. | Yes. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth client, so the founder can send through their own Gmail (`gmail.send` scope only). | Yes. The Connect Gmail button is replaced by a hint. |
| `GOOGLE_REDIRECT_URI` | OAuth callback. Default `http://localhost:8765/api/gmail/callback`. Set it to the public URL when deployed, and register the same URL in Google. | Yes, for local use. |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Spoken replies from `/api/speak`, which the interface no longer calls. | Yes. `/api/speak` returns 503. |
| `MAX_RUNS_PER_HOUR` | Run budget: most runs that may start in any rolling hour, web and MCP together. Default 6. | Yes. |
| `MIN_RUN_GAP_SECONDS` | Run budget: least time between two run starts. Default 20. | Yes. |
| `GRAPH_PATH` | Path of the embedded graph. Default `data/graph.kuzu`. | Yes. Leave it unset; do not set it empty. |

`PORT` is not read by the code. The Railway start command passes it to uvicorn.

## Tests

```bash
uv pip install pytest
.venv/bin/python -m pytest -q
```

Current result: 397 passed in about 2 seconds (the count moves as tests are added). The tests use injected fakes and need no keys or network. They cover scoring, policy, trust gates, the checks, the reviewer and its repair step, enrichment, billing (including the pending-charge logic), Gmail and Resend sending, intake, web discovery, voice actions, lessons, the simulation harness, the MCP tool list and the run budget. The intake tests call the API in-process. Nothing drives the browser.

## The simulation

The simulation runs the whole lead pipeline on ten product descriptions, with contact lookup and the credit gate switched off. It judges the top six leads of each case for relevance with a separate prompt that never sees the score, asks a model to play the recipient of each draft, and records recurring failures in `data/lessons.jsonl`. It writes `data/sim/latest.json`, which the trust gate named "Simulation finds relevant leads" reads.

```bash
set -a; . ./.env; set +a        # app.simulate does not load .env itself
GRAPH_PATH=data/sim-graph.kuzu .venv/bin/python -m app.simulate
```

Options: `--products flexprice,vectordb` (default all ten), `--founders detailed,one_liner,jargon,wrong_audience` (default `detailed`), `--sample 6`, `--workers 3`, `--out data/sim/latest.json`. Use a separate `GRAPH_PATH` if the server is running: the embedded graph allows one process at a time, and a second process fails with "Could not set lock on file" (I checked this with Kuzu 0.11.3). The code notes that the Moss free plan holds three indexes, so avoid running the simulation during a live run.

How to read the scorecard:

- A case is **works** with 5 or more leads and at least 60% judged relevant, **thin** with 1 to 4 leads, or 5 or more with at least 30% relevant, and **fails** otherwise.
- Some products are meant to fail. Four of the ten (a payroll product, a habit app, a window cleaner, a vague description) have no buyers in public issue trackers. Stopping early on them is the right outcome, and the scorecard lists a case as a "surprise" only when the verdict differs from what was expected.
- "Interested" and "annoyed" are a model's guesses at how the recipient would reply. They are not real replies.

Two simulation runs, 24 November 2026, same ten products, `detailed` founder only, six leads judged per case:

| | Run 1 (before) | Run 2 (after) |
| --- | --- | --- |
| Cases works / thin / fails | 2 / 2 / 6 | 2 / 1 / 7 |
| Average leads per case | 16.7 | 2.2 |
| Leads judged relevant | 14 of 40 (35%) | 13 of 14 (93%) |
| Simulated replies "interested" | 6 of 40 (15%) | 0 of 14 |
| Simulated replies "annoyed" | 10 of 40 (25%) | 4 of 14 (29%) |
| Open-source dev tools, average leads | 24.6 | 4.4 |
| Open-source dev tools, relevant | 48% | 93% |
| Products with no public buyers that still returned leads | 2 of 4, plus 13 leads for the closed-source API monitor | 0 |
| Products stopped at intake with a stated reason | 0 | 4 of 4 |

Between the runs, per the decision log, two changes were made: the Planner stops at intake when the method cannot work (`tracker_fit`), and the Qualifier became stricter and drops people it rates under 40.

What this shows and does not show. Relevance rose from 35% to 93% and the four products with no public buyers are now refused with a reason. But the volume fell by 87%, two of the five developer-tool products (feature flags, logging) went from about 25 leads to none, and I have not found out why. The number of cases that work did not change, the judged sample in run 2 is only 14 leads, and the judge is the same model family as the Writer. For the Flexprice description, the 13 known customers used as a check were found 0 times in the top 20 in both runs; leads are individuals who rarely list a company, and that score was dropped as a headline metric.

Real runs on flexprice.io through the live interface, 24 November 2026, after the Planner started choosing where to listen: 463 issues across 3 trackers plus 7 to 8 forum posts, 39 to 43 people describing a target pain, and 6 to 9 leads kept. The simulation table above was not re-run after that change.

## Flexprice setup

Flexprice meters three events: `lead.enriched` (2 credits), `outreach.sent` (1) and `graph.query` (0.1). In the Flexprice dashboard, create a customer with an external id (the script defaults to `earshot-demo`) and a prepaid wallet. Then:

```bash
FLEXPRICE_API_KEY=... FLEXPRICE_CUSTOMER_ID=earshot-demo .venv/bin/python scripts/flexprice_setup.py
```

The script is idempotent. It finds or creates a plan (`earshot-credits`), a metered feature with a COUNT meter for each event, a usage price on the plan for each meter (2, 1 and 0.1 USD), and a subscription of the customer to the plan. Without the subscription the wallet balance does not move. Then set `FLEXPRICE_API_KEY`, `FLEXPRICE_CUSTOMER_ID` and `FLEXPRICE_WALLET_ID` in `.env`. The code treats the wallet balance as credits, so a wallet in USD is assumed. The Activity section shows the balance, each metered event and the cost per lead.

I did not run the script again while writing this document. The log records that the wallet drew down after the plan and subscription existed.

## Band

What was actually done is recorded in [docs/band-run.md](docs/band-run.md). Four Band-hosted agents (Planner, Builder, Reviewer, Security) planned, wrote and reviewed one real change: a web lead with no named author is never released. Every message was sent in read-only plan mode, so the agents could read files but edited nothing and ran no commands. An operator session (a Claude Code session) relayed the messages through the Band CLI and applied the Builder's diff with `git apply`. No permission prompt was approved by automation; the one prompt that appeared was cancelled by stopping the chat. The resulting rule is in `app/policy.py`.

`scripts/band/demo.sh` is the earlier setup script for the same four roles with a human Yes or No at each handoff. It was set up and smoke-tested, but a full handoff between agents through it was not observed. Read [docs/band.md](docs/band.md) before relying on it.

## Deploy on Railway

The live copy runs on Railway at <https://earshot-production.up.railway.app>, with `GITHUB_TOKEN` set there. The repo has a `Procfile`, a `railway.json` and a `.python-version` (3.12). Both start files run `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Keep it at one instance with one uvicorn process: run state, the credit ledger and Gmail tokens live in process memory, and the graph file allows one process.

The graph (`data/graph.kuzu`) and the other state files (`data/autopilot.json`, `data/icp.json`, `data/lessons.jsonl`) live on the container's disk. A redeploy clears them unless you mount a Railway volume at the app's `data/` folder (I have not checked its absolute path). Each run also wipes and rebuilds the graph. A new deployment has no `data/sim/latest.json`, so the simulation gate reads "not run yet" until the simulation is run there.

## Known limits

- **Nothing reaches a lead.** Approving a message, or the Sender releasing one, delivers it to your own Gmail (if connected) or to the demo inbox through Resend, with a line saying who it was written for. The lead's own address is never used as a recipient. There is no real outbound to prospects in this build.
- **No sign-in on the public copy.** Anyone who can reach the URL can start a run, approve, reject and top up local credits. The one mitigation is the run budget: at most `MAX_RUNS_PER_HOUR` (6) starts in a rolling hour and `MIN_RUN_GAP_SECONDS` (20) between them, enforced in the one function the web route and the MCP tool both use. It limits spend. It is not authentication, and the budget lives in memory, so a restart resets it.
- **Railway storage is ephemeral.** A redeploy clears the graph, the autopilot state, the lessons and the customer profile. Results shown to a judge come from a run made on that deployment.
- **Forum authors usually cannot be identified.** Only Reddit user URLs and X status URLs yield a handle. Every other web lead has no named author, so it is held in every mode and is evidence only: there is nobody to write to. Web leads also get no contact lookup.
- **The method declines some products.** If a product's buyers do not write about problems in public, Overheard says so at intake and stops. In the simulation, four of ten products (a payroll product, a habit app, a window cleaner, a vague description) are refused for this reason, which is the intended result. Two developer-tool products (feature flags, logging) returned nothing after the stricter filter, and I have not found out why.
- **The demo video's progress screen is a replay.** It replays the log of a real run. It is not a live run recorded in one take.
- **Gmail sending is coded but not finished.** The Google console setup was not completed, so the sign-in was never run against Google. Resend to a test inbox is what actually runs. Gmail is tested only against faked HTTP, and its tokens live in memory.
- **People, not companies, and email only.** Leads are individuals from public posts. Most list no company, so few get a business email. LinkedIn URLs come from Hunter and are shown, but there is no LinkedIn outreach.
- **Departures from the organizers' spec.** No chat intake (a form that takes a website, a repository or a typed description), no multi-hop graph queries or warm-introduction paths, no continuous signal ingestion (the graph is rebuilt per run), no split-test analytics, no competitor pricing extraction, no Snyk scanning, no company-level discovery from filings or job posts.
- **Stages after Contacted are manual and have no screen.** The stage route works, but the pipeline board was deleted, and nothing reads replies.
- **Accepted expansion segments change nothing.** The route saves the choice and discovery does not use it; the interface no longer offers it.
- **Billing covers part of the work.** Only `lead.enriched`, `outreach.sent` (recorded only when mail actually left) and `graph.query` (recorded per lead) are metered. Language-model calls and scouting are not metered or gated.
- **Shadow and supervised behave the same.** Neither releases anything.
- **The trust gates read small evidence.** The simulation gate counts only product kinds that produced usable leads, so run 2 passes it at 93% on the open-source developer tools alone. A fresh deployment has no human decisions, so the agreement gate cannot pass until you have made eight judged ones.
- **The lessons ledger has stale entries.** Four "no public tracker ecosystem" lessons are still open, although the intake check now refuses those products on purpose. Marking a lesson fixed is done by calling `lessons.mark_fixed` from Python.
- **Claims are checked only where the draft talks about the recipient.** A sentence with no "you", name or company is not sent to the second model. A draft the Reviewer fails gets one rewrite and one re-review; if that still fails, the lead is held for you. Sentences that state a number the person never wrote are cut by code before the review.
- **Prompt injection.** Issue, post and website text goes into the Planner and Qualifier prompts without a defence beyond the claim check and your approval.
- **Website intake was tested on few real sites.** It reads the home page, `/pricing`, `/docs` and `/about` through Tavily's extractor, keeps at most 12,000 characters, and the Planner works from that text. A site that blocks the extractor, or says little, gives a poor profile.
- **Voice code is unused.** `app/voice.py` and its two routes remain on the server and are tested, but the interface no longer has a voice control.

## Where each judging row lives

| Row | Where in the product |
| --- | --- |
| ICP and discovery quality (20) | The Planner builds the profile (Customer section) from a website, a repository or a typed description (`app/intake.py`), and chooses where to listen. Leads come from public issues and posts, each with its URL, date and matched pain (People section). `tracker_fit` refuses products the method cannot serve. Ten-product simulation. Code: `app/pipeline.py`, `app/scout_web.py`. |
| Enrichment and outreach (20) | Tavily and Hunter resolve a domain and a verified email, and the status is shown on each lead (`app/enrich.py`). The draft cites the person's own words. Rule checks (`app/checks.py`) and a second model's claim check (`app/reviewer.py`) run before you see it. You approve, edit or reject; sending is redirected (`app/mailer.py`, `app/gmail.py`). |
| Dashboard and lead management (15) | People section: ranked leads, tiers, evidence, one question card to decide. Activity section: audit events, self-check, autonomy gates, credit ledger. The five-stage pipeline board was removed; stage data is still stored. |
| Startup viability (15) | Live runs on flexprice.io (463 issues across 3 trackers plus 7 to 8 forum posts, 39 to 43 people describing a target pain, 6 to 9 leads kept), and the simulation, which says plainly where the method fits (open-source developer tools) and where it does not. There are no customers or revenue yet. |
| Technical execution and demo (10) | Modular `app/` (one file per concern, pure decision functions with injected services), about 400 tests, a simulation harness, an MCP server, a run budget on the public copy, [docs/architecture.md](docs/architecture.md). The demo video is `demo/earshot-demo.mp4`. |
| Band Desktop bonus (+20) | [docs/band-run.md](docs/band-run.md): four Band-hosted agents planned, built and reviewed one real change, relayed through the Band CLI. See Band above for exactly what that does and does not show. |
| Flexprice bonus (+20) | `app/billing.py` and `scripts/flexprice_setup.py`: usage events sent to Flexprice, a priced plan and subscription so the wallet draws down, a credit gate before enrichment, approval and release, a cost per lead, and logic for the measured 0.2 to 15 second drawdown delay. |
