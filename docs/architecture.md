# Overheard: system design and architecture

This document describes what the code does today. Where something is partial, untested or missing, it says so, and the last section collects those points. Setup is in the [README](../README.md). The reasons behind each decision are in [log.md](log.md).

## 1. Overview

Overheard takes a description of a product (typed, or read from a website or GitHub repository) and runs a line of seven agents: Planner, Scout, Qualifier, Enricher, Writer, Reviewer and Sender. The line ends in a drafted message with the person's own words as evidence. A human decides on each message, or, once five trust gates have been earned, the Sender releases messages that pass the sending policy. Messages are always redirected to the founder's own inbox or a demo inbox. No lead is ever emailed.

Code layout, one file per concern:

| File | Concern |
| --- | --- |
| `app/main.py` | HTTP API, the two HTML pages, and the run budget. No auth. |
| `app/mcp_server.py` | MCP server mounted at `/mcp`: six tools, none that decides or spends. |
| `app/intake.py` | Website or repository to product text. Pure functions, injectable readers. |
| `app/pipeline.py` | Planner, Scout (GitHub and Moss), Qualifier and Writer, Enricher call, check-and-rewrite loop, graph write. |
| `app/scout_web.py` | Second Scout: forum and review posts through Tavily. |
| `app/enrich.py` | Company domain (Tavily) and email find and verify (Hunter). |
| `app/scoring.py`, `app/checks.py` | The score formula and tiers; the per-lead rule checks. |
| `app/reviewer.py` | Claim check with a second model. |
| `app/policy.py`, `app/trust.py` | What may be released; which autonomy level has been earned. |
| `app/autopilot.py` | State behind the autonomy gates and the held-lead inbox, the Reviewer's records, and the Sender. |
| `app/billing.py` | Credit gate and metering, local wallet or Flexprice. |
| `app/mailer.py`, `app/gmail.py` | Redirected sending through Gmail or Resend. |
| `app/store.py` | Kuzu graph: schema and every read and write. |
| `app/simulate.py`, `app/lessons.py` | Regression harness and the ledger of mistakes. |
| `app/voice.py` | Spoken words to one of nine allowed actions; spoken replies. Reachable through `/api/voice` and `/api/speak`, which the interface no longer calls. |
| `static/` | Plain HTML, CSS and JS with no build step: `index.html`, `app.js`, `app.css`, `ask.js`, `ask.css`, `landing.*`, `tokens.css`. Three sections (Customer, People, Activity). |

## 2. The agent line

```mermaid
flowchart TD
    H1(["Human touchpoint 1<br/>Founder describes the product<br/>and sets the sending policy"]):::human
    PLAN["Planner<br/>ICP, pain statements, competitors,<br/>channels, process areas, tracker fit"]
    STOP["Run stops at intake<br/>founder is told why"]
    SGH["Scout: GitHub issues<br/>matched to pains in Moss,<br/>then up to three learned pains"]
    SWEB["Scout: forum and review posts<br/>Tavily"]
    QW["Qualifier and Writer<br/>fit, reason, draft"]
    DROP["Dropped<br/>fit under 40, the seller's staff,<br/>or a seller's own post"]
    CREDIT{"Credit gate<br/>Flexprice wallet"}
    ENR["Enricher<br/>Tavily domain, Hunter email"]
    CHECK{"Self-check<br/>writing rules"}
    REWRITE["Rewrite once"]
    REPAIR["Rewrite once more from the evidence,<br/>review again"]
    REV["Reviewer<br/>second model checks each claim"]
    GATE{"Trust gates<br/>and sending policy"}
    HUMAN(["Human touchpoint 2<br/>Founder approves, edits or rejects"]):::human
    RULE["Standing rule<br/>from the rejection reason"]
    SEND["Sender<br/>Gmail or Resend<br/>redirected, never to the lead"]
    GRAPH[("Kuzu graph<br/>people, signals, events")]
    SIM["Simulation harness<br/>ten products"]
    LESS["Lessons ledger"]

    H1 --> PLAN
    PLAN -->|"tracker_fit is false"| STOP
    PLAN --> SGH
    PLAN --> SWEB
    SGH --> QW
    SWEB --> QW
    QW -->|"weak"| DROP
    QW --> CREDIT
    CREDIT -->|"allowed"| ENR
    CREDIT -->|"refused"| CHECK
    ENR --> CHECK
    CHECK -->|"rule broken"| REWRITE
    REWRITE --> REV
    CHECK -->|"clean"| REV
    REV -->|"claim fails"| REPAIR
    REPAIR --> GRAPH
    REV --> GRAPH
    GRAPH --> GATE
    GATE -->|"supervised, or anything unmet"| HUMAN
    GATE -->|"autopilot earned and policy releases"| SEND
    HUMAN -->|"approve, credit gate again"| SEND
    HUMAN -->|"reject with a reason"| RULE
    RULE -->|"applies to later leads"| GATE
    HUMAN -.->|"each decision is recorded as evidence"| GATE
    SEND --> GRAPH
    SIM --> LESS
    LESS -.->|"a regressed lesson blocks autopilot"| GATE

    classDef human fill:#f6e7b4,stroke:#8a6d00,color:#222
```

