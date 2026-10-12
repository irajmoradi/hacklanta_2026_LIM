---
id: AGENT-01
branch: ext/AGENT-01
allowed_paths: [full_app/editor_agent/**, full_app/tests/test_editor_agent*.py, full_app/server/**, full_app/app.py, docs/editor_agent.md]
---
# AGENT-01: Agentic video editor (plan → watch draft → critique → revise)

Today the pipeline is a fixed sequence (signals → window scoring → planner → render). Make the editing step **agentic**:
a Gemini editor agent (gemini-3.5-flash-lite via `services/provider_config.py`; Vertex express) with function-calling **tools** over the
job's existing analysis, iterating until the cut is good or the budget is used.

1. `full_app/editor_agent/`: tool layer (pure Python, typed with Pydantic, unit-tested): `list_candidates(filter)`, `inspect_window(t0,t1)`
   (returns stored scores/signals/transcript + optionally a low-res keyframe strip), `add_clip`, `remove_clip`, `trim_clip`, `reorder`,
   `set_transition`, `add_reaction(clip, label, speaker)`, `add_caption`, `set_music`, `render_preview()` (fast low-res proxy render using
   the perf/ proxy path), `watch_preview()` (uploads the proxy to Gemini once and returns a structured critique: pacing, dead air, repeated
   kills, missing context, reaction timing), `finish(summary)`.
2. Agent loop: goal from the user's brief + mode (nice/mean) + target length/preset; operates on the planner v2 plan as its starting draft;
   max steps and a hard per-job call budget (reuse `call_budget.py`; default 12 calls, configurable); every step logged as an **edit trace**
   (tool, args, rationale, diff of the plan) streamed over the existing SSE as `agent_step` events; deterministic fallback = planner v2 output.
3. **Chat-to-edit** API: `POST /api/jobs/<id>/agent` `{instruction}` ("make it 30 s", "more roasts on Iraj's deaths", "cut the slow buy
   phase") runs the agent for a few steps from the current plan and returns the new plan + trace; undo = previous plan version.
4. Tests with a scripted fake model (no live calls): tool validation, budget enforcement, invalid tool args rejected and fed back to the
   model, trace/undo, SSE events. Full suite green on the runner.
5. One **live** smoke run on runner 1 (at most 12 Gemini calls, `GOOGLE_API_KEY` env-only from /c/Users/mourn/Downloads/hacklanta/.env)
   using a saved analysis of the Valorant demo footage in `/srv/demo_out/demo01/` or `/srv/demo_out/demo02/` if present (use their
   stored candidates/scores; if no reusable analysis is stored, trim the first 6 min of `/srv/demo_in/valorant_phoenix_44k.mp4`). Report the
   trace and before/after plan. Write docs/editor_agent.md. Frontend wiring is AGENT-02 (document the API + event shapes clearly).
