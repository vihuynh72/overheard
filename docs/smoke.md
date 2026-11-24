# Smoke test

`scripts/smoke.py` runs 16 read-only checks against any Earshot deployment: pages and static assets, the shape of `/api/state`, the evidence rules on every lead (cited, scored 0-100, staged, no draft on a web lead), trust gates, billing, graph, the six MCP tools, and live evidence links. It proves the deployment is up, serves the contracts the product claims, and every lead links to a real page.
It does not prove lead quality, that a run completes (`/api/run` is only checked to exist, never called), or that mail is delivered; the optional `--write-test` approves one pending draft (changes state, may spend one `outreach.sent` credit, never mails the lead) and is not part of the default run.

Run: `.venv/bin/python scripts/smoke.py [BASE_URL]` (default `http://localhost:8765`). Exit code is non-zero on any FAIL; WARN (for example a GitHub rate limit) does not fail.

## Output, 2026-11-24 14:50 PST

```
$ .venv/bin/python scripts/smoke.py
PASS landing /                   200, map section and /app link present
PASS app shell /app              200, references app.js app.css ask.js
PASS static app.js               200 text/javascript, 54043 bytes, cache-control: no-cache
PASS static app.css              200 text/css, 21779 bytes, cache-control: no-cache
PASS static ask.js               200 text/javascript, 21109 bytes, cache-control: no-cache
PASS static tokens.css           200 text/css, 2336 bytes, cache-control: no-cache
PASS static landing.js           200 text/javascript, 20558 bytes, cache-control: no-cache
PASS static vendor/gsap.min.js   200 text/javascript, 72214 bytes, cache-control: no-cache
PASS state shape                 200 JSON, 8 leads, running=False
PASS leads: evidence rules       8 leads all cited, scored 0-100, staged; 2 with a valid email
PASS trust gates                 3 of 5 pass, autonomy level supervised
PASS billing                     28.8 credits, mode flexprice, 9 ledger entries
PASS graph                       counts {'people': 8, 'companies': 1, 'repos': 4, 'signals': 10, 'pains': 4, 'edges': 41}, 5 insights; /api/graph/insights agrees
PASS MCP tools                   6 tools: customer_profile, find_leads, get_lead, list_leads, run_status, trust
PASS evidence links live         github.com 200; github.com 200; github.com 200
PASS run endpoint present        /api/run exists (not called: it would consume a run)

16 pass, 0 warn, 0 fail  (http://localhost:8765)

$ .venv/bin/python scripts/smoke.py https://earshot-production.up.railway.app
PASS landing /                   200, map section and /app link present
PASS app shell /app              200, references app.js app.css ask.js
PASS static app.js               200 text/javascript, 54043 bytes, cache-control: no-cache
PASS static app.css              200 text/css, 21779 bytes, cache-control: no-cache
PASS static ask.js               200 text/javascript, 21109 bytes, cache-control: no-cache
PASS static tokens.css           200 text/css, 2336 bytes, cache-control: no-cache
PASS static landing.js           200 text/javascript, 15681 bytes, cache-control: no-cache
PASS static vendor/gsap.min.js   200 text/javascript, 72214 bytes, cache-control: no-cache
PASS state shape                 200 JSON, 4 leads, running=False
PASS leads: evidence rules       4 leads all cited, scored 0-100, staged; 1 with a valid email
PASS trust gates                 3 of 5 pass, autonomy level supervised
PASS billing                     28.8 credits, mode flexprice, 8 ledger entries
PASS graph                       counts {'people': 4, 'companies': 1, 'repos': 5, 'signals': 14, 'pains': 6, 'edges': 46}, 5 insights; /api/graph/insights agrees
PASS MCP tools                   6 tools: customer_profile, find_leads, get_lead, list_leads, run_status, trust
PASS evidence links live         github.com 200; github.com 200; github.com 200
PASS run endpoint present        /api/run exists (not called: it would consume a run)

16 pass, 0 warn, 0 fail  (https://earshot-production.up.railway.app)
```

The production run reports a different `landing.js` size than local (15681 vs 20558 bytes): production is behind the working tree.
