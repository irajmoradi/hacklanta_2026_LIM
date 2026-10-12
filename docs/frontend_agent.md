# AGENT-02: Director UI

Branch: `ext/AGENT-02`. Implementation milestone: `191b55a`.

The review screen now includes Director for the jobs backend: five quick instruction chips, a conversation thread, Enter to send (Shift+Enter adds a line), streaming tool traces with rationale and Before/After values, Undo, and Apply & render. Ctrl+Z / Cmd+Z undo an agent edit outside editable fields; native text undo remains available inside them. Requests disable conflicting editing and rendering controls. Failures restore the pre-request timeline and retain the instruction for retry. Budget errors have a dedicated message and do not disable undo/render.

Source ranges and the new montage-order track animate left/width changes in 120 ms. Reduced-motion preferences disable both those transitions and trace entry animation. Streamed steps highlight the affected clip. The final response sets the authoritative plan; render retains its effects and ordering. The existing SSE connection carries agent_step events, and POST trace entries fill in missed events without duplicating received step numbers. Polling cannot overwrite provisional clip changes during an edit.

## Contract and choices

- `EditorApi.agent(id, instruction)` POSTs `{instruction}` to `/api/jobs/<id>/agent` and reads `{plan, plan_version, trace}`.
- `EditorApi.undoAgent(id)` POSTs to `/api/jobs/<id>/agent/undo` and reads `{plan, plan_version}`.
- Plans use the existing `segments` schema with `source_start` and `source_end`. Segment `clip_id` / `id`, title, and overlapping source ranges map plans back to review clips.
- The task does not specify the internal diff shape. Live previews accept `diff.after.segments` for a full plan, or `diff.after` containing source_start/source_end/title for a segment. Segment selection accepts zero-based `args.segment_index`, `args.clip_index`, or `args.clip_id` / `diff.clip_id`. Other diffs remain visible in the trace; the final returned plan always updates the timeline.
- HTTP 429 or error code `budget_exhausted` displays the budget state. Other errors retain their backend message.
- Undo availability counts edits made in this mounted Director session; historical undo availability is not supplied by the contract. Chat is session-local.
- Director is hidden for the legacy and fixture-demo adapters, which do not implement these endpoints. The mocked browser test demonstrates it without a backend or credentials.
- No new dependencies, live API calls, or secret reads. No pushes or merges.

## Files changed

All frontend paths below are under `full_app/production_frontend/`:

- `src/api.ts`: typed agent client, structured errors, plan-to-clip conversion, agent SSE dispatch, authoritative render support.
- `src/App.tsx`: Director integration, provisional updates, rollback, render preservation.
- `src/components/Director.tsx`: chat, trace, shortcuts, loading/error/undo states.
- `src/components/ReviewTimeline.tsx`: highlighted clips and animated montage-order track.
- `src/styles/editor.css`: responsive panel and motion styles.
- `src/agentApi.test.ts`, `src/components/Director.test.tsx`: mocked API/component coverage.
- `e2e/director.spec.ts`: mocked SSE/HTTP browser test and screenshot.
- `director-mid-trace.png`: reviewed Playwright screenshot from the Linux runner.
- `docs/frontend_agent.md`: this handoff (repository root).

## Verification

Run from the worktree root with Git Bash (the Windows tool invocation prepended `bash`):

1. `tools/remote_run.sh 'cd full_app/production_frontend && npm ci --silent && npm run build && npm test'`: exit 0; build and 27 existing tests passed.
2. `tools/remote_run.sh 'cd full_app/production_frontend && npm run build && npm test && npx playwright test e2e/director.spec.ts'`: first run exit 1 (32/33 tests; keyboard handler assumed an Element target). After fixing the target guard, exit 0: build, 33 tests, and 1 Director browser test passed.
3. `tools/remote_run.sh 'cd full_app/production_frontend && npm run build && npm test && npm run test:browser'`: first run exit 1 (build and 33 tests passed; 2/3 browser tests passed; existing encoding assertion caught a question mark in the new timeline label). Final run exit 0: build, all 33 tests, and all 3 browser tests passed.
4. `git diff --check`: exit 0.

The browser suite uses mocked jobs/agent calls and synthetic ffmpeg footage in the existing gameplay test. The Director test asserts streaming trim updates, highlight, reduced motion, and preservation of the returned speed effect in the render payload. The final screenshot was copied back from the runner and visually inspected: both diff columns are visible and panel content fits.

## Try it / remaining integration

After AGENT-01 is integrated, start the normal jobs backend and frontend, upload gameplay, analyze, then use Director below the timeline. Choose a chip, press Enter, review the trace, Undo if needed, and Apply & render. To exercise the mocked flow immediately, run the Director Playwright command above.

Real AGENT-01 integration remains untested here (zero live calls required). If its diff payload differs from the documented supported shapes, adapt the provisional-preview mapping; final plan rendering and raw diff display already use the required contract. The backend must keep agent mutation/undo transactional and return an authoritative plan on success.
