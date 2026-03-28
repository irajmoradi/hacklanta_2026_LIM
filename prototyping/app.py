"""
Gemini Video Analyzer — lightweight prototype.
Upload an MP4 and get Gemini's analysis with a custom prompt.
Supports splitting video into 1/2, 1/3, or 1/4 segments for parallel analysis.

Usage:
    pip install -r requirements.txt
    python app.py

Expects GEMINI_API_KEY in ../.env or environment.
"""

import json
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from google import genai

# Load API key from parent .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = Path(__file__).resolve().parent / "uploads"
app.config["UPLOAD_FOLDER"].mkdir(exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB limit

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _get_duration(path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        capture_output=True, text=True,
    )
    info = json.loads(result.stdout)
    return float(info["format"]["duration"])


def _split_video(path: Path, n_splits: int) -> list[dict]:
    """Split video into n equal segments. Returns list of {path, start, end, index}."""
    duration = _get_duration(path)
    seg_dur = duration / n_splits
    segments = []
    for i in range(n_splits):
        start = i * seg_dur
        end = min((i + 1) * seg_dur, duration)
        seg_path = path.parent / f"seg_{i}_{path.stem}.mp4"
        # Use -ss before -i for fast seek, re-encode to ensure clean cuts
        result = subprocess.run(
            ["ffmpeg", "-y",
             "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
             "-i", str(path),
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
             "-c:a", "aac",
             "-avoid_negative_ts", "1",
             str(seg_path)],
            capture_output=True, text=True,
        )
        if not seg_path.exists() or seg_path.stat().st_size == 0:
            raise RuntimeError(
                f"ffmpeg failed to create segment {i}: {result.stderr[-500:]}"
            )
        segments.append({"path": seg_path, "start": start, "end": end, "index": i})
    return segments


def _offset_timestamps(text: str, offset_seconds: float) -> str:
    """Shift all MM:SS or HH:MM:SS timestamps in text by offset_seconds."""
    def _shift(match):
        parts = match.group(0).split(":")
        if len(parts) == 3:
            total = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            total = int(parts[0]) * 60 + float(parts[1])
        total += offset_seconds
        h = int(total // 3600)
        m = int((total % 3600) // 60)
        s = total % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:05.2f}"
        return f"{m}:{s:05.2f}"
    return re.sub(r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?", _shift, text)


def _analyze_segment(seg: dict, prompt: str, part_label: str) -> dict:
    """Upload one segment to Gemini and return the response with timing info."""
    seg_prompt = (
        f"{prompt}\n\n"
        f"NOTE: This is {part_label} of the full video. "
        f"Provide timestamps relative to the START of this segment (starting at 0:00)."
    )
    uploaded = client.files.upload(file=str(seg["path"]))
    while uploaded.state.name == "PROCESSING":
        time.sleep(1)
        uploaded = client.files.get(name=uploaded.name)
    if uploaded.state.name == "FAILED":
        return {"error": f"Gemini failed on {part_label}", "index": seg["index"]}
    response = client.models.generate_content(
        model=MODEL, contents=[uploaded, seg_prompt],
    )
    return {
        "index": seg["index"],
        "text": response.text,
        "start": seg["start"],
        "end": seg["end"],
    }

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gemini Video Analyzer</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: system-ui, -apple-system, sans-serif; background: #0f0f0f; color: #e0e0e0; min-height: 100vh; display: flex; justify-content: center; padding: 2rem; }
  .container { max-width: 720px; width: 100%; }
  h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: #8ab4f8; }
  .model-badge { font-size: 0.8rem; background: #1e3a5f; padding: 0.2rem 0.6rem; border-radius: 4px; margin-left: 0.5rem; vertical-align: middle; }

  .drop-zone { border: 2px dashed #444; border-radius: 12px; padding: 2rem; text-align: center; cursor: pointer; transition: border-color 0.2s; margin-bottom: 1rem; }
  .drop-zone:hover, .drop-zone.dragover { border-color: #8ab4f8; }
  .drop-zone input { display: none; }
  .drop-zone p { color: #888; }
  .file-name { color: #8ab4f8; margin-top: 0.5rem; font-size: 0.9rem; }

  #video-preview { max-width: 100%; border-radius: 8px; margin-bottom: 1rem; display: none; }

  textarea { width: 100%; min-height: 100px; background: #1a1a1a; color: #e0e0e0; border: 1px solid #333; border-radius: 8px; padding: 0.75rem; font-size: 0.95rem; resize: vertical; font-family: inherit; }
  textarea:focus { outline: none; border-color: #8ab4f8; }

  button { background: #8ab4f8; color: #0f0f0f; border: none; padding: 0.7rem 1.5rem; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; margin-top: 1rem; width: 100%; }
  button:hover { background: #aecbfa; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }

  .result { background: #1a1a1a; border: 1px solid #333; border-radius: 8px; padding: 1rem; margin-top: 1.5rem; white-space: pre-wrap; line-height: 1.6; font-size: 0.95rem; }
  .status { color: #888; font-size: 0.85rem; margin-top: 0.5rem; }
  .error { color: #f28b82; }
</style>
</head>
<body>
<div class="container">
  <h1>Gemini Video Analyzer <span class="model-badge" id="model-name"></span></h1>

  <div class="drop-zone" id="dropZone">
    <p>Drop an MP4 here or click to select</p>
    <div class="file-name" id="fileName"></div>
    <input type="file" id="fileInput" accept="video/mp4,video/*">
  </div>

  <video id="video-preview" controls></video>

  <textarea id="prompt" placeholder="Enter your prompt... e.g. 'Describe what happens in this video in detail'">Describe what happens in this video in detail.</textarea>

  <div style="margin-top: 1rem; display: flex; align-items: center; gap: 1rem;">
    <label style="color: #888; font-size: 0.9rem;">Split video into:</label>
    <select id="splits" style="background: #1a1a1a; color: #e0e0e0; border: 1px solid #333; border-radius: 6px; padding: 0.4rem 0.8rem; font-size: 0.95rem;">
      <option value="1">No split (whole video)</option>
      <option value="2">2 halves</option>
      <option value="3">3 thirds</option>
      <option value="4">4 quarters</option>
    </select>
  </div>

  <button id="analyzeBtn" onclick="analyze()" disabled>Analyze Video</button>
  <div class="status" id="status"></div>
  <div class="result" id="result" style="display:none"></div>
</div>

<script>
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');
const preview = document.getElementById('video-preview');
const fileName = document.getElementById('fileName');
const btn = document.getElementById('analyzeBtn');

// Show model name
fetch('/api/model').then(r => r.json()).then(d => document.getElementById('model-name').textContent = d.model);

let selectedFile = null;

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragover');
  if (e.dataTransfer.files.length) pickFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener('change', () => { if (fileInput.files.length) pickFile(fileInput.files[0]); });

function pickFile(file) {
  selectedFile = file;
  fileName.textContent = file.name + ' (' + (file.size / 1048576).toFixed(1) + ' MB)';
  preview.src = URL.createObjectURL(file);
  preview.style.display = 'block';
  btn.disabled = false;
}

async function analyze() {
  const prompt = document.getElementById('prompt').value.trim();
  if (!selectedFile || !prompt) return;

  btn.disabled = true;
  const status = document.getElementById('status');
  const result = document.getElementById('result');
  result.style.display = 'none';
  status.className = 'status';

  const splits = document.getElementById('splits').value;

  // Live timer so it doesn't feel frozen
  const t0 = Date.now();
  const splitLabel = splits === '1' ? '' : ' (' + splits + ' segments in parallel)';
  status.textContent = 'Uploading & processing video' + splitLabel + '... (0s)';
  const timer = setInterval(() => {
    const s = Math.round((Date.now() - t0) / 1000);
    status.textContent = 'Uploading & processing video' + splitLabel + '... (' + s + 's) — large videos can take 1-2 min';
  }, 1000);
  const form = new FormData();
  form.append('video', selectedFile);
  form.append('prompt', prompt);
  form.append('splits', splits);

  try {
    const resp = await fetch('/api/analyze', { method: 'POST', body: form });
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


@app.route("/api/analyze", methods=["POST"])
def analyze():
    if "video" not in request.files:
        return jsonify({"error": "No video uploaded"}), 400

    video = request.files["video"]
    prompt = request.form.get("prompt", "Describe this video.")
    n_splits = int(request.form.get("splits", "1"))
    n_splits = max(1, min(4, n_splits))

    # Save temporarily
    save_path = app.config["UPLOAD_FOLDER"] / video.filename
    video.save(save_path)
    seg_paths = []

    try:
        t0 = time.time()

        if n_splits == 1:
            # Original single-video path
            uploaded = client.files.upload(file=str(save_path))
            while uploaded.state.name == "PROCESSING":
                time.sleep(1)
                uploaded = client.files.get(name=uploaded.name)
            if uploaded.state.name == "FAILED":
                return jsonify({"error": "Gemini failed to process video"}), 500
            response = client.models.generate_content(
                model=MODEL, contents=[uploaded, prompt],
            )
            elapsed = round(time.time() - t0, 1)
            return jsonify({"response": response.text, "elapsed": elapsed})

        # Split video and analyze segments in parallel
        labels = {
            2: ["part 1 of 2 (first half)", "part 2 of 2 (second half)"],
            3: ["part 1 of 3 (first third)", "part 2 of 3 (middle third)", "part 3 of 3 (final third)"],
            4: ["part 1 of 4 (first quarter)", "part 2 of 4 (second quarter)",
                "part 3 of 4 (third quarter)", "part 4 of 4 (final quarter)"],
        }

        segments = _split_video(save_path, n_splits)
        seg_paths = [s["path"] for s in segments]

        results = []
        with ThreadPoolExecutor(max_workers=n_splits) as pool:
            futures = {
                pool.submit(_analyze_segment, seg, prompt, labels[n_splits][seg["index"]]): seg
                for seg in segments
            }
            for future in as_completed(futures):
                results.append(future.result())

        # Sort by segment index and combine
        results.sort(key=lambda r: r["index"])

        errors = [r for r in results if "error" in r]
        if errors:
            return jsonify({"error": "; ".join(e["error"] for e in errors)}), 500

        # Build combined response with corrected timestamps
        combined_parts = []
        for r in results:
            header = f"══════ Segment {r['index'] + 1}/{n_splits} [{_fmt_time(r['start'])} → {_fmt_time(r['end'])}] ══════"
            adjusted_text = _offset_timestamps(r["text"], r["start"])
            combined_parts.append(f"{header}\n\n{adjusted_text}")

        combined = "\n\n".join(combined_parts)
        elapsed = round(time.time() - t0, 1)
        return jsonify({
            "response": combined,
            "elapsed": elapsed,
            "segments": n_splits,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        save_path.unlink(missing_ok=True)
        for p in seg_paths:
            p.unlink(missing_ok=True)


def _fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:05.2f}"


if __name__ == "__main__":
    print(f"Using model: {MODEL}")
    print("Open http://localhost:5000")
    app.run(debug=True, port=5000)
