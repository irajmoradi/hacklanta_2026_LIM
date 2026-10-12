---
id: FINAL-1
branch: ext/FINAL-1
allowed_paths: [full_app/server/**, full_app/pipeline/**, full_app/app.py, full_app/reactions/**, full_app/render/**, full_app/planner/**, full_app/sam/**, full_app/production_frontend/**, full_app/tests/**, demo_video/final/**, docs/pipeline.md, docs/api.md, docs/planner.md, docs/reactions.md, docs/final_render.md]
---
# FINAL-1: Chaos/seed over HTTP + UI, bigger head reactions, and the final combined render

`Extension` now has FX-2 (seeded event-tied VFX/SFX stacks + chaos; see `demo_video/fx2/REPORT.md` "integrator handoff"), WIRE-1 (Full experience
preset, privacy opt-in; `docs/wiring_audit.md`), REACT-2 (head-only matted reactions; `docs/reactions.md`), FIX-5. (DEADLOCK-1 is running in
parallel on `full_app/profiles/**` and `full_app/signals/**`: do not edit those.)
1. **Chaos/seed end to end:** apply FX-2's handoff: allowlist and forward `chaos` (0-1) and `seed` (+ the complete event list) through the API
   (`server/**`, `pipeline/extensions.py::planner_plan`), add them to the planning invalidation keys in `server/queue.py`, return the seed used
   in the job status. UI: a **Chaos** slider (0-100%) in edit settings and a **🎲 Reroll** button on the review screen that replans with a new
   seed (no paid calls; reuse analysis) and shows the new effects. Tests for API forwarding, invalidation, reproducibility, reroll.
2. **Reaction size/placement:** head-only reactions currently render too small (about 7% of frame height). Default to a large, readable head
   (~28-35% of frame height in 16:9, ~22-28% of width in 9:16, scaled for 1:1), anchored bottom corner, overlapping the frame edge a little like a
   streamer cam, with the existing shadow/bounce/bob/name tag; add a `reaction_size` option (small/medium/large, default large). Tests.
3. **Mean mode may use explicit reaction clips** (pack clips flagged `explicit: true`, style `genalpha`); nice mode prefers non-explicit but
   may use genalpha. Add a `clean` option that excludes explicit clips. Reactions should rotate across all four speakers and vary labels per event.
4. **SAM:** SAM 2.1 small weights are at runner 1 `/srv/models/sam2.1_hiera_small.pt` and torch/sam2 may be installed in the runner venv
   `/srv/lim/lim/.venv` (check with `python -c "import sam2"`; if missing, install CPU torch + `full_app/sam/requirements-local.txt` into the
   venv your remote_run uses). Run the final render with `SAM_BACKEND=local`, `SAM2_CHECKPOINT=/srv/models/sam2.1_hiera_small.pt`, the matching
   config, so the spotlight actually renders on the key kill (report whether it did; warnings otherwise).
5. **Final combined render** on runner 1 from the saved DEMO-02 full-match analysis (`/srv/demo_out/demo02/`; no re-analysis; at most 5 Gemini
   calls): Full experience + FX-2 stacks + chaos (nice 0.35, mean 0.6) + **no privacy blur** + large head-only reactions from all 4 of us
   (`/srv/packs/team`, mattes present) + SAM spotlight + music/beat sync + varied transitions + intro/outro: landscape 60 s, vertical 30 s,
   mean vertical 30 s, plus one **reroll** of the mean vertical with a different seed. Outputs `/srv/demo_out/final/` + local
   `demo_video/final/out/` (gitignored), Discord copies under 20 MB, contact sheet, per-clip table (events, VFX, SFX, reaction speaker/line).
   Visually inspect frames: heads big and clean, no blur boxes, effects visible. Full suite green on the runner.
