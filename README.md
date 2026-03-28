# AI Gameplay Clip Editor

> **HackLanta 2026** — Automatically turn raw gameplay footage into highlight montages using AI.

Upload a gameplay video. Gemini AI finds the best kills and worst deaths. Pick a style. FFmpeg renders a montage with effects, text overlays, and sound — all in minutes.

https://github.com/user-attachments/assets/placeholder

## What It Does

1. **Upload** any gameplay recording (Valorant, Overwatch 2, Deadlock, etc.)
2. **AI analyzes** the video and identifies highlights and lowlights — with game-specific death/spectating detection
3. **Choose your style** — Hype Montage, Clean Edit, Meme Edit, or Cinematic
4. **Nice or Mean mode** — hype reel of your best plays, or roast reel of your worst deaths
5. **AI plans the edit** — selects clips, assigns visual effects, text overlays, and sound effects
6. **FFmpeg renders** the final montage with NVENC GPU acceleration

### Features

- **35+ Visual Effects** — blur, sharpen, color grading, shake, glitch, chromatic aberration
- **9 Text Overlays** — HIGHLIGHT, FAIL, CLUTCH, RIP, BRUH, NICE, GG, LOL, OOF (huge, TikTok-ready)
- **49 Sound Effects** — roblox death, spongebob fail, anime wow, JoJo's, za warudo, clown music, and more
- **AI Thumbnails** — auto-generated intro and outro images
- **Multiple VFX + SFX per clip** — stack effects and time multiple sounds to the action
- **Video splitting** — analyze long videos in parallel (1/2/3/4 splits)
- **Structured AI output** — Pydantic schemas enforce valid JSON from Gemini

## Quick Start

```bash
# Clone
git clone https://github.com/irajmoradi/hacklanta_2026_LIM.git
cd hacklanta_2026_LIM/full_app

# Install
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Set your API key (free at https://aistudio.google.com/apikey)
echo "GEMINI_API_KEY=your_key_here" > ../.env
# Or skip this — the app will prompt you in the browser

# Run
python app.py
# Open http://localhost:8000
```

### Prerequisites

| Dependency | Install |
|---|---|
| **Python 3.10+** | [python.org](https://python.org) |
| **FFmpeg** | `winget install FFmpeg` (Win) / `brew install ffmpeg` (Mac) / `sudo apt install ffmpeg` (Linux) |
| **Gemini API Key** | Free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |
| **Node.js 18+** | Only needed for the production frontend |

### Production Frontend (optional)

```bash
cd full_app/production_frontend
npm install
npm run dev
# Open http://localhost:5173 (backend must be running on :8000)
```

## Tech Stack

| Layer | Technology |
|---|---|
| **AI** | Google Gemini API (video analysis, edit planning, image generation) |
| **Rendering** | FFmpeg with NVENC GPU acceleration |
| **Backend** | Python, Flask |
| **Frontend (dev)** | Vanilla HTML/JS |
| **Frontend (prod)** | React 18, Vite 6, Tailwind CSS 4, shadcn/ui |
| **Schema** | Pydantic models + Gemini structured output |

## Project Structure

```
full_app/
├── app.py                    # Flask backend — full pipeline
├── frontend/                 # Dev frontend (vanilla HTML/JS)
├── production_frontend/      # Production frontend (React + Vite)
├── models/
│   ├── effects.py            # 35+ VFX + 49 SFX registries
│   └── schemas.py            # Pydantic data models
├── services/
│   ├── gemini_client.py      # Gemini API wrapper
│   ├── ffmpeg_runner.py      # FFmpeg rendering engine
│   └── probe.py              # Video metadata extraction
├── prompts/                  # AI prompt templates
├── sfx/                      # 50 sound effect files (included)
└── requirements.txt
```

## How It Works

```
┌──────────┐     ┌───────────┐     ┌──────────┐     ┌──────────┐
│  Upload   │────>│  Analyze  │────>│   Plan   │────>│  Render  │
│  Video    │     │  (Gemini) │     │ (Gemini) │     │ (FFmpeg) │
└──────────┘     └───────────┘     └──────────┘     └──────────┘
                  Splits video      Selects clips     Applies VFX,
                  into segments,    assigns VFX,      SFX, text,
                  finds highlights  SFX, and text     transitions,
                  and lowlights     per edit style     concatenates
```

## Team

Built at HackLanta 2026.
