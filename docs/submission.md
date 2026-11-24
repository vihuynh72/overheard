# Submission text

Ready to paste into the HackwithBay 4.0 form.

## Project name

Overheard

## One line (under 140 characters)

Overheard finds people who describe your product's problem in public, quotes what they wrote, and drafts a message you approve.

## Description for judges

Outbound fails because the sender does not know whether this person has this problem now. Overheard starts from that fact. You give it your website. It works out who your buyers are and where they write, then reads public GitHub issues and forum posts and matches them by meaning to the problems your product solves. Every lead links to the exact post the person wrote.

For each person it drafts a short message that answers what they said. A second model checks every claim in the draft against the post. A code check cuts any number the person never wrote. Nothing is sent without your approval, and in this build no message reaches a lead at all. It goes to your own inbox or a test inbox.

Autonomy is earned. Overheard may release messages alone only after its calls have matched yours, and one release you would have stopped switches it off. When your buyers do not write in public, it says so and stops.

## How it maps to the rubric

- **ICP and discovery.** The Planner reads your site, infers buyers, pains, competitors and where to listen, and refuses products the method cannot serve. Each lead carries its source link, date and matched pain. See the Customer and People sections of the app.
- **Enrichment and outreach.** Tavily finds the company domain and Hunter finds and verifies an email. Drafts quote the person's own words and pass rule checks and a second-model claim check. You approve, edit or reject. Sending goes through Resend to a test inbox. Gmail sending is coded but its Google setup was not finished.
- **Dashboard and lead management.** The People section ranks leads by tier with evidence and one question card to decide. The Activity section shows the audit trail, self-check, autonomy gates and credit ledger. The five-stage board was removed.
- **Startup viability.** Live runs on flexprice.io read 463 issues across 3 trackers plus 7 to 8 forum posts. 39 to 43 people described a target pain, and 6 to 9 leads were kept. A ten-product simulation shows where the method works (open-source developer tools) and where it does not. There are no customers or revenue yet.
- **Tech and demo.** FastAPI, an embedded Kuzu graph, Moss search, about 400 offline tests, a run budget on the public copy, and an MCP server at `/mcp` with six tools and no decision tools. The design document is `docs/architecture.md`.
- **Band bonus.** Four Band-hosted agents (Planner, Builder, Reviewer, Security) planned, built and reviewed one real change, in read-only plan mode. An operator session relayed messages through the Band CLI and applied the patch. No permission prompt was approved by automation. See `docs/band-run.md`.
- **Flexprice bonus.** Usage events (lead enriched, outreach sent, graph query) go to Flexprice. A priced plan and subscription draw down a wallet, and a credit gate runs before enrichment, approval and release. Each lead shows its cost. See `app/billing.py` and the Activity section.

## Links

- Deployment: https://earshot-production.up.railway.app
- Repository: https://github.com/vihuynh72/overheard
- Design document: docs/architecture.md
- Band proof: docs/band-run.md
- Demo video: demo/earshot-demo.mp4 (upload and paste link)
- MCP: `claude mcp add --transport http earshot https://earshot-production.up.railway.app/mcp`

## Sponsor tools used

- **Anthropic Claude (Sonnet 5.5):** the Planner, the Qualifier and the Writer.
- **Moss:** matches issue text to pain statements by meaning.
- **Tavily:** reads your website, searches forums and review sites, and finds company domains.
- **Hunter:** finds and verifies email addresses.
- **Flexprice:** usage metering, a prepaid wallet and the credit gate.
- **Band:** four agents planned and reviewed one change.
- **Resend:** delivers approved drafts to a test inbox.
- **SubQ:** the second model that checks each claim in a draft.
- **ElevenLabs:** used for a voice control that was removed from the interface. The server code remains but nothing calls it.

## What is next

First, sign-in and a persistent volume, so the public copy is safe to leave open and results survive a redeploy. Second, reply tracking, so Overheard learns from what happens after a message and not only from your approvals. Third, finishing Gmail sending and finding out why feature-flag and logging products returned no leads.
