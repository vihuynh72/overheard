# Decision log

Append-only history of important decisions and changes. Newest at the bottom. Two lines per entry at most.

Format: `YYYY-MM-DD · <what was decided or changed> · <why>`

---

2026-11-24 · Project initialized with CLAUDE.md, this log, and the knowledge graph setup · /initialize
2026-11-24 · Scope is the organizers' fixed AI GTM Engine spec; the core flow is intake → ICP → cited leads → graph → outreach → human approval → dashboard · the rubric scores exactly these modules
2026-11-24 · Demo client is a sponsor's product (Flexprice or Nexla) fed into the engine; goal is top 5 · carried over from the overnight brainstorm (Desktop/claude/docs/brainstorming/DECISIONS.md)
2026-11-24 · Pain locked: outbound tools send irrelevant mail and miss the right person because leads are filtered in or out wrongly; user is a founder at a small or mid-sized business · Vi's answer in brainstorm round 1
2026-11-24 · "Receipts" framing dropped as the headline; the open question is how to measure the ICP better · Vi finds it generic GTM-agent style and wants something more creative inside the spec
2026-11-24 · Demo client is Flexprice; build deep on one edge with a thin pass over the rest; commit to both Band and Flexprice bonuses; solo · Vi's answers in brainstorm round 1
2026-11-24 · Edge leaning: the ICP is a tested filter scored by rediscovering hidden known buyers (Flexprice's and competitors' public customers) · Flexprice names only 4 solid customers publicly, competitors name about 45
2026-11-24 · Main lead source is GitHub activity (forks and issues on Flexprice and open-source competitors), web search second · public dated evidence that names the person who cared; other teams will use web search only
2026-11-24 · ICP accuracy score = share of hidden known buyers the filter ranks in the top tier, from public customer lists · Flexprice's team is probably not at the venue, so no private list
2026-11-24 · Moss is the search layer: pain matching over GitHub issues (tested, 2–6 ms queries) and instant rule application via sessions and metadata filters · spike on 84 issues found real matches for 3 of 4 pain statements
2026-11-24 · Vi wants a voice agent (ElevenLabs or Pipecat); Python is acceptable; deploy on Railway is acceptable · Vi's steer; role of the voice agent still open
2026-11-24 · Voice agent is the founder's control surface (spoken intake and corrections) via ElevenLabs' hosted agent; built after the two bonuses · it scores no marks alone
2026-11-24 · Stack: Python FastAPI + Kùzu embedded graph + Moss + Claude Sonnet 5.5; static HTML/CSS/JS page with no build step; deploy target Railway · Vi's choice of Python and Railway; no build step keeps a solo build fast
2026-11-24 · Step 1 built and run on Flexprice: 463 public issues → 69 pain matches → 25 scored leads with drafts and an approval queue · approving only records the decision, nothing is sent
2026-11-24 · UI direction "Earshot": warm paper, serif headings, slate navy and gold, two-pane workbench (design record in static/tokens.css) · Vi's references officialjp.com and helios.education
2026-11-24 · SubQ Snap parked as a later upgrade for yes/no and score judgments on leads · Vi called it just an idea; UI comes first
2026-11-24 · Work split across parallel workers with one owner per file: scoring and checks, Hunter and Tavily enrichment, Flexprice credit gate, landing page; orchestrator integrates in pipeline.py and main.py · Vi asked for orchestration; 79 offline tests pass
2026-11-24 · Score now decays with evidence age (full weight under 1 year, 0.6 at 3 years) and adds 5 for a Hunter-verified email · the top lead's evidence was from 2022
2026-11-24 · Run loop: build leads, run check_leads, rewrite each rule-breaking draft once, then report remaining findings · a loop with a written exit condition and a cap of one retry
2026-11-24 · Credit gate before every enrichment and every approval; local wallet until Flexprice keys exist; weak-fit leads pause below 15 credits · Flexprice bonus needs gating that changes behaviour, not a meter
2026-11-24 · Leads who work at the product's own company are dropped · a Flexprice employee was scored as a lead for Flexprice
2026-11-24 · Landing page at /, workbench at /app · Vi asked for a proper scrolling landing page
2026-11-24 · API keys live in a gitignored .env only · the repo must be public for submission
2026-11-24 · Page ground changed to deep navy with paper-coloured type and gold for actions · Vi's choice; the design detector flagged warm cream as a default
2026-11-24 · Autonomy is earned, not toggled: autopilot needs every trust gate met (clean self-check, 90% agreement with 8 human decisions, no release the human would have stopped, simulation relevance, no regressed lesson) and steps down on an enforced-gate failure · from Lauren Tan's ordering (code-enforced first, prose last) plus Vi's ask for less human in the loop
2026-11-24 · Reviewer is a different model from the Writer (SubQ Snap yes/no probabilities per claim) and reads the full issue text · it rejected 10 of 11 drafts when given only a 300-character excerpt
2026-11-24 · Simulation across ten product types is the regression suite; failure patterns go to data/lessons.jsonl · first run showed 25 leads returned regardless of fit
2026-11-24 · Planner stops at intake when the method cannot work; Qualifier drops people rated under 40 · lessons from simulation run 1
2026-11-24 · Dropped the hidden-known-buyers accuracy score · 0 of 13 known buyers appeared; leads are individuals who rarely list a company
2026-11-24 · Interface now runs itself: an AI cursor (static/pilot.js) operates the real app and is blocked in code from pressing anything that spends money or decides for the human · Vi: "everything is manual", wanted an AI cursor managing the interface
2026-11-24 · Agents drawn as generative creatures moving between workspaces (static/habitat.js); customer profile redrawn as a portrait with pains weighted by people who voiced them (static/profile.js) · Vi asked for organic, moving, less plain
2026-11-24 · Voice control through ElevenLabs speech and a Claude interpreter limited to nine validated actions (app/voice.py) · Vi wanted the voice agent present
2026-11-24 · Second Scout searches forums and review sites through Tavily; up to a third of the lead cap is reserved for those voices (app/scout_web.py) · Vi: people discuss contracts, invoicing and collections outside GitHub
2026-11-24 · Flexprice wallet now draws down through a priced plan and subscription (scripts/flexprice_setup.py); pending charges cover the 0.2–15 s delay measured · the balance did not move without a subscribed plan
2026-11-24 · Approved and released messages are sent through Resend to a demo inbox, never to the lead (app/mailer.py) · a real send path without emailing strangers
2026-11-24 · A rejection reason becomes a standing rule when it matches a known pattern · Lauren Tan: every correction should become a deterministic check
2026-11-24 · Voice button removed; one docked question card (static/ask.js) is the only place the founder acts · the voice control asked for labour, which breaks principle 2
2026-11-24 · Planner now chooses where to listen (channels, process_areas) and the Scout learns up to three pains from the best real posts, one round · fixed site list and pre-written pains were the limit on relevance; X test showed vendors outnumber buyers, so sellers' posts are dropped
2026-11-24 · Agreement gate judges only calls that could do harm (agreed vs wrong releases); held-but-approved is reported, not penalised · QA showed autopilot was unreachable because caution counted as error
2026-11-24 · A credit for outreach is recorded only when mail left; graph.query recorded per lead · billing must match what happened
2026-11-24 · App being reduced to one home screen with sections behind an icon rail, Pipeline tab removed; MCP server at /mcp exposes read tools plus find_leads, never decisions · user found the UI cluttered and asked for agent access
2026-11-24 · A web lead with no named author is always held ("No named author, so there is nobody to write to"), in every mode; X system paths such as /i/ are not authors · planned, built and reviewed by four agents in Band (docs/band-run.md); only Reddit and X yield handles, so other web sources always hold
2026-11-24 · Interface cut to three plain sections (Customer, People, Activity) on a paper ground; map, agent creatures, AI cursor, voice and icon rail deleted · the user could not read who the customer was through the clutter
2026-11-24 · Run budget on the one function that starts runs (MAX_RUNS_PER_HOUR 6, MIN_RUN_GAP_SECONDS 20, in memory); README, architecture, band and CLAUDE.md brought in line with the three-section interface, the MCP server and the Railway copy · the public deployment has no sign-in and anyone could spend the owner's credits
2026-11-24 · Sponsor-tool eval (scripts/eval_tools.py, docs/eval.md): alive, use per run and a quality number for each tool; it found and fixed three faults: the number guard cut honest "40k" sentences, directory pages chosen as a company's domain, failed web searches hidden; enrichment now tries the profile blog domain and one Hunter domain search after a finder miss, at most 3 Hunter calls per lead · user asked to prove every tool works and improve from the result