The two human touchpoints are the founder's input at the start (what you sell, and the sending policy) and the decision on each message. Touchpoint 2 is also where trust is earned: every decision is stored next to what the agent would have done, and that record feeds the agreement gate.

How a run is driven. `POST /api/run` starts one background thread and refuses a second run while one is in progress (HTTP 409). The MCP tool `find_leads` calls the same function, so both share the lock and the run budget. The thread writes progress lines to `pipeline.state`, which the page turns into a five-step checklist. After the run, `autopilot.after_run()` calls the Sender.

The run budget (`app/main.py`). The public copy has no sign-in, so the one function that starts runs keeps a deque of start times (`time.monotonic`). It refuses a start when fewer than `MIN_RUN_GAP_SECONDS` (default 20) have passed since the last one, or when `MAX_RUNS_PER_HOUR` (default 6) starts are already inside the last hour. The web route answers HTTP 429 with a sentence saying when to try again, which the page shows as the reason; the MCP tool returns `{"started": false, "reason": ...}`. A refused start spends no budget. The state is in memory, so a restart resets it. It limits spend; it does not identify anyone.

### Agents

| Agent | Input | Output | Service or model | Decides alone |
| --- | --- | --- | --- | --- |
| Planner | Product text (typed, or read by `intake.py` from a site through Tavily or a repository through the GitHub API) | ICP with a confidence per field, pain statements, negative signals, competitors with category and repository, adjacent segments, `channels` (four to six public places where this buyer writes, with a domain) and `process_areas` (three to five jobs the product touches), and `tracker_fit` | Claude (`claude-sonnet-5-5`, overridable with `LLM_MODEL`) with structured output; GitHub API to check that each named competitor repository exists | Whether the run stops at intake (`tracker_fit` false). Which competitor repositories to watch; made-up ones are dropped. Where the Scout listens (channels and process areas). It only suggests adjacent segments. |
| Scout | Pain statements, repositories, channels | Posts with author, URL, date, best-matching pain and match score | GitHub REST search, Moss; Tavily for forum and review sites | Which posts count as a match: Moss score of at least 0.3 for issues, Tavily score of at least 0.45 for web posts. Learns up to three further pain statements from the best real posts in one extra round. Drops sellers' own posts. Caps the list at 25 people, with up to 8 reserved for web voices. |
| Qualifier | One person's posts and GitHub profile, plus the ICP | `fit` 0 to 100, `production_user`, role, a one-sentence reason | Claude (same call as the Writer) and the GitHub users API | Drops people with fit under 40, and people whose company is the seller's own. |
| Enricher | Name and company | Domain, email, verification status, position, LinkedIn URL | Tavily, Hunter | Skips the paid lookup for weak leads without a public address, and when the credit gate refuses. |
| Writer | The Qualifier's evidence | Subject (under 8 words) and body (under 90 words) | The same Claude call as the Qualifier (`Qualification` in `pipeline.py`) | Rewrites its own draft once when a writing rule is broken. |
| Reviewer | A lead and its draft | Rule findings; per-sentence support probabilities; a verdict of pass, fail or unchecked | `checks.py` (code); SubQ Snap `subq-snap-1.2`, a different model from the Writer | Nothing is blocked outright. A finding holds the lead for the human. It cannot approve anything. Before the review, code cuts sentences about the recipient that state a number the evidence lacks (`reviewer.guard`). A failed draft is rewritten once and reviewed again (`reviewer.repair`, `MAX_REWRITES_PER_DRAFT = 1`). |
| Sender | Pending leads, policy, trust level, credit balance | A stage change and a redirected email | `policy.py`, `trust.py`, Flexprice gate, Gmail or Resend | Releases a message only when the level is autopilot, the policy says release and the credit gate allows it. Steps itself down when an enforced gate fails. A web lead with no named author is always held. |

