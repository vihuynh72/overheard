# Earshot

Earshot is a line of seven agents that finds people describing a problem in public, drafts a message that answers what they wrote, and holds it for the founder's approval. It is for a founder at a small or mid-sized company who sells to developers and has no list of target accounts. Every lead links to the post the person wrote, and in this build no message ever reaches a lead.

Built for HackwithBay 4.0 (San Francisco, 24 November 2026). Design document: [docs/architecture.md](docs/architecture.md). Decision history with reasons: [docs/log.md](docs/log.md). Band notes: [docs/band.md](docs/band.md).

## The idea

Most outbound tools start from a list of companies and then invent a reason to write. Earshot starts from a person's own public words about a problem. It reads public GitHub issues on your product's tracker and on your open-source competitors' trackers, and (with a Tavily key) forum and review-site posts. It matches them by meaning to pain statements it inferred from your product description, keeps the author, and quotes the post next to the draft.

Autonomy is earned from evidence, not toggled. The Sender can release a message without a per-message click only when five gates pass: a clean self-check, at least 90% agreement with at least 8 of your own approve and reject decisions, no release you would have stopped, a simulation that finds relevant leads, and no fixed mistake that came back. If an enforced gate fails, autopilot is switched off by code. See [docs/architecture.md](docs/architecture.md#5-trust-model).

## What you see in the app

The landing page is `/`. The workbench is `/app`, with six views.

- **Floor.** The seven agents drawn as creatures at their workstations, and the line between them drawn as a track schematic. Below it: the trust ladder (shadow, supervised, autopilot) with each gate, what passed and what did not; an inbox of leads held for you, each with its reasons; the lessons ledger; and the simulation results.
- **Leads.** The intake form (a website address or GitHub repository, or a description you type) and, after a run, a ranked list. Choose a person to see what they wrote (linked, with the matched pain and match score), why they were kept, their contact lookup steps and email status, and a draft you can edit, approve or reject. A rejection reason can become a standing rule.
- **Map.** Pains, the people who voiced them, their companies, and where they wrote, as four columns.
- **Pipeline.** A board with five stages: Matched, Contacted, Replied, Meeting Booked, Closed/Lost. Each card says whether the agent or a rep moved it last. A table shows leads per stage by tier, and the approval rate.
- **Profile.** The intake form again, with the pages the description was read from, and the inferred customer profile: industries, company size, personas and triggers with confidence per field, pains, negative signals, competitors, and suggested adjacent segments that you can accept or dismiss.
- **Activity.** The last run's steps, self-check findings, the sending setup (Gmail or Resend), and the credit balance with a per-event ledger.

Two more things run across all views.

- **The AI cursor.** A second, visibly machine-owned cursor that moves around the real interface and clicks real elements. A denylist in the page blocks it from pressing anything that approves, rejects, spends credits, moves a stage, starts a run, or changes the trust controls. Any human input pauses it. Turn it off with its toggle.
- **Voice.** Hold the microphone button (or click it) and speak. Browser speech recognition turns your words into text, a Claude call turns the text into one of nine allowed actions (run, show a view, open a lead, approve, reject, set policy, set autonomy level, explain, none), and the page carries it out through the same routes as a click. Spoken replies need ElevenLabs keys; without them replies are text.

## Quick start

You need Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
cp .env.example .env        # then fill in .env
.venv/bin/uvicorn app.main:app --port 8765
```

Open <http://localhost:8765/>. A fresh checkout has no leads and no data: the `data/` folder is created at start and is not committed. Enter your website or GitHub repository on the Leads view (or the Profile view), or open "Describe it yourself instead" and type a paragraph, then choose Find leads. The interface says a run takes about two minutes; I did not time it.

The minimum for a lead run from a typed description is `ANTHROPIC_API_KEY`, `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY`, and GitHub access (`GITHUB_TOKEN`, or the `gh` CLI logged in). Reading a website at intake also needs `TAVILY_API_KEY`. Every other service is optional.

## Environment variables

These are all the variables the code reads. `.env` is loaded by `app/main.py` at start. "Works without" says what the app does when the variable is missing.

| Variable | What it is for | Works without it? |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Read by the Anthropic SDK. Planner, Qualifier and Writer, and the voice interpreter. | The app starts, but a run fails with an error shown in the UI. Voice replies "could not reach the model". |
| `LLM_MODEL` | Model for every Claude call. Default `claude-sonnet-5-5`. | Yes. Leave it unset; do not set it empty. |
| `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY` | Moss search: matches issue text to pain statements by meaning. | No for GitHub discovery. The run fails once it has issues to match. |
| `GITHUB_TOKEN` | GitHub API calls for issues, repos and profiles. The run falls back to the output of `gh auth token`; repository intake uses only this variable and otherwise calls GitHub unauthenticated. | Locally, yes, if `gh` is logged in. On a server without `gh`, set it. With neither, the code sends an empty bearer token; I did not test what GitHub does with that. |
| `TAVILY_API_KEY` | Reading your website at intake, the second Scout (forums and review sites), and the company website lookup for enrichment. | Yes. Web voices and domain lookup are skipped, and the step log says so. Intake from a website fails with "no page reader is configured"; intake from a GitHub repository and a typed description still work. |
| `HUNTER_API_KEY` | Email finder and verifier. | Yes. No lead gets an email, and the default policy holds every lead that has no verified address. |
| `SUBQ_API_KEY` | The second model that checks claims in each draft (SubQ Snap). | The app runs, but drafts with a claim about the recipient are marked "unchecked", which counts as a self-check failure, so autopilot cannot be earned. |
| `FLEXPRICE_API_KEY`, `FLEXPRICE_CUSTOMER_ID`, `FLEXPRICE_WALLET_ID` | Flexprice metering and the credit wallet. All three are needed. | Yes. Without all three, a local wallet is used and labelled "Local wallet". |
| `FLEXPRICE_BASE_URL` | Flexprice API base. Default `https://us.api.flexprice.io/v1`. | Yes. |
| `LOCAL_CREDITS` | Starting balance of the local wallet. Default 60. | Yes. |
| `RESEND_API_KEY` | Sending through Resend. | Yes. Approving records the decision and the activity log says "not sent (no RESEND_API_KEY)". |
| `DEMO_INBOX` | Where redirected messages go. Default `delivered@resend.dev`, Resend's test address. | Yes. |
| `MAIL_FROM` | Sender on Resend messages. Default `Earshot <onboarding@resend.dev>`. | Yes. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Google OAuth client, so the founder can send through their own Gmail (`gmail.send` scope only). | Yes. The Connect Gmail button is replaced by a hint. |
| `GOOGLE_REDIRECT_URI` | OAuth callback. Default `http://localhost:8765/api/gmail/callback`. Set it to the public URL when deployed, and register the same URL in Google. | Yes, for local use. |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Spoken replies. | Yes. `/api/speak` returns 503 and the page shows the reply as text. |
| `GRAPH_PATH` | Path of the embedded graph. Default `data/graph.kuzu`. | Yes. Leave it unset; do not set it empty. |

`PORT` is not read by the code. The Railway start command passes it to uvicorn.

## Tests

```bash
uv pip install pytest
.venv/bin/python -m pytest -q
```

Current result: 336 passed in about 2 seconds. The tests use injected fakes and need no keys or network. They cover scoring, policy, trust gates, the checks, the reviewer, enrichment, billing (including the pending-charge logic), Gmail and Resend sending, intake, web discovery, voice actions, lessons and the simulation harness. The intake tests call the API in-process. Nothing drives the browser.

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

Two real runs, 24 November 2026, same ten products, `detailed` founder only, six leads judged per case:

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

## Flexprice setup

Flexprice meters three events: `lead.enriched` (2 credits), `outreach.sent` (1) and `graph.query` (0.1). In the Flexprice dashboard, create a customer with an external id (the script defaults to `earshot-demo`) and a prepaid wallet. Then:

```bash
FLEXPRICE_API_KEY=... FLEXPRICE_CUSTOMER_ID=earshot-demo .venv/bin/python scripts/flexprice_setup.py
```

The script is idempotent. It finds or creates a plan (`earshot-credits`), a metered feature with a COUNT meter for each event, a usage price on the plan for each meter (2, 1 and 0.1 USD), and a subscription of the customer to the plan. Without the subscription the wallet balance does not move. Then set `FLEXPRICE_API_KEY`, `FLEXPRICE_CUSTOMER_ID` and `FLEXPRICE_WALLET_ID` in `.env`. The code treats the wallet balance as credits, so a wallet in USD is assumed. The Activity view shows the balance, each metered event and the cost per lead.

I did not run the script again while writing this document. The log records that the wallet drew down after the plan and subscription existed.

## Band demo

`scripts/band/demo.sh` sets up four role agents (Planner, Builder, Reviewer, Security) in one Band worktree. They hand work to each other with `band chats send`, and Band's permission prompt makes the human approve each handoff. The task is a real Earshot rule that is not in the code yet: a web lead with no named author is never released.

```bash
scripts/band/demo.sh --dry-run   # print every command, run nothing
scripts/band/demo.sh             # set up, then send the Planner its kickoff once
scripts/band/demo.sh watch       # stream the four chats, with a line at each human gate
```

It needs the Band desktop app running, `jq`, and the app code committed to `main`. The Band version installed here (0.70) has no rooms and no @mentions. A handoff is a shell command that names the receiving chat. The human decision is Band's own Yes or No permission prompt. Setup and the first smoke test were run; a full handoff between agents was not. Read [docs/band.md](docs/band.md) before relying on it.

## Deploy on Railway

The repo has a `Procfile`, a `railway.json` and a `.python-version` (3.12). Both start files run `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Set the variables above in the Railway service. Keep it at one instance with one uvicorn process: run state, the credit ledger and Gmail tokens live in process memory, and the graph file allows one process.

The graph (`data/graph.kuzu`) and the other state files (`data/autopilot.json`, `data/icp.json`, `data/lessons.jsonl`) live on the container's disk. They are rebuilt by a run and are lost on a redeploy unless you mount a Railway volume at the deployed app's `data/` folder (I have not checked its absolute path). Each run also wipes and rebuilds the graph. A new deployment also has no `data/sim/latest.json`, so the simulation gate reads "not run yet" until you run the simulation there. I have not deployed this build to Railway; the two Railway files are unverified.

## Known limits

- **Nothing reaches a lead.** Approving a message, or the Sender releasing one, delivers it to your own Gmail (if connected) or to the demo inbox through Resend, with a line saying who it was written for. The lead's own address is never used as a recipient. There is no real outbound to prospects in this build.
- **Band.** The seven agents inside Earshot are functions in one Python process. They are not Band agents. The Band demo is a separate script. It has not been run end to end, and Band 0.70 has no @mentions or rooms. The demo's example rule is not implemented in `app/policy.py`. Band's token display was not seen by eye, and no dollar cost appears in its output.
- **No login.** Anyone who can reach the server can approve, reject, change policy and top up local credits.
- **People, not companies, and email only.** Leads are individuals from public posts. Most list no company, so few get a business email. Web leads get no contact lookup, so under the default policy the Sender never releases them. LinkedIn URLs come from Hunter and are shown, but there is no LinkedIn outreach.
- **Departures from the organizers' spec.** No chat intake (a form that takes a website, a repository or a typed description), no multi-hop graph queries or warm-introduction paths, no continuous signal ingestion (the graph is rebuilt per run), no split-test analytics, no competitor pricing extraction, no Snyk scanning, no company-level discovery from filings or job posts.
- **Stages after Contacted are manual.** Replied and Meeting Booked are set by a rep in the Pipeline view. Nothing reads replies.
- **Accepted expansion segments change nothing yet.** You can accept or dismiss a suggested adjacent segment, and the choice is saved, but discovery does not use it.
- **`graph.query` is defined and priced but never recorded.** Only `lead.enriched` and `outreach.sent` are metered by the app. Language-model calls and scouting are not metered or gated. The `outreach.sent` credit is recorded at approval even when no mail was sent.
- **Shadow and supervised behave the same.** Neither releases anything. The difference is only in how the Floor shows them.
- **The trust gates read small evidence.** The simulation gate counts only product kinds that produced usable leads, so run 2 passes it at 93% on the open-source developer tools alone. A fresh deployment has no human decisions, so the agreement gate cannot pass until you have made eight.
- **The lessons ledger has stale entries.** Four "no public tracker ecosystem" lessons are still open, although the intake check now refuses those products on purpose. Nothing in the app marks a lesson fixed; that is done by calling `lessons.mark_fixed` from Python.
- **Claims are checked only where the draft talks about the recipient.** A sentence with no "you", name or company is not sent to the second model. A failed claim holds the lead for you; it is not fed back to the Writer.
- **Prompt injection.** Issue, post and website text goes into the Planner and Qualifier prompts without a defence beyond the claim check and your approval.
- **Website intake is untested against real sites by me.** It reads the home page, `/pricing`, `/docs` and `/about` through Tavily's extractor, keeps at most 12,000 characters, and the Planner works from that text. A site that blocks the extractor, or says little, gives a poor profile.
- **The AI cursor's denylist is in the page.** It stops the cursor, not a person or script calling the API.
- **Gmail** is tested only against faked HTTP in the unit tests. I did not run the Google sign-in. Tokens are kept in memory and are lost on restart.
- **The landing page** (`static/landing.html`) says "The demo sends nothing at all". Approving does send to the demo inbox, as described above.

## Where each judging row lives

| Row | Where in the product |
| --- | --- |
| ICP and discovery quality (20) | Planner builds the profile with a confidence per field, pains, negative signals, competitors and suggested adjacent segments (Profile view), read from a website, a repository or a typed description (`app/intake.py`). Leads come from public issues and posts, each with its URL, date and matched pain (Leads view, Map view). `tracker_fit` refuses products the method cannot serve. Ten-product simulation. Code: `app/pipeline.py`, `app/scout_web.py`. |
| Enrichment and outreach (20) | Tavily and Hunter resolve a domain and a verified email, and the status is shown on each lead (`app/enrich.py`). The draft cites the person's own words. Rule checks (`app/checks.py`) and a second model's claim check (`app/reviewer.py`) run before you see it. You approve, edit or reject; sending is redirected (`app/mailer.py`, `app/gmail.py`). |
| Dashboard and lead management (15) | Pipeline view: five stages, "moved by agent or rep" on every card, conversion by tier, approval rate. Activity view: audit events, self-check, credit ledger. Floor view: trust gates and the inbox. |
| Startup viability (15) | One live run on Flexprice (463 issues read, 69 matched a pain, 25 leads scored and drafted, per the decision log), and the simulation, which says plainly where the method fits (open-source developer tools) and where it does not. There are no customers or revenue yet. |
| Technical execution and demo (10) | Modular `app/` (one file per concern, pure decision functions with injected services), 336 tests, a simulation harness, [docs/architecture.md](docs/architecture.md). The demo video is not in this repo. |
| Band Desktop bonus (+20) | `scripts/band/demo.sh` and [docs/band.md](docs/band.md): four role agents, a human Yes or No at each handoff, token usage events. Partly tested; see Known limits. |
| Flexprice bonus (+20) | `app/billing.py` and `scripts/flexprice_setup.py`: usage events sent to Flexprice, a priced plan and subscription so the wallet draws down, a credit gate before enrichment, approval and release, a cost per lead, and logic for the measured 0.2 to 15 second drawdown delay. |
