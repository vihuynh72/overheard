# hackwithbay

## Project

- **What it is.** An entry for HackwithBay 4.0 (Devnovate, AWS Builder Loft SF, 2026-11-24): an AI GTM engine that takes a product description, infers the ICP, finds leads with source citations, drafts outreach, and requires human approval before sending. The spec is fixed by the organizers; the direction inside it is still being brainstormed.
- **Core flow that must work.** Product intake → inferred ICP → cited leads → knowledge graph → enriched contacts → drafted outreach → human approval gate → pipeline dashboard.
- **Scoring.** ICP and discovery 20, enrichment and outreach 20, dashboard 15, startup viability 15, tech and demo 10, Band Desktop bonus +20, Flexprice bonus +20.
- **Hard constraints.** Hacking 11:00–15:30 PT with lunch 12:00–13:00; submission due 15:30; top 5 present at 16:00. Deliverables: working deployment, public repo with setup docs, 2–3 minute demo video, system design document. The repo will be public, so secrets stay in `.env` (gitignored) and never go in code or docs.
- **Pain and user.** Outbound tools send irrelevant mail and miss the right person, because leads get filtered in or out wrongly. The user is a founder at a small or mid-sized business. The demo client is Flexprice.
- **Build shape.** Deep on one edge, thin on the rest of the spec; both the Band and Flexprice bonuses; solo builder.
- **Edge.** Leads come from public GitHub issues on the product's and its open-source competitors' repos, matched by meaning (Moss) to pain statements inferred from the product description. Every lead links to what the person wrote. Planned next: an ICP accuracy score from rediscovering hidden known buyers.
- **Stack.** Python 3.12, FastAPI (`app/main.py`), pipeline in `app/pipeline.py`, Kùzu embedded graph in `app/store.py`, Moss for search, Claude Sonnet 5.5 via the Anthropic SDK. The UI is `static/` (plain HTML, CSS, JS, no build step); design tokens live in `static/tokens.css` and every colour and font must come from them.
- **Run.** `uv venv --python 3.12 && uv pip install -r requirements.txt`, then `.venv/bin/uvicorn app.main:app --port 8765` with the variables from `.env.example` set.
- **Earlier research.** `/Users/vihuynh/Desktop/claude/docs/brainstorming/` (start with `INDEX.md` and `TOP-10.md`). The spec is at `/Users/vihuynh/Downloads/AI GTM Engine - Product & Technical Requirements Specification.md`.

## First principles of this product

Outbound fails for one reason: the sender does not know whether this person has this problem now. Everything else (lists, enrichment, sequences) is machinery around that missing fact. So the product is a machine for establishing that fact and acting on it, and every piece of work is judged against these five statements.

1. **Evidence before action.** A lead exists only because a person said something in public that shows the problem. No evidence link, no lead. No claim in a message without evidence behind it.
2. **The human gives a goal, not labour.** The founder supplies one input (their site) and then only answers questions the machine cannot settle. Any new field, button or setting the founder must operate is a defect unless the machine truly cannot infer it.
3. **Autonomy is earned and revocable.** The machine may act alone only where its past judgments matched the human's, its own checks are clean, and the simulation holds. One release the human would have stopped ends autopilot.
4. **Every mistake becomes a mechanism.** A correction is not finished until it lives in code: a check, a rule, a gate or a test. A line of prompt is the weakest fix and the last resort.
5. **Declining is a feature.** When the method cannot work for a product, or a lead is weak, the machine says so and stops. Volume is never the goal; relevant people are.

**How these are enforced, strongest first.** When you add or change behaviour, put the rule at the highest layer that can hold it, and add the test in the same change.

| Layer | What lives here | Where |
|---|---|---|
| Impossible by construction | No message is ever addressed to a lead in this build; the AI cursor cannot press anything that spends money or decides for the human; the Sender releases nothing unless policy, review and the credit gate all pass | `app/mailer.py`, `static/pilot.js` denylist, `app/autopilot.py` `run_sender` |
| Checked on every run | The twelve lead rules, the second-model claim check, the fit check at intake, the score floor | `app/checks.py`, `app/reviewer.py`, `app/pipeline.py` |
| Checked across runs | Ten product types simulated; failure patterns written to the lessons ledger; a fixed lesson that recurs is flagged | `app/simulate.py`, `app/lessons.py` |
| Earned | Trust gates decide the autonomy level | `app/trust.py` |
| Advised | Prompts and this file | last resort |

A worker's brief must name which of the five statements the work serves and which layer its rule belongs to. Work that serves none of them is not done.

## Three lenses

Hold these on every piece of work. They are questions to answer, not sections to write.