In the code the Qualifier and the Writer are one model call.

## 3. Graph ontology

The graph is Kuzu, embedded, at `data/graph.kuzu` (`GRAPH_PATH` overrides). The schema is created at import in `app/store.py`:

```
CREATE NODE TABLE Person(login STRING PRIMARY KEY, name STRING, url STRING,
    company STRING, email STRING, blog STRING, bio STRING, location STRING, followers INT64,
    role STRING, fit INT64, production BOOLEAN, reason STRING, score INT64, tier STRING,
    stage STRING, stage_actor STRING, subject STRING, body STRING, draft_status STRING,
    email_status STRING, domain STRING, linkedin_url STRING, position STRING, enrich STRING, newest STRING)
CREATE NODE TABLE Company(name STRING PRIMARY KEY)
CREATE NODE TABLE Repo(name STRING PRIMARY KEY, kind STRING)     -- kind: product | competitor | web
CREATE NODE TABLE Signal(id STRING PRIMARY KEY, url STRING, title STRING,
    excerpt STRING, created STRING, pain STRING, match DOUBLE)
CREATE NODE TABLE Event(id STRING PRIMARY KEY, ts STRING, login STRING,
    actor STRING, action STRING, detail STRING)
CREATE REL TABLE WORKS_AT(FROM Person TO Company)
CREATE REL TABLE RAISED(FROM Person TO Signal)
CREATE REL TABLE ABOUT(FROM Signal TO Repo)
```

Meaning of the main properties:

- `Person.login` is the GitHub login, or `host/handle` for a web lead with a handle, or `web:<hash>` for one with no named author.
- `stage` is one of `Matched`, `Contacted`, `Replied`, `Meeting Booked`, `Closed/Lost`. `stage_actor` is `agent` or `rep` and records who moved it last. `draft_status` is `pending`, `approved` or `rejected`.
- `Signal` is one public post. `match` is the Moss score (or the Tavily score) against the pain in `pain`. Its `url` is the citation.
- `Event` is the audit log. `actor` is `agent` or `rep`; `login` points at a Person by value, not by an edge.

The ontology is small on purpose. Two things to know:

- `Company` nodes and `WORKS_AT` edges are written on every run, but no query reads them. The company shown in the app comes from `Person.company`.
- The graph is wiped (`MATCH (n) DETACH DELETE n`) and rebuilt at the end of each run. It does not accumulate across runs.

Queries the app runs, quoted from the code:

```cypher
-- store.leads(): every person, then each person's evidence two hops out
MATCH (p:Person) RETURN p
MATCH (p:Person)-[:RAISED]->(s:Signal)-[:ABOUT]->(r:Repo) RETURN p.login AS login, s, r.name AS repo

-- store.events(): the audit trail, newest first
MATCH (e:Event) RETURN e ORDER BY e.ts DESC LIMIT 200

-- main._lead(): the draft and tier the decision route acts on
MATCH (p:Person {login: $login}) RETURN p.subject AS subject, p.body AS body, p.tier AS tier

-- store.link(): how every edge is written, idempotently
MATCH (a:{a_label} {{{a_key}: $a}}), (b:{b_label} {{{b_key}: $b}}) MERGE (a)-[:{rel}]->(b)
```

