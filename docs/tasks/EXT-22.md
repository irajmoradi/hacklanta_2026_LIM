---
id: EXT-22
branch: ext/EXT-22
allowed_paths: [full_app/music/**, full_app/tests/**, docs/music.md]
---
# EXT-22: Music beds: procedural + library
Build `full_app/music/`: background music for montages without copyright problems. (1) A **procedural music generator** (numpy synthesis or
pretty-midi + a bundled tiny CC0 soundfont/synth) producing energetic or chill loops at a target BPM and length with intro/drop/outro sections whose
drop lines up with the montage climax; (2) a manifest format for a user-provided royalty-free library (tags: energy, mood, BPM, license), with
selection by style/mode; (3) BPM/energy analysis for user tracks (librosa optional, fallback autocorrelation). `music.pick_or_generate(style, length,
climax_at) -> MusicBed{path, bpm, beats[], sections}`. Tests: generated audio length/BPM within tolerance, drop position, manifest selection.
Write docs/music.md (licensing notes).
