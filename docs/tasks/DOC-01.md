---
id: DOC-01
branch: ext/DOC-01
allowed_paths: [README.md, docs/README_ASSETS/**, docs/architecture.md, docs/quickstart.md]
---
# DOC-01: Docs: README + architecture + quick start for the Extension
Rewrite the top-level README.md for the Extension branch: what the app does now (before vs after table), a mermaid architecture diagram
(ingest -> signals (scene/audio/motion/OCR/audio AI/chat/V-JEPA) -> VLM window scoring (Gemini or local VLM) + fusion -> planner v2 -> render v2 (FX,
captions, reframe, SAM, privacy, reactions, narration, music) -> share kit; plus the job queue/SSE API, Discord bot, auto-capture), supported games
(Valorant, Overwatch 2, Deadlock, League), quick start (local + Docker), a configuration table of every env var and flag (read the code and docs/*.md),
cost notes, research background (docs/RESEARCH.md), credits/licensing (bundled meme SFX are third-party; model licenses). Write docs/architecture.md
and docs/quickstart.md. Verify every command and env var name against the code; no secrets.