`store.upsert` writes a node as `MERGE (n:Person {login: $login}) SET n.stage = $stage, ...`. All reads and writes go through one lock and one connection, because the API thread and the run thread share the database.

Query logic, stated plainly: traversal is one hop (`RAISED`) and two hops (`RAISED` then `ABOUT`). Ranking, filtering by tier and the held-lead inbox are computed in Python from the result of those queries. The graph is used as a store with provenance. The multi-hop reasoning in the organizers' spec (warm introductions, requisition-to-evaluation links, displacement paths) is not built.

## 4. Reasoning loops

Each loop has a written exit condition and a cap.

**Check, then rewrite once** (`pipeline.build_leads`). After drafting, `checks.check_leads` runs on every lead. For findings in the fixable set (`placeholder`, `long_body`, `long_subject`, `empty_draft`), the Writer is called again with its original evidence, the broken rules listed, and the instruction to keep its judgment of the lead and rewrite only the subject and body. Exit: one retry per lead, then stop. The rewrite is not re-checked inside this loop. The self-check that runs after the graph is written reports what is left, and a lead with a remaining finding is held for the human by `policy.decide`.

**Claim check by a second model** (`reviewer.review`). The body is split into sentences. Sentences about the recipient (a "you", their name or first name, or their company; greetings and questions excluded) are each sent, with the evidence (profile fields plus the full text of each post), to SubQ Snap as a yes/no question: is this sentence fully supported by the evidence, with nothing added? A sentence with a support probability under 0.5 is unsupported. A missing answer counts as 0, and so does NaN. Verdict: `fail` if any sentence is unsupported, `unchecked` if the judge raised (for example no `SUBQ_API_KEY`), otherwise `pass`. Exit: one review, one repair, one re-review per draft per run. A failed claim becomes a finding that holds the lead and shows in the Activity section. Two bounded repairs run around it. First, before the review, `reviewer.guard` deletes any sentence about the recipient that states a number, percentage, money amount or date that does not appear in the evidence; no model is involved, and a draft that would be left with fewer than two sentences is not touched. Second, `reviewer.repair` gives each failed draft one rewrite (`MAX_REWRITES_PER_DRAFT = 1`) from the evidence and the flagged sentences, reviews the rewrite, and keeps it only if the new review passes. If it does not, the original draft and verdict stand and the lead is held. The judge reads the full post text: a first version given a 300-character excerpt rejected 10 of 11 drafts (decision log).

**Rejection to rule** (`main.decide`, `policy.suggest_rule`). When you reject a lead and give a reason, the reason is matched against a short list of patterns: "agency", "consultan", "hobby", "student" or "personal project" produce a `hold` rule on the text of future leads; "competitor" or "works at" with a known company produces a `drop` rule on that company. A rule that duplicates an existing one is not added. Exit: no pattern matches, no rule; the reason is still stored in the audit log. Rules apply to leads still pending, in the held-lead inbox and in the Sender. They do not change scores or past decisions.

**Simulation to lessons** (`simulate.derive_lessons`, `lessons.add`). After a simulation, six kinds of failure are turned into lessons: a product kind where every case fails (`no_ecosystem`), under 50% relevant matches (`loose_matches`), a founder style that scores worse than the detailed one (`founder_degrades`), a check rule that fires on over 20% of leads (`check_rule`), over 25% annoyed simulated replies (`annoyed_replies`), and a crash (`pipeline_crash`). A lesson is keyed by kind and pattern, so a repeat increments `seen` and does not add a row. If a lesson marked `fixed` appears again it is reopened with `regressed: true`. Exit for the loop: a person fixes the cause and marks it fixed (`lessons.mark_fixed`, called from Python; there is no button). The trust gate "No fixed mistake came back" reads the regressed lessons.

## 5. Trust model

Autonomy is a level the system holds, not a switch the founder flips. The levels are `shadow`, `supervised` and `autopilot`. Founders request one; `trust.level()` grants it or refuses it and says which gates blocked it. A fresh install starts at `supervised`.

The gates (`app/trust.py`):

