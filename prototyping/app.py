"""
Gemini Video Analyzer — lightweight prototype.
Upload an MP4 and get Gemini's analysis with a custom prompt.

Usage:
    pip install -r requirements.txt
    python app.py

Expects GEMINI_API_KEY in ../.env or environment.
"""

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from google import genai

# Load API key from parent .env
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = Path(__file__).resolve().parent / "uploads"
app.config["UPLOAD_FOLDER"].mkdir(exist_ok=True)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB limit

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

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

  // Live timer so it doesn't feel frozen
  const t0 = Date.now();
  status.textContent = 'Uploading & processing video... (0s)';
  const timer = setInterval(() => {
    const s = Math.round((Date.now() - t0) / 1000);
    status.textContent = 'Uploading & processing video... (' + s + 's) — large videos can take 1-2 min';
  }, 1000);

  const form = new FormData();
  form.append('video', selectedFile);
  form.append('prompt', prompt);

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

    # Save temporarily
    save_path = app.config["UPLOAD_FOLDER"] / video.filename
    video.save(save_path)

    try:
        t0 = time.time()

        # Upload to Gemini File API
        uploaded = client.files.upload(file=str(save_path))

        # Wait for processing
        while uploaded.state.name == "PROCESSING":
            time.sleep(1)
            uploaded = client.files.get(name=uploaded.name)

        if uploaded.state.name == "FAILED":
            return jsonify({"error": "Gemini failed to process video"}), 500

        # Generate
        response = client.models.generate_content(
            model=MODEL,
            contents=[uploaded, prompt],
        )

        elapsed = round(time.time() - t0, 1)
        return jsonify({"response": response.text, "elapsed": elapsed})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        save_path.unlink(missing_ok=True)


if __name__ == "__main__":
    print(f"Using model: {MODEL}")
    print("Open http://localhost:5000")
    app.run(debug=True, port=5000)
