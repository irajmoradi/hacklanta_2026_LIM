---
id: EXT-09
branch: ext/EXT-09
allowed_paths: [full_app/profiles/**, full_app/prompts/games/**, full_app/tests/**, docs/game_profiles.md]
---
# EXT-09: Game profiles for Valorant, Overwatch 2, Deadlock and League of Legends
Owner: "Make sure it works for Deadlock, Overwatch, Valorant, and maybe League." Other agents are building the pipeline in parallel
(EXT-01 `full_app/signals/` candidate detection with HUD/kill-feed OCR; EXT-02 VLM window scoring in `full_app/services/`). You own a
**shared game-profile package** they (and the integrator) can import:
- `full_app/profiles/` with one profile per game: `valorant`, `overwatch2`, `deadlock`, `league_of_legends`, plus `generic`.
  Each profile (Pydantic/dataclass, data-driven YAML or JSON is fine) defines:
  - **HUD regions** as normalized boxes (kill feed, death banner / "killed by" panel, spectating indicators, round/score banner,
    multikill / ace / "shutdown" / "PENTAKILL" announcements, health bar region) for 16:9; note how 16:10 / ultrawide shift them.
  - **OCR keyword sets** per event (kill, death, assist, multikill, ace/teamwipe/pentakill, round won/lost, objective taken
    (Baron/Dragon/Tower for League; Patron/urn for Deadlock; payload/point for OW2; spike plant/defuse for Valorant)), with
    multilingual variants where common (e.g. Portuguese/Spanish already appear in the current prompt).
  - **Alive / dead / spectating rules** (what the existing `prompts/clip_finder.txt` describes for Valorant/OW2/Deadlock), and for
    **League** a top-down MOBA: no crosshair; death = grey screen + respawn timer; "You have been slain"; spectating = camera locked on an ally after death.
  - **Highlight definitions** per game (e.g. League: multikills, outplays at low HP, steals; OW2: team kills, ult combos; Valorant: clutches, aces, multi-kills; Deadlock: multi-kills, souls/urn plays) and lowlight/roast definitions.
  - Signal weight overrides for the fusion step (e.g. League relies more on announcements + OCR, less on motion energy).
- **Auto-detect the game** from a few sampled frames: OCR/keyword + simple HUD-layout heuristics, with an optional VLM fallback hook;
  `profiles.detect_game(video_path) -> (name, confidence)`.
- **Prompt fragments** per game in `full_app/prompts/games/<game>.txt` that the VLM window-scoring prompt can include
  (alive rules, what counts as a highlight/lowlight, reaction-label hints).
Tests (no network, no copyrighted footage): synthetic frames rendered with ffmpeg/PIL drawing each game's banners/text in the profile regions
(e.g. "PENTAKILL", "ELIMINATED BY", "KILLED BY", "ACE") and asserting OCR-keyword matching + region math + detect_game on synthetic
layouts. Write docs/game_profiles.md (per-game summary + how to add a game).