| Gate | Passes when | Layer |
| --- | --- | --- |
| Self-check is clean | No findings on any lead, including the Reviewer's | checked |
| Agent matches your decisions | At least 8 judged decisions exist, and at least 90% of the judged ones among the last 20 agreed. Only calls that could do harm are judged: an agreed call, or a release you rejected. A lead the agent held and you approved is reported ("held that you approved") but is not an error and does not count toward the 8 | checked |
| No release you would have stopped | In the last 20 decisions, no case where the agent would have released and you rejected | enforced |
| Simulation finds relevant leads | The case-weighted relevant share in `data/sim/latest.json` is at least 60%, over product kinds with at least one usable case | checked |
| No fixed mistake came back | No open lesson marked `regressed` | enforced |

How a level is granted. Autopilot is granted only when every gate passes. Otherwise the granted level is `supervised` and the answer lists the gates that blocked it. The Sender checks this each time it runs: after a run finishes and when the level is changed through `POST /api/autonomy`.

How a level is lost. If the requested level is autopilot and an enforced gate fails, `trust.demote` rewrites the requested level to `supervised` and the Sender reports why. If a checked gate fails, the granted level drops to `supervised` and nothing is released, but the request stays as autopilot and resumes when the gate passes again. Because the false-release window is the last 20 decisions, a bad release stops counting after 20 further decisions.

`shadow` and `supervised` behave the same in the server code: neither releases.

Ordering of protections. The ordering of protections used here, from enforced in code through checked every run to advised in prose, comes from Lauren Tan's talk "All Code Is Slop (Except Mine)". The Activity section shows the gates. What sits in each layer in this repository:

- **Enforced in code.**
  - The Sender returns before releasing anything unless the granted level is autopilot.
  - `policy.decide` holds a lead that fails the policy (minimum score, verified email, evidence age, banned phrases, daily limit, your rules). A `drop` rule removes the lead.
  - The credit gate refuses enrichment, approval (HTTP 402) and release when the balance is too low.
  - The mailer never uses the lead's address as a recipient.
  - Request bodies are validated (pydantic, `policy.validate`).
  - The MCP server at `/mcp` has no tool that approves, rejects, requests autopilot, adds credits or sends (a test pins the tool list at six).
  - The run budget (section 2) caps how often anyone can start a run on the public copy.
  - A web lead with no named author is held in every mode (`policy.decide`).
  - A credit for outreach is recorded only when mail actually left.
  - Two trust gates are enforced: no release you would have stopped, and no regressed lesson. Failing either stops autopilot.
- **Checked every run.** `checks.check_leads`, the Reviewer's claim check, and the simulation. They produce findings and gate values, and a person or the policy acts on them.
- **Advised.** The Qualifier and Writer prompts: no flattery, no invented facts, a short body, a clear ask. Prompts can be ignored by the model, so the rules that matter most are also checked (length and placeholders) or reviewed (claims).

Human approval is not removed by any of this. In supervised mode the policy always holds a message for you. The decision route lets you approve a message the Reviewer flagged; the flag is information, not a lock.

## 6. Scoring

`app/scoring.py`:

```
score = round((0.6 * fit + 40 * match) * recency) + (5 if email_status == "valid" else 0)
clamped to 0..100
tier: A if score >= 70, B if score >= 50, else C
```

- `fit` is the Qualifier's 0 to 100. `match` is the best Moss (or Tavily) score among the person's posts, 0 to 1.
- `recency` is 1.0 when the newest post is at most 365 days old, 0.6 when it is 1095 days old or more, and linear in between. A missing or unparseable date gets 0.6.
- A Hunter-verified email adds 5 points after the multiplier.

Examples with fit 80 and match 0.5: newest post from last June gives 68 (tier B); the same post two years old gives 54 (B); three years old gives 41 (C). Adding a verified email gives 73, 59 and 46. The decay exists because the first live run's top lead had evidence from 2022.

## 7. Discovery

**Intake.** The founder gives a website, a GitHub repository, or a typed paragraph. `intake.normalize` accepts only public hostnames (no IP addresses, no `localhost`, `.local` or `.internal`, no ports, no credentials in the address). For a repository, the description and README come from the GitHub API, and the homepage is also read if a Tavily key exists. For a site, Tavily's extractor reads the home page, `/pricing`, `/docs` and `/about`. The text is capped at 12,000 characters, split equally among the pages. At intake the server itself calls only `api.github.com`. Website fetching is done by Tavily.

