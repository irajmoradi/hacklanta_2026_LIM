---
id: AGENT-02
branch: ext/AGENT-02
allowed_paths: [full_app/production_frontend/**, docs/frontend_agent.md]
---
# AGENT-02: Editor-agent UI (chat-to-edit + live edit trace)

AGENT-01 (running in parallel) adds an agentic editor: `POST /api/jobs/<id>/agent {instruction}` returns `{plan, plan_version, trace:[{step,
tool, args, rationale, diff}]}` and streams `agent_step` SSE events with the same step shape on the job's existing event stream; undo via
`POST /api/jobs/<id>/agent/undo` returning the previous `{plan, plan_version}`. Build the frontend against that contract (typed client in
`src/api.ts`, mock it in tests; it will be wired once AGENT-01 merges):
- A **"Director" chat panel** on the review screen: instruction box with quick chips ("Shorter (30 s)", "More hype", "Roast my deaths",
  "Cut slow parts", "Add reactions"), a message thread, and an **edit trace** that animates each agent step as it arrives (tool icon, one-line
  rationale, the clip affected highlighted on the timeline, a small before/after diff), plus Undo and "Apply & render".
- Timeline reacts live to plan changes (clips sliding/trim animations, under 150 ms, reduced-motion respected).
- Loading/error/budget-exhausted states; keyboard: Enter sends, Ctrl+Z undo.
Component tests with the mocked API (vitest), build passes (`tools/remote_run.sh` for heavy commands as AGENTS.md says), Playwright
screenshot of the panel mid-trace with mocked events. Keep the existing visual style; no new heavy dependencies.
