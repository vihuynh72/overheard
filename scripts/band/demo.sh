#!/usr/bin/env bash
# Earshot x Band: four role agents (Planner, Builder, Reviewer, Security) in one Band
# worktree. They hand work to each other by running `band chats send <chat id>` from their
# shells, and Band's permission prompt makes the human approve each handoff before it runs.
#
# Usage:
#   scripts/band/demo.sh --dry-run   print every command, run nothing
#   scripts/band/demo.sh             set up (idempotent), then send the Planner its kickoff once
#   scripts/band/demo.sh watch       stream all four chats into this terminal (Ctrl-C to stop)
#   scripts/band/demo.sh status      list the chats and their state
#
# Safe to re-run: the repo, worktree and chats are reused, and the kickoff is sent only once
# (the Planner chat gets the label kickoff=sent). Needs the Band app running and jq.
set -euo pipefail

REPO=hackwithbay
REPO_PATH="$(cd "$(dirname "$0")/../.." && pwd)"
BRANCH=feat/band-author-gate
WT=hackwithbay-feat-band-author-gate      # Band's id for $REPO + $BRANCH
MODEL=sonnet                              # each chat starts near 130k tokens of context; keep the model cheap
DRY=0; CMD=run
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    watch|status) CMD=$a ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done

run() {  # print the command; run it unless --dry-run
  printf '+'; printf ' %q' "$@"; echo
  [ "$DRY" = 1 ] || "$@"
}

chat_id() {  # chat id of a role label in the worktree, empty if none
  band chats list "$WT" --output json 2>/dev/null \
    | jq -r --arg r "$1" '[.chats[] | select(.labels.role == $r)][0].id // empty'
}

if [ "$CMD" = status ]; then
  run band chats list "$WT"; run band agents list "$WT"; exit 0
fi

if [ "$CMD" = watch ]; then
  # One `band chats watch` per role, each line prefixed with the role. Shows what the agents say,
  # every permission request (the human decision points) and the token meter (usage_update).
  for role in planner builder reviewer security; do
    id=$(chat_id "$role")
    [ -n "$id" ] || { echo "no $role chat yet; run the script without arguments first" >&2; exit 1; }
    echo "+ band chats watch $id   # $role"
    [ "$DRY" = 1 ] && continue
    # watch ends when a turn ends, so loop to follow the chat across turns
    ( while :; do band chats watch "$id" 2>/dev/null | jq --unbuffered -r --arg r "$role" '
        if .type == "update" and .update.sessionUpdate == "agent_message_chunk" then "[\($r)] \(.update.content.text // "")"
        elif .type == "update" and .update.sessionUpdate == "usage_update" and (.update.used != null) then "[\($r)] tokens in context: \(.update.used)/\(.update.size)"
        elif .type == "permission" then "[\($r)] >>> WAITING FOR HUMAN: \(.request.toolCall.title)"
        elif .type == "turn-ended" then "[\($r)] --- turn ended"
        else empty end'; sleep 2; done ) &
  done
  [ "$DRY" = 1 ] || { trap 'kill 0' INT TERM; wait; }
  exit 0
fi

# 1. Register the repo (Band also lists the main checkout as worktree hackwithbay-main).
if [ "$DRY" = 1 ] || ! band repos list --output json | jq -e --arg n "$REPO" '.repos[] | select(.name == $n)' >/dev/null; then
  run band repos add "$REPO_PATH"
fi

# 2. One worktree for the task. No --prompt, so creating it starts no agent. Idempotent.
run band worktrees create "$REPO" "$BRANCH"
WT_PATH="$HOME/.band/worktrees/$REPO/$BRANCH"

# 3. A git worktree only holds committed files. Bring it up to main, or stop if main lacks the code.
if [ "$DRY" = 1 ] || [ ! -f "$WT_PATH/app/policy.py" ]; then
  if [ "$DRY" = 1 ] || git -C "$REPO_PATH" cat-file -e main:app/policy.py 2>/dev/null; then
    run git -C "$WT_PATH" merge --ff-only main
  else
    echo "STOP: main has no app/policy.py yet. The app code is uncommitted, so the worktree only" >&2
    echo "has README.md. Commit the work to main (your call), then re-run this script." >&2
    exit 1
  fi
fi

# 4. The four role chats, found by label so a re-run reuses them. All in Manual mode
#    ("always ask before making changes"): every shell command, including each handoff, waits for a Yes.
for spec in Planner:planner Builder:builder Reviewer:reviewer Security:security; do
  name=${spec%%:*}; role=${spec##*:}
  if [ "$DRY" = 1 ] || [ -z "$(chat_id "$role")" ]; then
    run band chats create "$WT" --name "$name" --agent claude-code --model "$MODEL" --mode default \
      --label "role=$role" --label demo=earshot
  fi
done

if [ "$DRY" = 1 ]; then
  P='<planner id>'; B='<builder id>'; R='<reviewer id>'; S='<security id>'
else
  P=$(chat_id planner); B=$(chat_id builder); R=$(chat_id reviewer); S=$(chat_id security)
fi
SEND="band chats send <CHAT> --worktree $WT --mode default --model $MODEL --message"

# 5. Kickoff goes to the Planner only. Every later message is sent by an agent, not by this script.
# read -d '' rather than $(cat <<EOF): macOS bash 3.2 misparses apostrophes in a heredoc inside $()
IFS= read -r -d '' KICKOFF <<EOF || true
You are the PLANNER in a four-agent team working in this Band worktree on Earshot (read CLAUDE.md).
Teammates are other Band chats. You reach one by running this shell command, nothing else:
  $SEND "<text>"
Chat ids: Planner $P, Builder $B, Reviewer $R, Security $S.

Task: web leads (signals with kind "web", from app/scout_web.py) that have no named author must never
be released; app/policy.py decide() must hold them with a clear reason, plus a test in tests/.
1. Read app/policy.py and app/scout_web.py. Write a plan of at most 8 lines: the exact rule, files, test.
2. This changes what Earshot may send, so it needs the human. End your plan with the line
   HUMAN DECISION: approve the handoff to Builder (Yes) or reject it (No).
3. Then hand the plan to the Builder with the send command (chat $B). The human answers the
   permission prompt on that command; that prompt is the decision. If it is rejected, stop.
The Builder's brief must say: implement only the plan, run the policy tests, then send the diff
summary to Reviewer ($R) and to Security ($S). Their briefs must say: review git diff, reply in at
most 5 lines with PASS or BLOCK and why, and send that verdict back to the Planner ($P).
4. When both verdicts reach you, post a 3-line summary and stop. Do not commit or push.
EOF
if [ "$DRY" = 1 ] || [ "$(band chats list "$WT" --output json | jq -r --arg id "$P" '.chats[] | select(.id == $id) | .labels.kickoff // empty')" != sent ]; then
  run band chats send "$P" --worktree "$WT" --mode default --model "$MODEL" --message "$KICKOFF"
  run band chats label "$P" kickoff=sent
else
  echo "kickoff already sent to Planner $P; not sending again"
fi

cat <<EOF

Next:
  - Open the Band app, worktree "$BRANCH": the four panes are Planner, Builder, Reviewer, Security.
  - Answer each Yes/No prompt in the panes. The Planner -> Builder one is the human decision.
  - Or follow everything here: $0 watch
EOF
