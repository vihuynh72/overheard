# Band run: four agents, one real change

Date: 2026-11-24. Band CLI 0.70.0, hub 0.70.0 (`band version`). Worktree `hackwithbay-feat-band-author-gate`.

## What was and was not done

- Band was used to carry the whole conversation: `band chats send` delivered every message to a real Claude Code chat (Planner, Builder, Reviewer, Security) and `band chats watch` streamed each reply. The four agents did the planning, the diff and the two reviews.
- Every message was sent with `--mode plan` (the read-only mode) and asked for text only. The agents could read files; none edited anything or ran a command.
- The operator session (a Claude Code session driving the CLI) did the relaying and applied the Builder's diff to the main working tree by `git apply`. The agents never wrote to the repo.
- No permission prompt was approved by automation. The only prompt that appeared in any watched stream is the one described next, and it was cancelled, not answered.
- The task: hold, never release, a lead from a web post with no named author. It serves principle 1 (evidence before action) at the "checked on every run" layer.

### The stuck Planner

The Planner chat showed `running` for about an hour. Its stream shows why: a `permission` request for `band chats send chat_1795552963291_1tuw8b ... --mode default --model sonnet ...` (the earlier kickoff handoff to the Builder), waiting for a human. I ran `band chats stop` on the Planner. The stream then shows `request-resolved` with `answer: "cancelled"`, and the Planner chat went to `error`. Stopping the task cancelled the prompt; nobody approved it, and the Planner itself later reported "last turn's handoff to the Builder was rejected, so nothing has been sent". The chat returned to `idle` after the next turn.

## Chats before

```
ID                         NAME      AGENT        STATUS   LABELS
chat_1795552405696_z965zp  Chat      claude-code  idle     
chat_1795552413413_3z8cwq  Planner   claude-code  running  demo=earshot,kickoff=sent,role=planner
chat_1795552413434_ggh76g  Reviewer  claude-code  idle     demo=earshot,role=reviewer
chat_1795552413447_4ju160  Security  claude-code  idle     demo=earshot,role=security
chat_1795552963291_1tuw8b  Builder   claude-code  idle     demo=earshot,role=builder
```

## Chats after

```
ID                         NAME      AGENT        STATUS  LABELS
chat_1795552405696_z965zp  Chat      claude-code  idle    
chat_1795552413413_3z8cwq  Planner   claude-code  idle    demo=earshot,kickoff=sent,role=planner
chat_1795552413434_ggh76g  Reviewer  claude-code  idle    demo=earshot,role=reviewer
chat_1795552413447_4ju160  Security  claude-code  idle    demo=earshot,role=security
chat_1795552963291_1tuw8b  Builder   claude-code  idle    demo=earshot,role=builder
```

## Relay

Raw watch output is not saved: each stream is 2.5 to 4.2 MB (over the 200 KB limit, because a watch replays the chat history) so they stay out of the repo. A scan for secret patterns matched only the substring `sk-` inside skill names such as `risk-assessment`, in the skill list each chat loads; no real keys were seen.

### 1. Stop the stuck Planner, then send it the task

```
band chats stop chat_1795552413413_3z8cwq
+ band chats send chat_1795552413413_3z8cwq --worktree hackwithbay-feat-band-author-gate --mode plan --message 'Task for Planner. Reply with text only. Do not edit files, run commands or use tools that need permission....'
```

Planner reply (verbatim):

Reading the two files first.**Plan (text only; nothing run or edited)**

1. **Where:** `app/policy.py`, inside `decide()`, as one more `why.append(...)` beside the "No verified email address" check. It runs in both modes, so autopilot can't skip it. A `drop` rule still wins, because that return comes first.
2. **Condition:** read only `lead.get("signals")`. Hold if any signal `s` has `s.get("kind") == "web"` and `not str(s.get("author") or "").strip()`. That covers a missing key, `None` and a whitespace-only author. Don't read `lead["name"]` or `lead["login"]`: the pipeline sets name to the host when there is no author, and a crafted name or login like `reddit.com/u/alice` would make the lead look authored.
3. **Fail closed:** a lead with no web signal is untouched, so GitHub leads (no `kind`, always an author) behave as before. A lead with one authored and one blank web signal is held.
4. **Reason (exact):** `"No named author, so there is nobody to write to"`.
5. **Tests in `tests/test_policy.py`:** add a row to `test_each_hold_branch` with `signals=[{"repo": "news.ycombinator.com", "kind": "web", "author": ""}]`, which must give exactly `{"action": "hold", "reasons": [reason]}`.
6. **More cases:**
   - Whitespace author and missing `author` key are both held.
   - Crafted `name="alice"` and `login="reddit.com/u/alice"` with a blank signal author are still held.
   - A web signal with `author="alice"` releases.
   - A GitHub-style signal with no `kind` releases.
   - A mixed web lead (one authored, one blank signal) is held.