**GitHub issues.** For the product's repository (if given) and each competitor repository the Planner named, `fetch_issues` takes up to three pages of 100 of the newest issues from the GitHub search API. It skips bots and anyone whose association is MEMBER, OWNER or COLLABORATOR, because maintainers are not leads. It strips issue-template scaffolding so that the text is the author's words, and keeps 1,500 characters.

**Matching by meaning in Moss.** All issues are indexed in one temporary Moss index (as `title` and `body`), and each pain statement is queried with `top_k=20`. A hit is kept when its score is at least `MIN_MATCH = 0.3`; the best pain per issue wins. The index is deleted when the run ends, because the free plan holds three. Matching by meaning, not keywords, is the point: pain statements are written the way an engineer would phrase a bug report, and people use different words. The 0.3 floor was chosen on the first 84 issues, where lower scores were noise (code comment); the spike on those 84 issues found real matches for 3 of 4 pain statements (decision log). Issues are grouped by author and the authors are ranked by their best match. In one extra round the Scout then reads the best-matching real posts and writes up to three new pain statements in the words those people used (`learn_pains`), and matches again with them.

**Forums and review sites (second Scout).** With a Tavily key, `scout_web.find_voices` searches the channel domains the Planner chose for this product (up to 8, cleaned by `clean_domains`). It builds up to 12 queries: each pain, plus the pain closest in words to each of the Planner's process areas. It keeps results with a Tavily score of at least 0.45 and at least 80 characters of content, drops vendor hosts, marketing paths and posts by the seller's own people (`drop_sellers`), and keeps one result per URL. An author is known only for Reddit user URLs and X status URLs (X system paths such as `/i/` are not authors); other posts have no named author and are keyed `web:<hash>`, and `policy.decide` always holds such a lead. No reason for 0.45 is recorded. Up to a third of the 25-lead cap (8) is reserved for these voices.

**Citations.** Every `Signal` carries its `url`, and `checks.check_leads` flags any lead with no signals or a signal whose URL is not `https://`. The UI links every excerpt to its source.

## 8. Enrichment

`enrich.enrich(name, company, known_email)`, which never raises and returns a list of the steps it took, shown on each lead:

1. If the GitHub profile has a public email, verify it with Hunter.
2. Otherwise, with a company: take the domain from the profile if it looks like one; else search Tavily for the official website, skipping social, directory and aggregator hosts; else ask Hunter by company name.
3. With a name, ask Hunter's email finder for an address, then take its verification status or ask the verifier. A pending answer is left pending (no retry).
4. Statuses are shown as Hunter reports them (`valid`, `accept_all`, `invalid`, `webmail`, `disposable`, `unknown`, `pending`). Only `valid` adds to the score and satisfies the default policy.

Web leads get no contact lookup. The credit gate runs before each lookup, and a tier C lead without a public email skips the paid search.

## 9. Billing and credit gating

Three events are metered: `lead.enriched` (2 credits), `outreach.sent` (1) and `graph.query` (0.1). The app records `lead.enriched` per enrichment, `outreach.sent` only when mail actually left, and `graph.query` once per lead.

`scripts/flexprice_setup.py` creates these Flexprice objects, and is safe to repeat: a plan `earshot-credits` ("Overheard Credits"); one metered feature per event, each with a COUNT meter that resets per billing period; one usage price per meter on the plan (2, 1 and 0.1 USD, flat fee, monthly, arrears); and a subscription of the customer to the plan. The customer and the prepaid wallet are made in the dashboard first. The log records why the subscription matters: the wallet balance did not move until usage was priced on a subscribed plan.

The gate (`billing.gate`) is where execution stops. Flexprice only records and prices. The gate refuses when the balance is below the event's cost ("Out of credits"), and refuses a tier C lead when the balance is under 15 credits. It runs:

