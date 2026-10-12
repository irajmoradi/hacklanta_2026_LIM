# AUDIT-2: feature verification

Audit in progress against Extension `8db1f6d` on task branch `ext/AUDIT-2`.
This is a report-only task; no product changes are made.

The audit distinguishes stock API, the React development frontend, the legacy
frontend served by `python app.py`, and separate libraries/CLIs. A module's
presence or a mocked test is not proof that it appears in a real montage.

Evidence is generated under `demo_video/audit/out/` (ignored): a fresh four-minute
trim selected by high-energy audio, stock HTTP upload/analyze/plan/render, three
Full experience exports, plan and warning snapshots, event-time frames, audio
metadata, share-kit metadata, and browser screenshots. Live analysis is bounded
to one job with a 25-call budget; export plans reuse the analysis.

Initial confirmed gaps:

- `full_app/server/api.py:41`: the default server serves the legacy frontend;
  React settings, review timeline and Director require a separate Vite frontend.
- `full_app/server/validation.py:153`: `chaos` and `seed` are not HTTP options
  in the audited snapshot. FINAL-1 has a separate, unmerged implementation.
- `full_app/production_frontend/src/components/EditSettings.tsx:33`: Full
  experience does not enable window scoring, whose UI default is false.
- `full_app/pipeline/extensions.py:309`: the stock share-kit call supplies no
  image-generation client. Nano Banana thumbnails cannot execute on this path.
- SAM weights exist on runner 1, but `sam2` is not importable in this task's
  base-install virtualenv; a weights file alone does not enable SAM inference.

The completed report will replace this checkpoint with the promise matrix,
measured evidence, exact test results, and prioritized fix splits.
