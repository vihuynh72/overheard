# Eval: does Earshot use every sponsor tool, and use it well

## How to re-run

```
.venv/bin/python scripts/eval_tools.py          # full: alive, used, quality
.venv/bin/python scripts/eval_tools.py --quick  # alive and used only
.venv/bin/python -m app.simulate --workers 2 --out data/sim/run-N.json   # end to end, ten product types
```

The keys come from the environment (`.env.example` lists them). The local server must be running on port 8765, because the "used" counts come from its last real run (`/api/state`) and `data/autopilot.json`. Results go to `data/eval/latest.json`. The script exits 1 if any tool fails its alive check. One tool's error never stops the others.

One full run spends: Hunter 5 domain searches, Tavily 1 search, 1 extract and 3 searches, Claude 3 calls, one Flexprice event (`graph.query`, 0.1 credits, source `earshot-eval`), and one Resend message to `delivered@resend.dev`.

## What is measured

Each tool gets three measurements, each a real call with an assertion.

- **Alive.** A minimal real call through the app's own code where one exists (`pipeline.ask`, `reviewer.snap_judge`, `mailer.send`).
- **Used in the product.** Counts from the most recent real run (Flexprice, flexprice.io as the product).
- **Quality.** One number on a fixed fixture, so it can be repeated: 30 issue texts for Moss (10 about usage billing, 20 not), two product descriptions for the Planner, six drafts (three honest, three that overclaim) for SubQ and the number guard, three pain queries for Tavily, five public company domains for Hunter.

## Results (2026-11-24)

| Tool | Alive | How hard it worked in one real run | Quality | Verdict |
|---|---|---|---|---|
| Claude (Sonnet 5.5) | structured output through `pipeline.ask` | 27 calls: Planner 1, learn-pains 1, Qualifier and Writer 25 (one per candidate) | Planner 5/5 assertions: at least 3 pains, 6 valid channel hosts, flexprice fits, goat yoga declined | PASS |
| Moss | index of 5 docs created, queried, deleted | 463 issues indexed, 8 queries (5 pains + 3 learned), 70 hits above 0.3 | precision@5 1.00, recall 0.50, 0 off-topic docs above MIN_MATCH | PASS |
| Tavily | 1 search, 1 extract (115k characters of flexprice.io) | 1 site extract, 10 web searches planned, 7 posts kept | 5 of 15 results (33%) pass the app's filters; 0 of 5 kept have a date | WEAK on dates |
| Hunter | account read, domain search on stripe.com | 1 of 6 leads looked up, 1 verified address | 5/5 public domains return an address with a verification status | PASS |
| Flexprice | real-time wallet balance, plan `earshot-credits` and all three features exist | 9 events (6 `graph.query`, 3 `lead.enriched`), 6.6 credits drawn | labelled eval event drew the wallet 44.9 to 44.8 in 1.3 s | PASS |
| SubQ | supported claim P=0.98, invented claim P=0.06 | 6 drafts judged, 3 flagged | 6/6 drafts judged correctly | PASS |
| Number guard (no model) | not a service | runs on every draft before SubQ | before fix: cut 1 of 3 honest drafts. After: 0 of 3. Catches 1 of 3 overclaims (the other two have no number, or would leave one sentence, and go to SubQ) | PASS after fix |
| Resend | `mailer.send` sent to `delivered@resend.dev`; the fake lead's address was not used | 0 sends in the last run; 8 human decisions recorded | not scored | PASS |
| Gmail | not configured, as a plain fact | not connected | not scored | n/a |
| Band | `band version` and `band chats list hackwithbay-feat-band-author-gate` succeed; `docs/band-run.md` exists | verified by transcript, not a live agent run | not scored | PASS |
| ElevenLabs | list-voices returned 25 voices | used for the demo film's voices; not called by the app | not scored | n/a |

## What the eval found and what was fixed