- before each enrichment, strongest leads first, so a low balance pauses the weak ones;
- at approval, where a refusal returns HTTP 402;
- before each release by the Sender.

The pending-charge logic. Flexprice's real-time balance lags behind events. The delay was measured at 0.2 to 15 seconds. Without a correction, a burst of calls could all see the old balance and overspend. So each recorded event adds `[cost, time]` to a pending list. On each balance read the code computes how much the Flexprice balance fell since the last read and subtracts that from the oldest pending entries. Entries older than 30 seconds (about twice the slowest measurement) expire. The available balance is the fresh balance minus what is still pending. If the Flexprice read fails, the available balance is the last known balance minus pending, which is 0 when there has been no read, so the gate fails closed.

Cost per lead: each recorded event carries the lead, and the lead detail shows its total. The Activity section lists the ledger. The ledger and the local wallet reset at the start of each run. Without Flexprice keys a local wallet starts at 60 credits (`LOCAL_CREDITS`) and can be topped up from the Activity section.

## 10. Sending

`mailer.send` is the only place a message leaves the process, and it has two paths. The message is the one the agents wrote. Only the recipient is replaced, and a line is added saying who it was written for.

- **Gmail**, when the founder has connected it (OAuth, `gmail.send` scope only): the message goes to the connected address (or to `DEMO_INBOX` if the address could not be read). Tokens are held in memory and are never written to disk or logged. The OAuth state value is single-use.
- **Resend**, otherwise, with `RESEND_API_KEY`: the message goes to `DEMO_INBOX`, or Resend's test address `delivered@resend.dev`. If that address were the lead's own, the sink is used instead.
- With neither, the result is `skipped` and the decision is still recorded.

`mailer.send` never raises, and its error strings carry the exception type, never request details. The audit log says which path was used and that the message went to the founder or the demo inbox, not to the lead.

## 11. Simulation harness

`python -m app.simulate` runs ten product descriptions (Flexprice, plus nine fictional ones: feature flags, logging, a vector database, authentication, an API monitor, payroll, a habit app, window cleaning and a vague one). Each has an expected outcome (strong, weak or none) and, for Flexprice, a list of 13 known public customers. Founder styles (`detailed`, `one_liner`, `jargon`, `wrong_audience`) rewrite the description. Per case it records lead count, tiers, how many leads have a company, the check findings, the median match score and evidence age, and the verdict (works, thin, fails). A judge prompt that never sees the score rates the top six leads for relevance, and a second prompt plays the recipient and answers with one of five outcomes. Lessons are derived and written to the ledger (section 4).

The two simulation runs (24 November 2026, `detailed` founder, six leads judged per case; the table was not re-run after the Planner began choosing channels):

| | Run 1 | Run 2 |
| --- | --- | --- |
| Cases works / thin / fails | 2 / 2 / 6 | 2 / 1 / 7 |
| Average leads per case | 16.7 | 2.2 |
| Leads judged relevant | 14 of 40 (35%) | 13 of 14 (93%) |
| Simulated "interested" / "annoyed" replies | 6 / 10 of 40 | 0 / 4 of 14 |
| Products with no public buyers that returned leads | 2 of 4 (25 and 6 leads) | 0 of 4, all stopped at intake with a reason |
| Feature-flag and logging products, leads | 24 and 25 (1 of 5 and 0 of 5 relevant) | 0 and 0 |
| Flexprice, leads | 24 (4 of 5 relevant) | 4 (4 of 4 relevant) |

What the runs showed. Run 1 returned about 25 leads regardless of fit, including for a habit app and a vague description. That produced two changes: stop at intake when the method cannot work, and drop people the Qualifier rates under 40. Run 2 shows those changes working: relevance went from 35% to 93%, and the four products with no public buyers are refused with a plain reason. It also shows the cost: volume fell by 87%, the feature-flag and logging products now return nothing, and the number of working cases did not improve. The cause of the two zero results was not investigated. Samples are small (14 leads judged in run 2), one run per cell, and the relevance judge is a model from the same family as the Writer. Replies are simulated and are not evidence of real response rates. The check for rediscovering known customers found 0 of 13 in the top 20 in both runs; leads are individuals who seldom list a company, and the accuracy score built on it was dropped (decision log).