7. **Run:** `pytest tests/test_policy.py tests/test_scout_web.py tests/test_pipeline_web.py`.
8. **Not doing:** no change to `scout_web.py` and no new policy flag.

I'd also add one line to `docs/log.md` for this rule, per CLAUDE.md. Known limit: an author that is a placeholder like `"-"` or the host itself passes. `_author()` only returns regex-matched Reddit and X handles today, so this is not reachable now.

Last turn's handoff to the Builder was rejected, so nothing has been sent. Reviewer and Security have no verdicts to wait for. Tell me when to hand this plan over.

> Cognee memory: Band's @mention approval isn't an enforced gate, so the app has to hold the lead itself, from the agent_sessions dataset (it ties to the earlier handoff and approval-gate work).

### 2. Builder: diff as text

```
+ band chats send chat_1795552963291_1tuw8b --worktree hackwithbay-feat-band-author-gate --mode plan --message 'Task for Builder. Reply with text only. Do not edit files, run commands or use tools that need permission. You may read files (plan mode)....'
```

The operator note in the message pointed out that stored signals lose `kind` and `author`, so the Planner's condition alone would never fire on autopilot. The Builder confirmed this in the code and added a login check. Builder reply, prose only (its diff is the first version of the final diff below):

I'll read the code before writing the diff.Here is the diff. It is untested, because plan mode lets me read files but not run commands.

**What I chose:** `decide()` holds on either of two signals. The first is a login starting with `web:`, because stored signals lose `kind` and `author` but the login survives, and a GitHub login cannot contain `:`. The second is any signal with `kind == "web"` and a blank or missing author. I kept the second because fresh, unstored leads still carry both fields, and it is the planner's original rule.

**What the code shows:**
- `store.py:24` defines the `Signal` node with no `kind` or `author` columns.
- `pipeline.py:339` writes only `id`, `url`, `title`, `excerpt`, `created`, `pain` and `match`.
- `store.leads()` (`store.py:70`) returns those fields plus `repo`.
- `decide()` is only called from `autopilot._decide` (`autopilot.py:57`) with leads read back from the store, so the signal branch alone would never fire in production.
- The login check only adds holds, so a crafted login can make a lead held but never released.

**Not done:**
- I didn't run pytest or check `autopilot.py` for other places that count hold reasons, such as the `top_reasons` summary, which will now show the new reason.
- `docs/log.md` still needs the one-line entry CLAUDE.md asks for.
- Authored web leads from other sites still pass. `_author()` returns handles only for Reddit and X, so every other host (blogs, forums, review sites) is anonymous by construction and will now be held.

The operator applied the diff with `git apply` (it applied cleanly). Tests: 377 passed (368 before plus 9 new cases).

### 3. Reviewer and Security, in parallel

```
+ band chats send chat_1795552413434_ggh76g --worktree hackwithbay-feat-band-author-gate --mode plan --message 'Task for Reviewer. Reply with text only. Do not edit files, run commands or use tools that need permission....'
+ band chats send chat_1795552413447_4ju160 --worktree hackwithbay-feat-band-author-gate --mode plan --message 'Task for Security. Reply with text only. Do not edit files, run commands or use tools that need permission....'
```

Reviewer reply (verbatim):

**APPROVE**

1. **Correct and fail-safe:** `_no_named_author` only ever adds a hold reason, so it cannot release a lead; blank, whitespace, `None` and missing authors are all covered, and both the stored shape (login only) and the fresh shape (signals) are tested.
2. **Main risk, non-blocking:** on stored leads the gate rests entirely on the `web:` login prefix from `scout_web.as_people`, and only a comment ties the two together. Add one test that feeds an authorless voice through `as_people` into `decide()`, so a prefix change fails loudly instead of silently releasing.
3. **Nits:** `test_authorless_web_login_is_held_on_stored_signals` duplicates the new parametrized `web:3fa91c0b7e` case, so drop one. `kind == "web"` is an exact match, which is fine as long as the scout always writes it in lowercase.
4. **Missing from the diff:** the `docs/log.md` entry that CLAUDE.md requires. It should also say that web sources other than Reddit and X are always authorless, so they will now always hold.
5. **Not checked:** I reviewed the diff text only and opened no files. I did not confirm the `web:<hex>` key format in `scout_web.py`, whether the manual approve path can still send a held authorless lead, or how the new reason affects the hold-reason counts in `autopilot.py`.

