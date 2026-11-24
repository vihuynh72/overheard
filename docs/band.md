# Band Desktop integration

## What actually happened

The record is [band-run.md](band-run.md). On 2026-11-24 four Band-hosted Claude Code agents (Planner, Builder, Reviewer, Security) planned, wrote and reviewed one real change: a web lead with no named author is never released. Every message went out in read-only plan mode, so the agents read files and edited nothing. An operator session relayed the messages through `band chats send` and `band chats watch`, and applied the Builder's diff with `git apply`. No permission prompt was approved by automation; the one prompt that appeared was cancelled when the stuck Planner chat was stopped. The rule is now in `app/policy.py`. The six-step demo below (`scripts/band/demo.sh`) is the earlier design, with a human Yes or No at each handoff; it was smoke-tested but a full agent-to-agent handoff through it was not observed.


Band bonus (+20) in the judging text: specialized agents working together, a human deciding the risky step, and the shared message stream, tokens and cost visible to everyone.

## What Band is in version 0.70

Band (CLI and hub 0.70.0) is a desktop app plus a local hub (`http://localhost:3456`) for running coding agents side by side on git worktrees. It has no "rooms" and no @mentions. The pieces line up with the judging text like this:

- A **chat** (one agent pane) is one specialized agent.
- **Labels** on a chat give it a role.
- An agent reaches another agent by running `band chats send <chat id>` from its own shell. Every agent has `band` on its PATH, plus its own chat and worktree ids (`BAND_CHAT_ID`, `BAND_WORKTREE_ID`).
- The human decision is the agent's **permission prompt**. In Manual mode the agent stops before each change or shell command, and the human clicks Yes or No in the pane.

**Honest gap.** No @mention syntax exists, and the built-in `band` MCP server has no tool for sending a message to another chat. Its tools are `worktrees_create`, `worktrees_pr_*` and `band_editor_*`. A handoff in this version is a shell command that names the receiving chat's id.

## Concepts (one line each)

- **hub**: the local server the desktop app starts; it holds all state. The CLI is a thin client to it.
- **repo**: a registered git repository, identified by its remote URL. Registering one also lists its main checkout as a worktree (`hackwithbay-main`).
- **worktree**: a git worktree, plus Band's state for it, under `~/.band/worktrees/<repo>/<branch>`. It holds only committed files.
- **worker**: a machine that worktrees run on. This laptop is `local`.
- **runner**: scripts that start workers on demand. None are set up here.
- **group**: a sidebar section of worktrees.
- **chat**: an agent pane in a worktree, with its own agent process, mode, model and history. It can be created, sent to, watched, stopped, removed and labelled.
- **agent session**: one run of a coding agent, in a chat (gui) or a terminal (tui). Band also lists Claude Code sessions started outside Band, through hooks.
- **terminal**: a shell pane in a worktree, which the CLI can drive.
- **browser**: a browser tab pane in a worktree.
- **cronjob**: a prompt sent to a worktree's chat on a schedule.
- **subscription**: what a chat waits for (PR reviews, CI, a webhook or a timer). Band wakes the chat with a short message when it happens.
- **tools**: the built-in `band` MCP server that every chat gets. `band tools list/call` reaches it from a shell.
- **mcp**: outside MCP servers that the hub proxies for agents, with credentials kept in the vault.
- **vault**: encrypted credentials held by the hub.
- **tokens**: device and worker auth tokens for the hub. These are not LLM tokens.
- **settings**: the coding agents (claude-code, codex, opencode) and the default agent.
- **schema**: every command's parameters as JSON.
- **skills**: Agent skills shipped with the CLI (`band`, `band-chat`, `band-start`, `band-loop`, `band-subscribe`, `band-terminal`, `band-browser`), already installed in `~/.claude/skills`.

## The demo in six steps

The task is a real Overheard rule: a web lead with no named author is never released. It belongs in `app/policy.py` `decide()`. It changes what Overheard may send, so a human must approve it.

1. **Setup.** Run `scripts/band/demo.sh`. The judge sees one worktree, `feat/band-author-gate`, in the Band sidebar. It has four panes labelled Planner, Builder, Reviewer and Security.
2. **Planner.** It reads the policy code and writes an eight-line plan that ends with `HUMAN DECISION`. It then tries to run `band chats send <Builder>`. The judge sees the Planner pane stop on a Yes/No prompt that shows that exact command.
3. **Human decision.** The founder clicks Yes, and the plan lands in the Builder pane. A No stops the chain. Band enforces this gate, so it does not depend on prose in a prompt.
4. **Builder.** It edits `policy.py` and adds a test. Each edit asks for Yes as well, because the chat is in Manual mode. It runs the tests, then sends the diff summary to Reviewer and Security, each send behind a Yes.
5. **Reviewer and Security.** Each reads `git diff`, replies PASS or BLOCK in at most five lines, and sends that verdict to the Planner.
6. **Close.** The Planner posts a three-line summary. The judge sees the whole exchange through `scripts/band/demo.sh watch`, one prefixed line per agent with `>>> WAITING FOR HUMAN` at each gate, or in the panes themselves.