## 12. Security notes

- **No authentication.** The server has no login and no CORS rules. Anyone who can reach it can run, approve, reject, change policy and add local credits. The public deployment at <https://earshot-production.up.railway.app> is therefore protected only by the run budget (section 2), which caps spend but does not identify anyone. Sign-in is the first thing to fix before real users. The MCP server at `/mcp` is equally open, which is why it exposes no tool that decides or spends.
- **Keys only in the environment.** Keys are read at call time from environment variables. `.env` is git-ignored, and `.env.example` holds names only. Error handling in the integrations returns the exception type, not its text, because a library message can include a URL with a key (Hunter takes its key as a query parameter). The Gmail client secret and tokens are never returned or logged.
- **Untrusted text.** GitHub posts, web posts, website text and model output are treated as untrusted. In the page they are written with an `esc()` function, and links are limited to `http` and `https`. The Qualifier and Planner prompts have no such defence for post or site text; the claim check and the human decision are what stand between an injected instruction and a sent message, and in this build sending is redirected.
- **Intake.** The address is validated to a public hostname before anything is fetched, and the server fetches only the GitHub API itself.
- **What an agent can do through MCP.** `find_leads` starts a run (inside the run budget); the other five tools only read. Lead text is data written by strangers, and the server's instructions say so. No tool approves, rejects, requests autopilot, adds credits or sends mail.
- **Voice.** `voice.interpret` still limits a model to nine validated actions behind `/api/voice`, but no page calls it any more, so it is unused attack surface rather than a feature. It is kept, and tested, because deleting server code was out of scope.
- **Sending.** The lead's address is never a recipient (section 10).
- **Dependencies.** I found no dependency scan or CI configuration in the repository, so none has been run.

## 13. Known limits and what would come next

Limits:

- Nothing reaches a lead. This is deliberate for the demo.
- No sign-in on the public copy; the run budget limits spend only. Its state is in memory.
- Railway storage is ephemeral: a redeploy clears the graph, the autopilot state, the lessons and the profile unless a volume is mounted.
- Forum authors usually cannot be identified (only Reddit and X yield a handle), so those leads are evidence only and are always held. Web leads have no contact lookup.
- The method declines products whose buyers do not write in public; four of ten simulated products are refused for that reason. Feature-flag and logging products returned nothing after the stricter filter, and the cause was not investigated.
- Band: [band-run.md](band-run.md) records four Band-hosted agents that planned, built and reviewed one change in read-only plan mode, relayed by an operator session through the Band CLI. The operator applied the diff, and no permission prompt was approved by automation. The seven agents inside Overheard are functions in one process, not Band agents. `scripts/band/demo.sh` was smoke-tested but a full handoff through it was not observed ([band.md](band.md)).
- Gmail sending is coded and tested against faked HTTP, but the Google console setup was not finished, so Resend to a test inbox is what runs. Tokens are in memory.
- State is in one process: run log, credit ledger, Gmail tokens, run budget. Files in `data/` hold the graph, the policy and decisions, and the lessons. Run one instance.
- Accepted expansion segments are saved but do not change discovery, and the interface no longer offers them. The stage route, `/api/policy`, `/api/voice` and `/api/speak` have no screen.
- Language-model calls and scouting are not metered.
- Replies and meetings are set by hand through the stage route. Nothing reads replies.
- The Reviewer's repair is one rewrite per draft, and the number guard looks only at digit and currency patterns.
- Spec items not built: chat intake, LinkedIn outreach, split-test analytics, competitor pricing, multi-hop graph reasoning, continuous ingestion, Snyk.
- The demo video's progress screen replays the log of a real run.
- Untested by me: the Gmail OAuth round trip and website intake against many live sites.

What would come next, in order: authentication and a persistent volume; reply tracking so that stage movement and conversion are measured; wiring accepted expansion segments into discovery; diagnosing the zero-lead results for feature flags and logging; turning the lessons ledger into regression cases that run on every change; the graph queries the spec asks for, once there are enough people and companies in the graph to make them useful.