- **Project judgment.** Anything can be built now, so being buildable is worth nothing. Know what makes this product hard to copy and spend the effort there. If a task does not move the edge or the core flow, say so before building it.
- **First principles.** Before solving, name the core problem in one sentence. If you cannot, research or ask until you can. Fix the cause, not the symptom the task described.
- **Product taste.** The user's experience is the product. After any change a user can see, open the running app in the browser (the Claude in Chrome skill, `/chrome-browser`, when it is available) and use the flow the way a first-time user would. Fix what feels slow, confusing, or ugly before calling the work done. This is using the product, not running a test suite.

## Think in systems

The product is a graph: components, data, and the flows between them. A task is a change to that graph.

- Before you plan, find where the change sits: what it touches, what depends on it, what it could break. Query the knowledge graph for this instead of guessing.
- Plan work as a graph too, with the control flow written down instead of left to chance: nodes are pieces of work, each with a stated input and a stated output; edges are dependencies. Independent nodes fan out in parallel, dependent ones wait, and one named step joins the results.
- Every loop (build, check, fix) has an exit condition written before it starts and a cap on attempts. A loop that fails twice the same way needs a different approach, not a third try.
- Fix the system, not the instance. When the same mistake shows up twice, remove what allowed it, at the strongest layer that can hold it: the architecture first, then a type, lint rule, or script, and only last a new line in this file.

## Orchestration

The main session is the orchestrator and architect. It owns the plan, the architecture, the decisions, and the final integration. Workers do most of the building.

**Delegate** when the work is self-contained enough to brief in a few sentences: implementing a planned piece, broad searches, mechanical refactors, writing tests, debugging an isolated failure, reviewing a diff. Launch independent pieces in parallel, in one message.

**Do it yourself** when it is architecture, a product decision, a small edit that is faster to make than to explain, or the step that joins workers' output together.

**Pick the worker model by the shape of the task:**

- Sonnet 5.5 (`model: "sonnet"`): the work is well specified. Implementation from a clear plan, searches, mechanical edits, tests, docs. Use several in parallel.
- Opus 5.5 (`model: "opus"`): the work needs judgment. Ambiguous requirements, hard debugging, changes that cut across many parts, review of a risky diff.

**Every brief states:** the goal and why, the files the worker owns, what done looks like, and what to send back (changed files, what it ran, anything it was unsure of). A worker knows only what the brief says.

**Keep workers out of each other's way.** One owner per file. Workers that must edit overlapping files run one after another or in separate worktrees. Add parallel workers as their output proves reliable on this codebase; more agents on a shaky plan only produces more to throw away.

**Read what comes back.** A worker's report is a claim. Look at the diff for anything that matters before building on it.

If `/superset:orchestrate` or `/ecc:team-agent-orchestration` is installed, use it when the work needs many long-running agents across separate workspaces or branches. Otherwise the Agent tool with the rules above is enough.

## Verification

Match the check to the risk. Most changes need only this: run the thing you changed once and see it work.

Bring in an independent reviewer or a wider test pass only for significant architectural changes, data migrations, auth, payments, or anything that cannot be undone. Do not run full end-to-end suites or spawn verifier agents by default. That spends tokens on output that is usually already right.

## Knowledge graph

When `graphify-out/` exists, it holds a graph of this codebase and is the first place to look for how things connect.

- Ask the graph before grepping or reading files one by one: `/graphify query "<question>"`, `/graphify path "<A>" "<B>"`, `/graphify explain "<node>"`. Use plain search for literal strings and for files changed since the last build.
- No graph yet: build it with `/graphify .` once the first real code exists.
- Keep it current: run `/graphify . --update` after a feature lands. If the graphify git hook is installed, commits do this for you.
- If graphify is not installed, skip this section and search normally.

## Decision log

Append to `docs/log.md` whenever something important is decided or changed: architecture, a dependency, the data model, a scope cut, a reversed decision, a finished feature. Skip trivia like typos.

One entry is two lines at most, newest at the bottom:

```
YYYY-MM-DD · <what was decided or changed> · <why>
```

Write the entry in the same turn as the decision. You do not need to read this file during normal work; the graph is where you look things up. The log exists so a person can trace the history when something goes wrong.

## Shipping

- One commit is one coherent change that leaves the app working. The message says what changed and why.
- Keep changes small enough to review in one sitting. Split anything larger.
- Agents copy what is already in the repo, so the repo is the real instruction set. Keep one way of doing each thing, and delete dead code, commented-out code, and anything the change made unnecessary.
- Match the existing pattern before introducing a new one. If the existing pattern is wrong, replace it everywhere in its own commit.
- Comments explain why something non-obvious is the way it is. Never use one to excuse a workaround; fix the cause.
