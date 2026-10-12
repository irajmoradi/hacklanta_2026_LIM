#!/usr/bin/env bash
# Usage: tools/dispatch.sh <TASK_ID> <worktree_dir>   (integrator only; logs to ../lim-reports/<TASK>)
set -u
TASK="$1"; WT="$2"; LOG="/c/Users/mourn/Downloads/lim-reports/$TASK"; mkdir -p "$LOG"
PROMPT="You are a Codex worker on the AI Gameplay Clip Editor (hacklanta_2026_LIM), Extension sprint. Your task record is docs/tasks/$TASK.md in this worktree; read it, AGENTS.md and docs/RESEARCH.md first, then complete it fully and autonomously (no questions; make reasonable choices and note them). A Gemini key for optional live smoke tests is GOOGLE_API_KEY in /c/Users/mourn/Downloads/hacklanta/.env (Vertex AI express: genai.Client(vertexai=True, api_key=...)); read it at runtime only, never copy it into files, at most 3 live calls. Work only inside allowed_paths. Run tests with tools/remote_run.sh. Commit to the current branch at milestones. End with the final report required by AGENTS.md."
echo "$(date -Is) start $TASK in $WT" >> "$LOG/events.txt"
codex exec -m "${MODEL:-gpt-6-astra}" -C "$WT" --dangerously-bypass-approvals-and-sandbox \
  -c model_reasoning_effort="${EFFORT:-medium}" \
  --json -o "$LOG/final.md" "$PROMPT" < /dev/null > "$LOG/events.jsonl" 2> "$LOG/stderr.txt"
echo "$(date -Is) exit $? $TASK" >> "$LOG/events.txt"
