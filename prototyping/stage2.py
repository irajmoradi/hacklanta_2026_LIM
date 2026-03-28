"""
Stage 2 — Effect Planning via Gemini.
Takes clip analysis from stage 1, available effects lists, and a task prompt,
then asks Gemini to plan video/sound effects for each clip.

Usage:
    pip install -r requirements.txt
    python stage2.py

Expects GEMINI_API_KEY in ../.env or environment.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from google import genai

app = Flask(__name__)

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Load default clip analysis from testoutput.txt if it exists
DEFAULT_CLIPS = ""
testoutput = Path(__file__).resolve().parent.parent / "testoutput.txt"
if testoutput.exists():
    DEFAULT_CLIPS = testoutput.read_text()

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Stage 2 — Effect Planner</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, -apple-system, sans-serif; background: #0f0f0f; color: #e0e0e0; min-height: 100vh; display: flex; justify-content: center; padding: 2rem; }
  .container { max-width: 960px; width: 100%; }
  h1 { font-size: 1.5rem; margin-bottom: 0.3rem; color: #8ab4f8; }
  .subtitle { color: #888; font-size: 0.85rem; margin-bottom: 1.5rem; }
  .model-badge { font-size: 0.8rem; background: #1e3a5f; padding: 0.2rem 0.6rem; border-radius: 4px; margin-left: 0.5rem; vertical-align: middle; }

  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1rem; }
  .box { display: flex; flex-direction: column; }
  .box.full { grid-column: 1 / -1; }
  label { font-size: 0.85rem; font-weight: 600; color: #8ab4f8; margin-bottom: 0.3rem; }
  label .hint { font-weight: 400; color: #666; }

  textarea { width: 100%; background: #1a1a1a; color: #e0e0e0; border: 1px solid #333; border-radius: 8px; padding: 0.75rem; font-size: 0.85rem; resize: vertical; font-family: 'Cascadia Code', 'Fira Code', monospace, system-ui; line-height: 1.5; }
  textarea:focus { outline: none; border-color: #8ab4f8; }
  .tall { min-height: 220px; }
  .medium { min-height: 120px; }

  button { background: #8ab4f8; color: #0f0f0f; border: none; padding: 0.7rem 1.5rem; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; width: 100%; }
  button:hover { background: #aecbfa; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }

  .status { color: #888; font-size: 0.85rem; margin-top: 0.5rem; }
  .error { color: #f28b82; }
  .result { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 1rem; margin-top: 1rem; white-space: pre-wrap; line-height: 1.6; font-size: 0.9rem; font-family: 'Cascadia Code', 'Fira Code', monospace, system-ui; }
</style>
</head>
<body>
<div class="container">
  <h1>Stage 2 — Effect Planner <span class="model-badge" id="model-name"></span></h1>
  <p class="subtitle">Feed clip analysis + available effects to Gemini and get an editing plan</p>

  <div class="grid">
    <div class="box">
      <label>Clip Analysis <span class="hint">(from Stage 1)</span></label>
      <textarea id="clips" class="tall" placeholder="Paste clip analysis JSON from stage 1..."></textarea>
    </div>

    <div class="box">
      <label>Task Prompt <span class="hint">(what should Gemini do?)</span></label>
      <textarea id="task" class="tall" placeholder="e.g. For each clip, pick the best video and sound effects to make an exciting montage...">For each clip, assign the most fitting video effects and sound effects from the provided lists. Output JSON with each clip's start/end times, description, chosen video effect(s), and chosen sound effect(s). Explain briefly why each effect fits.</textarea>
    </div>

    <div class="box">
      <label>Available Video Effects <span class="hint">(one per line)</span></label>
      <textarea id="vfx" class="medium" placeholder="e.g. zoom_in, slow_motion, flash...">slow_motion
speed_ramp
zoom_in
zoom_out
shake
flash_white
flash_black
color_boost
desaturate
vignette
glitch
chromatic_aberration
motion_blur
radial_blur
letterbox_cinematic</textarea>
    </div>

    <div class="box">
      <label>Available Sound Effects <span class="hint">(one per line)</span></label>
      <textarea id="sfx" class="medium" placeholder="e.g. bass_drop, whoosh, impact...">bass_drop
whoosh
impact_hit
reverb_tail
riser_buildup
stinger_accent
vinyl_scratch
explosion_boom
crowd_cheer
metallic_clang
cinematic_boom
drum_hit
swoosh
glass_shatter
electric_zap</textarea>
    </div>
  </div>

  <button id="goBtn" onclick="run()">Generate Effect Plan</button>
  <div class="status" id="status"></div>
  <div class="result" id="result" style="display:none"></div>
</div>

<script>
fetch('/api/model').then(r => r.json()).then(d => document.getElementById('model-name').textContent = d.model);

// Load default clips
fetch('/api/default-clips').then(r => r.json()).then(d => {
  if (d.clips) document.getElementById('clips').value = d.clips;
});

async function run() {
  const clips = document.getElementById('clips').value.trim();
  const task = document.getElementById('task').value.trim();
  const vfx = document.getElementById('vfx').value.trim();
  const sfx = document.getElementById('sfx').value.trim();

  if (!clips || !task) { alert('Clip analysis and task prompt are required'); return; }

  const btn = document.getElementById('goBtn');
  const status = document.getElementById('status');
  const result = document.getElementById('result');
  btn.disabled = true;
  result.style.display = 'none';
  status.className = 'status';

  const t0 = Date.now();
  const timer = setInterval(() => {
    status.textContent = 'Thinking... (' + Math.round((Date.now() - t0) / 1000) + 's)';
  }, 1000);
  status.textContent = 'Thinking... (0s)';

  try {
    const resp = await fetch('/api/plan', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ clips, task, vfx, sfx })
    });
    clearInterval(timer);
    const data = await resp.json();
    if (data.error) {
      status.textContent = 'Error: ' + data.error;
      status.className = 'status error';
    } else {
      status.textContent = 'Done (' + (data.elapsed || '?') + 's)';
      result.textContent = data.response;
      result.style.display = 'block';
    }
  } catch (e) {
    clearInterval(timer);
    status.textContent = 'Request failed: ' + e.message;
    status.className = 'status error';
  }
  btn.disabled = false;
}
</script>
</body>
</html>"""


@app.route("/")
def index():
    return HTML


@app.route("/api/model")
def model_info():
    return jsonify({"model": MODEL})


@app.route("/api/default-clips")
def default_clips():
    return jsonify({"clips": DEFAULT_CLIPS})


@app.route("/api/plan", methods=["POST"])
def plan():
    import time

    data = request.json
    clips = data.get("clips", "")
    task = data.get("task", "")
    vfx = data.get("vfx", "")
    sfx = data.get("sfx", "")

    prompt = f"""## Clip Analysis (from video analysis stage)
{clips}

## Available Video Effects
{vfx}

## Available Sound Effects
{sfx}

## Your Task
{task}"""

    try:
        t0 = time.time()
        response = client.models.generate_content(
            model=MODEL,
            contents=[prompt],
        )
        elapsed = round(time.time() - t0, 1)
        return jsonify({"response": response.text, "elapsed": elapsed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print(f"Using model: {MODEL}")
    print("Open http://localhost:5001")
    app.run(debug=True, port=5001)
