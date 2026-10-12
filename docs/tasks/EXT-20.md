---
id: EXT-20
branch: ext/EXT-20
allowed_paths: [full_app/privacy/**, full_app/tests/**, docs/privacy.md]
---
# EXT-20: Privacy: blur usernames, chat and personal info
Build `full_app/privacy/` so montages are safe to share: detect and blur **other players' usernames** (kill feed, scoreboard, nameplates), text
chat boxes, party/voice overlays, Discord/OBS notification pop-ups, and webcam overlays if requested; per game regions come from profiles (EXT-09
`profiles` if present, else built-in defaults for Valorant/OW2/Deadlock/League); OCR-driven detection (RapidOCR/Tesseract) with temporal smoothing,
plus manual blur boxes from the API. Option to keep the uploader's own name. Output a blur track the renderer applies (ffmpeg boxblur/delogo
with enable expressions). Tests on synthetic frames with drawn usernames/chat text: boxes found, blur applied only where expected, own-name
whitelist respected. Write docs/privacy.md.
