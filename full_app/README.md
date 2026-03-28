# AI Gameplay Clip Editor

AI-powered video editor that automatically finds highlights and lowlights in gameplay footage, applies effects and sound, and renders a montage — all using Gemini AI + FFmpeg.

## Features

- **AI Analysis**: Gemini AI watches your gameplay and identifies the best (and worst) moments
- **Nice/Mean Mode**: "Nice" makes a hype reel of your best plays. "Mean" roasts your worst deaths
- **35+ Visual Effects**: Blur, sharpen, color grading, text overlays (BRUH, FAIL, CLUTCH, etc.)
- **49 Sound Effects**: Roblox death, spongebob fail, anime wow, JoJo's, and more
- **4 Edit Styles**: Hype Montage, Clean Edit, Meme Edit, Cinematic
- **AI Thumbnails**: Auto-generated intro and outro images via Gemini image generation
- **GPU Accelerated**: NVENC encoding on NVIDIA GPUs
- **Game-Specific Detection**: Recognizes Valorant, Overwatch 2, and Deadlock death/spectating screens

## Quick Start

### Prerequisites

- **Python 3.10+**
- **FFmpeg** (must be in PATH)
- **Gemini API Key** (free at [aistudio.google.com/apikey](https://aistudio.google.com/apikey))
- **Node.js 18+** (only for production frontend)

### Install FFmpeg

**Windows:**
```bash
winget install FFmpeg
# OR download from https://ffmpeg.org/download.html and add to PATH
```

**macOS:**
```bash
brew install ffmpeg
```

**Linux (Ubuntu/Debian):**
```bash
sudo apt install ffmpeg
```

### Setup

```bash
# Clone the repo
git clone https://github.com/irajmoradi/hacklanta_2026_LIM.git
cd hacklanta_2026_LIM/full_app

# Create virtual environment (recommended)
python -m venv .venv

# Activate it
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt
```

### Configure API Key

**Option A: .env file (recommended)**
```bash
# Create .env file in the repo root (one level up from full_app/)
echo "GEMINI_API_KEY=your_key_here" > ../.env
```

**Option B: Enter in the app**
Skip the .env file — the app will prompt you for your API key in the browser.

### Run

```bash
# From the full_app/ directory
python app.py
```

Open **http://localhost:8000** in your browser.

### Production Frontend (optional)

The production frontend uses React + Tailwind + shadcn/ui for a polished look:

```bash
cd production_frontend
npm install
npm run dev
```

Open **http://localhost:5173** (make sure the backend is running on port 8000).

## How It Works

1. **Upload** — Drop your gameplay .mp4 into the browser
2. **Analyze** — Gemini AI splits the video and finds highlights/lowlights in parallel
3. **Plan** — Gemini selects the best clips and assigns VFX + SFX based on your chosen style
4. **Render** — FFmpeg applies all effects, overlays sound, and concatenates into the final montage

## Project Structure

```
full_app/
├── app.py                  # Flask backend (API + pipeline)
├── frontend/               # Dev frontend (vanilla HTML/JS)
├── production_frontend/    # Production frontend (React + Vite)
├── models/
│   ├── effects.py          # VFX + SFX registries
│   └── schemas.py          # Pydantic data models
├── services/
│   ├── gemini_client.py    # Gemini API wrapper
│   ├── ffmpeg_runner.py    # FFmpeg rendering engine
│   └── probe.py            # FFprobe metadata extraction
├── prompts/
│   ├── clip_finder.txt     # Stage 1 analysis prompt
│   └── editor.txt          # Stage 2 planning prompt
├── sfx/                    # Sound effect mp3 files (included)
└── requirements.txt
```

## Tech Stack

- **Backend**: Python, Flask
- **AI**: Google Gemini API (video analysis, edit planning, image generation)
- **Rendering**: FFmpeg with NVENC GPU acceleration
- **Frontend (dev)**: Vanilla HTML/JS
- **Frontend (prod)**: React 18, Vite 6, Tailwind CSS 4, shadcn/ui, Radix UI

## Troubleshooting

**"No Gemini API key configured"** — Set `GEMINI_API_KEY` in `.env` or enter it in the browser.

**"FFmpeg not found"** — Install FFmpeg and make sure `ffmpeg` is in your system PATH.

**"Quota exceeded"** — The app auto-deletes uploaded files from Gemini after analysis. If you hit the 20GB storage cap, wait 48h for auto-cleanup or use a new API key.

**Slow rendering** — NVIDIA GPU with NVENC is auto-detected for faster encoding. Without it, falls back to CPU (libx264).

**Windows font issues with text overlays** — The text effects use DejaVu Sans Bold. If not available, install it or the text overlays will be skipped silently.