For a 90-second video, record the run in advance and cut it down to steps 2, 3 and 6, plus one frame of the token meter.

## Token and cost visibility

- **CLI.** `band chats watch <id>` streams `usage_update` events. Each one carries the tokens in context and the window size (for example `132197/200000`), the model (`claude-fable-5-2`), and the account's rate-limit use (seven-day utilization 0.56 at the time of the smoke test). `demo.sh watch` prints the token line for each agent.
- **App.** The same events drive the chat pane. A context meter there is expected but has not been confirmed by eye.
- **Not seen.** No dollar cost appeared anywhere in the CLI output. "Cost" has to be shown as token counts plus the model name, or computed by hand.
- **The cost to know about.** Each new Claude Code chat starts at about 132k tokens of context, because it loads every skill, plugin and MCP server installed for this user. The default model in a chat is Fable. The script sends with `--model sonnet` to keep four agents affordable.

## What was actually run (2026-11-24)

1. **Read-only checks.** `band version` showed CLI and hub at 0.70.0. `repos`, `worktrees`, `agents --all`, `groups` and `cronjobs` were all empty. One worker, `local`, is online with agents claude-code, codex and opencode.
2. **`band repos add <this repo>`** registered `hackwithbay` (git, origin github.com/vihuynh72/overheard, checkpoints on). The main checkout became worktree `hackwithbay-main`.
   - `band agents list --all` then showed the two Claude Code sessions already running in the main checkout, one of which was the session doing this work.
3. **`band worktrees create hackwithbay feat/band-author-gate`** created worktree `hackwithbay-feat-band-author-gate` at `~/.band/worktrees/hackwithbay/feat/band-author-gate`. It contains only `README.md`, because only the initial commit exists and all the app code is uncommitted.
   - Band also created a default pane named `Chat` automatically.
4. **Four chats created** with labels `role=<role>,demo=earshot`:
   - Planner `chat_1795552413413_3z8cwq` (plan mode)
   - Builder `chat_1795552413425_r5y6tl` (Manual mode)
   - Reviewer `chat_1795552413434_ggh76g` (plan mode)
   - Security `chat_1795552413447_4ju160` (plan mode)

   The script switches every send to Manual mode and Sonnet.
5. **One smoke-test message to the Builder.** The first attempt was refused before anything was sent: outside a worktree directory, `band chats send` needs `--worktree` even when given a chat id. With `--worktree` it was delivered. The stream showed, in order:
   - prompt, then turn-started
   - the user's own Claude Code PreToolUse hook (a "Fact-Forcing Gate") blocking the first Bash call; the agent answered it
   - a `permission` event with options `allow-once` ("Yes") and `reject` ("No")

   The CLI has no command to answer that prompt; it is answered in the app. I stopped the turn with `band chats stop`, and the Builder chat now shows status `error`.
6. **`scripts/band/demo.sh` run for real.** It stopped at the guard, as designed: main has no `app/policy.py`. Nothing else was created or sent.

## Not yet tested

- **Whether a handoff arrives.** No agent has yet run `band chats send` to another chat. Band's environment variables and `band` on PATH are documented in the skills; the smoke test was stopped before printing them.
- **The Builder's `error` status.** Not checked: whether the chat recovers on the next send. If it does not, remove it (`band chats remove chat_1795552413425_r5y6tl`) and re-run the script, which recreates the Builder by label.
- **Mode changes.** Not checked: whether `--mode default` on `chats send` really switches a chat created in plan mode.
- **Plan approval as a second gate.** Not tried: Claude Code's own "approve this plan" prompt (plan mode's ExitPlanMode) as a further human gate.
- **The app's token display.** Not seen by eye.
- **How long the full run takes.** Unknown, as is how many prompts the user's global hooks add to each agent's first command.

## Before the demo (the user's calls)

1. **Commit the app code to `main`.** The worktree can only hold committed files. The script fast-forwards the worktree to `main` once `main` has `app/policy.py`.
2. **Run** `scripts/band/demo.sh --dry-run`, then `scripts/band/demo.sh`, then `scripts/band/demo.sh watch` in a second terminal.
3. **Answer the prompts** in the Band app. This starts billable agent work: four Sonnet chats, each starting at about 130k tokens of context.
4. **Clean up afterwards** if wanted:
   - `band chats remove <id>` for each chat
   - `band worktrees remove hackwithbay feat/band-author-gate`
   - `band repos remove hackwithbay`

The script reads and writes no Overheard project data. Its only local effect is a fast-forward merge inside the Band worktree.