Security reply (verbatim):

1. **Bypass by crafted name or login: no, from this diff.** `name` is never read, the check only adds holds, and an attacker cannot choose the `web:<hex>` key or put ":" in a GitHub login.
2. **Stored leads rest on the prefix alone.** Once `kind` and `author` are dropped, the match is exact and case-sensitive, so a login like `" web:…"` or `"WEB:…"` would release. Nothing produces those today; `.strip().lower()` would close it.
3. **The real bypass risk is upstream, in `scout_web._author()`.** If a non-person URL path such as `x.com/i/status/…` or `/share/…` yields an "author" like `i`, the lead is keyed `x.com/u/i` and releases on autopilot. Add a reserved-segment denylist there, with a test.
4. **Leak: none.** The hold reason is a static string with no login, hash, or URL in it, and the test fixtures are synthetic.
5. **Not checked:** I read only the diff, so `_author()`, `rule_matches`, and whether any rule or merge path can rewrite a login or force a release are all unverified.

### 4. Changes made from the reviews

- Security point 2: the login check now strips and lowercases before testing the `web:` prefix.
- Reviewer point 2 and 3: removed the duplicate test and added one that feeds an authorless voice through `scout_web.as_people` into `decide()`, so a change to the key format fails the test.
- Not done, outside the allowed files: Security point 3 (reserved URL segments such as `/i/status/` in `scout_web._author`, which could yield a fake author like `i`), and the `docs/log.md` entry the Reviewer asked for. Both are follow-ups.

### 5. Final verdicts (one follow-up round)

```
+ band chats send chat_1795552413434_ggh76g --worktree hackwithbay-feat-band-author-gate --mode plan --message 'Follow-up for Reviewer. Reply with text only. Do not edit files, run commands or use tools that need permission....'
+ band chats send chat_1795552413447_4ju160 --worktree hackwithbay-feat-band-author-gate --mode plan --message 'Follow-up for Security. Reply with text only. Do not edit files, run commands or use tools that need permission....'
```

(`band chats watch` replays the chat history, so each raw reply starts with the previous one. Only the new part is shown.)

Reviewer, final:

**APPROVE**

Both review points are closed: the `as_people` → `decide()` test now locks the `web:` prefix contract, and the normalised prefix check only widens what gets held.
Still owed before merge is the `docs/log.md` entry, including that web sources other than Reddit and X will now always hold. I have not seen the revised diff or run the tests, so this rests on your description.

Security, final:

**PASS.** The gate only adds holds, the prefix check is now robust to case and whitespace, and the hold reason leaks nothing.

The verdict covers this diff as described: I have not seen the revised line, `_author()`, or `rule_matches`. Until the `_author()` reserved-segment follow-up lands, an authorless X or Reddit post with a non-person URL path can still release on autopilot.

## Final diff