1. **The number guard cut honest sentences.** "You mentioned sending about 40k usage events a day" was removed although the person wrote "40k". The pattern read "40k" as a bare "40", which is not in the evidence as a whole word. Fixed in `app/reviewer.py` so the k, m and b suffix belongs to any number. Before: 1 of 3 honest drafts cut. After: 0 of 3. Test: `tests/test_pipeline_rewrite.py`.
2. **The company domain came from a directory page.** For "Danfoss" Tavily ranked `tavily.com/knowledge/...` and `leadiq.com` above `danfoss.com`, and the app took the first one, so Hunter looked for the person at tavily.com. Fixed in `app/enrich.py`: the chosen host must carry a word of the company name. Before: tavily.com. After: danfoss.com. Test: `tests/test_enrich.py`.
3. **Fewer sources were tried than exist.** A lead with no company was skipped even when the GitHub profile's `blog` field named their own domain, and a Hunter finder miss was final. Now the order is: public profile email, then the profile's own domain (company field, then blog field, skipping hosted blogs such as github.io), then a web search for the company, then Hunter finder, then one Hunter domain search that takes the person's own listed address or fills the domain's pattern and keeps it only if Hunter verifies it. At most 3 Hunter calls per lead. Tests: `tests/test_enrich.py`.
4. **Failed web searches were silent.** `scout_web.find_voices` skipped a failed Tavily query without a trace. It now counts them in `scout_web.last`, and the run log says "N of M web searches failed". Test: `tests/test_scout_web.py`.

### Why verified emails are rare (today's runs gave 3, 1, 0, 2, 0)

In the last real run, of 6 leads: 1 had a public profile email (verified valid), 3 were weak fit (tier C) and skipped on purpose to save credits, and 2 had no name, company, blog or email on their GitHub profile at all. So most of the gap is the tier rule and empty profiles, not Hunter. On the two leads re-checked with real calls: `khanakia` (company Solverhood.com) gets `aman@solverhood.com`, verified valid, but only if a run does not skip them as tier C. `tollercode` ("Nils T", @Danfoss) now resolves danfoss.com instead of tavily.com, but Hunter has no address and the pattern cannot be filled without a surname, so it correctly gives nothing.

## Simulation (end to end, contact lookup off)

`python -m app.simulate --workers 2`, ten product types, detailed founder, top 6 leads judged per product. Run 3 is this task. It ran without Tavily to stay inside the call budget, and started before the guard fix.

| Run | Open-source devtools: works / thin / fails | Leads per devtool product | Judged relevant (all) | Products that should be declined and were |
|---|---|---|---|---|
| run-1 (before the fit gate) | 2 / 1 / 2 | 24.6 | 14 of 40 (35%) | 2 of 4 |
| run-2 (previous latest) | 2 / 1 / 2 | 4.4 | 13 of 14 (93%) | 4 of 4 |
| run-3 (this task) | 2 / 2 / 1 | 4.8 | 14 of 17 (82%) | 4 of 4 |

Per product in run 3: flexprice 11 leads, 6 of 6 relevant (run 2: 4 leads, thin). vectordb 8 leads, 5 of 6. auth 4 leads, 3 of 4. flags 1 lead, 0 of 1. logs 0 leads. Every non-developer, consumer, local and vague product was declined before any spend, with a plain reason. The closed-source devtool returned no leads.

Reading: the method declines the right products every time and holds relevance above 80% where it works. It is still thin for flags and logs, the open-source devtools whose trackers are mostly bug reports. The drop from 93% to 82% is 3 more judged leads, 2 of them not relevant; with samples this small it is within noise, not a regression we can name.

## Spend during this task

- Hunter: searches 4 to 11 of 50 (7 calls by the eval and the investigation). Hunter's verification counter went 9 to 23 although the eval made no verifier call; Hunter counts the verification status it attaches to finder and domain-search results. Plan for that: the new domain-search fallback can use verification credits.
- Tavily: 8 calls.
- Flexprice: 1 eval event to the real demo customer, labelled `source: earshot-eval`. A separate eval customer would need its own subscription.
- Resend: 1 message to `delivered@resend.dev`.

## What the eval does not prove

- It does not prove anyone would reply. Simulated replies are a model's guess.
- Quality fixtures are small (30 issues, 6 drafts, 5 domains) and written by us. They catch regressions, not the true error rate.
- Hunter quality is measured on large public companies. Leads are often small companies and individuals, where coverage is lower.
- Band is checked from the CLI and the saved transcript, not by running the agents again.
- The simulation ran without Tavily, so web voices are not in its numbers.
- The enrichment change was tested with mocks and two real leads, not a full live run.
- Tavily basic search returns no publish date, so web posts score with the oldest recency. Not fixed.