```diff
diff --git a/app/policy.py b/app/policy.py
--- a/app/policy.py
+++ b/app/policy.py
@@ -75,6 +75,14 @@ def _too_old(newest: str, limit: int, today: datetime.date) -> bool:
         return True
 
 
+def _no_named_author(lead: dict) -> bool:
+    # The store keeps no kind or author on signals, but an authorless web voice is keyed "web:<hex>"
+    # (scout_web.as_people) and a GitHub login cannot hold ":". Fresh signals still carry both fields.
+    if str(lead.get("login") or "").strip().lower().startswith("web:"):
+        return True
+    return any(s.get("kind") == "web" and not str(s.get("author") or "").strip() for s in lead.get("signals") or [])
+
+
 def decide(lead: dict, policy: dict, rules: list[dict], findings: list[dict],
            sent_today: int, today: datetime.date) -> dict:
     hits = [r for r in rules if rule_matches(r, lead)]
@@ -87,6 +95,8 @@ def decide(lead: dict, policy: dict, rules: list[dict], findings: list[dict],
         why.append(f"Score {lead.get('score', 0)} is below your minimum of {policy['min_score']}")
     if policy["require_verified_email"] and lead.get("email_status") != "valid":
         why.append("No verified email address")
+    if _no_named_author(lead):
+        why.append("No named author, so there is nobody to write to")
     if policy["require_production_use"] and not lead.get("production"):
         why.append("No sign of production use")
     if not lead.get("newest"):
diff --git a/tests/test_policy.py b/tests/test_policy.py
--- a/tests/test_policy.py
+++ b/tests/test_policy.py
@@ -3,6 +3,7 @@ import datetime
 import pytest
 
 from app.policy import DEFAULT_POLICY, decide, make_rule, rule_matches, suggest_rule, summarize, validate
+from app.scout_web import as_people
 
 TODAY = datetime.date(2026, 11, 24)
 
@@ -14,6 +15,7 @@ LEAD = {
     "signals": [{"repo": "getlago/lago", "title": "Metering lag", "excerpt": "events arrive late"}],
 }
 AUTOPILOT = {**validate({}), "mode": "autopilot", "approved_first_batch": True}
+NO_AUTHOR = "No named author, so there is nobody to write to"
 
 
 def run(lead=None, policy=None, rules=(), findings=(), sent=0):
@@ -33,6 +35,8 @@ def test_clean_release_in_autopilot():
     ({"findings": [{"login": "x", "rule": "placeholder", "detail": "d"}]}, "Failed self-check: placeholder"),
     ({"lead": {"score": 42}}, "Score 42 is below your minimum of 50"),
     ({"lead": {"email_status": "unknown"}}, "No verified email address"),
+    ({"lead": {"login": "web:3fa91c0b7e"}}, NO_AUTHOR),
+    ({"lead": {"signals": [{"repo": "reddit.com", "kind": "web", "author": ""}]}}, NO_AUTHOR),
     ({"policy": {"require_production_use": True}, "lead": {"production": False}}, "No sign of production use"),
     ({"lead": {"newest": "2020-01-01"}}, "Evidence is older than 730 days"),
     ({"lead": {"newest": "garbage"}}, "Evidence is older than 730 days"),
@@ -45,6 +49,38 @@ def test_each_hold_branch(kwargs, reason):
     assert run(**kwargs) == {"action": "hold", "reasons": [reason]}
 
 
+@pytest.mark.parametrize("sig", [
+    {"repo": "reddit.com", "kind": "web", "author": ""},
+    {"repo": "reddit.com", "kind": "web", "author": "   "},
+    {"repo": "reddit.com", "kind": "web", "author": None},
+    {"repo": "reddit.com", "kind": "web"},
+])
+def test_web_signal_without_author_is_held(sig):
+    assert run(lead={"signals": [sig]}) == {"action": "hold", "reasons": [NO_AUTHOR]}
+    assert NO_AUTHOR in run(lead={"signals": [sig]}, policy={"mode": "supervised"})["reasons"]
+
+
+def test_crafted_name_and_login_cannot_hide_a_missing_author():
+    sig = {"repo": "reddit.com", "kind": "web", "author": ""}
+    got = run(lead={"name": "alice", "login": "reddit.com/u/alice", "signals": [sig]})
+    assert got == {"action": "hold", "reasons": [NO_AUTHOR]}
+
+
+def test_authorless_voice_from_the_scout_is_held_on_its_stored_shape():
+    # the key as_people really produces, with signals as store.leads() returns them (no kind or author)
+    voice = {"id": "web:3fa91c0b7e", "repo": "reddit.com", "author": "", "kind": "web"}
+    (login, _), = as_people([voice])
+    assert run(lead={"login": login}) == {"action": "hold", "reasons": [NO_AUTHOR]}
+    assert run(lead={"login": " WEB:3fa91c0b7e"})["reasons"] == [NO_AUTHOR]
+
+
+def test_authored_web_and_github_leads_release():
+    web = {"repo": "reddit.com", "kind": "web", "author": "alice"}
+    assert run(lead={"login": "reddit.com/u/alice", "signals": [web]})["action"] == "release"
+    assert run(lead={"login": "reddit.com/u/alice"})["action"] == "release"  # stored shape, authored
+    assert run()["action"] == "release"  # GitHub-style signal, no kind
+
+
 def test_other_leads_findings_are_ignored():
     assert run(findings=[{"login": "someone-else", "rule": "placeholder", "detail": "d"}])["action"] == "release"
```

## Test result

```
.venv/bin/python -m pytest -q
377 passed in 1.95s
```
