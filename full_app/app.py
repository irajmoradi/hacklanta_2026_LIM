"""
AI Gameplay Clip Editor — Full Pipeline
Upload gameplay → Gemini finds highlights → Gemini plans edit → FFmpeg renders montage

Usage:
    pip install -r requirements.txt
    python app.py
    # Open http://localhost:8000
"""

import json
import os
import re
import subprocess
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, send_file

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from services.probe import probe_video
from services.gemini_client import GeminiVideoClient
from services.ffmpeg_runner import FFmpegRunner
from models.effects import VIDEO_EFFECTS, SOUND_EFFECTS, effects_for_prompt, sfx_for_prompt

app = Flask(__name__, static_folder="frontend", static_url_path="")
WORKSPACE = Path(__file__).resolve().parent / "workspace"
WORKSPACE.mkdir(exist_ok=True)
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
APP_DIR = Path(__file__).resolve().parent

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2GB

gemini = GeminiVideoClient(api_key=os.environ["GEMINI_API_KEY"], model=MODEL)

# In-memory job store (fine for local single-user use)
jobs = {}


def _log(job_dir, stage: str, data: dict):
    """Append a timestamped entry to the job's log.txt and save stage output as JSON."""
    job_dir = Path(job_dir)
    # Append to running log
    with open(job_dir / "log.txt", "a") as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Stage: {stage}\n")
        f.write(f"{'='*60}\n")
        f.write(json.dumps(data, indent=2, default=str))
        f.write("\n")
    # Also save as individual JSON file
    with open(job_dir / f"{stage}.json", "w") as f:
        json.dump(data, f, indent=2, default=str)


def _parse_ts(val) -> float:
    """Parse a timestamp that could be HH:MM:SS, MM:SS string, or numeric seconds."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str) and ":" in val:
        parts = val.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        return int(parts[0]) * 60 + float(parts[1])
    return float(val)


def _split_video(path: Path, n_splits: int, duration: float) -> list[dict]:
    """Split video into n equal segments. Returns list of {path, start, end, index}."""
    seg_dur = duration / n_splits
    segments = []
    for i in range(n_splits):
        start = i * seg_dur
        end = min((i + 1) * seg_dur, duration)
        seg_path = path.parent / f"seg_{i}_{path.stem}.mp4"
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


def _offset_clip_timestamps(clips: list[dict], offset_seconds: float) -> list[dict]:
    """Shift all timestamp fields in clip dicts by offset_seconds."""
    for c in clips:
        if "start_seconds" in c:
            c["start_seconds"] = c["start_seconds"] + offset_seconds
        if "end_seconds" in c:
            c["end_seconds"] = c["end_seconds"] + offset_seconds
        # Also fix the MM:SS string representations
        if "start" in c and isinstance(c["start"], str):
            c["start"] = _seconds_to_mmss(c["start_seconds"])
        if "end" in c and isinstance(c["end"], str):
            c["end"] = _seconds_to_mmss(c["end_seconds"])
    return clips


def _seconds_to_mmss(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m:02d}:{s:05.2f}"


def _fmt_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:05.2f}"


SPLIT_LABELS = {
    2: ["part 1 of 2 (first half)", "part 2 of 2 (second half)"],
    3: ["part 1 of 3 (first third)", "part 2 of 3 (middle third)", "part 3 of 3 (final third)"],
    4: ["part 1 of 4 (first quarter)", "part 2 of 4 (second quarter)",
        "part 3 of 4 (third quarter)", "part 4 of 4 (final quarter)"],
}


def _analyze_segment(seg: dict, prompt_template: str, part_label: str, user_prompt: str) -> dict:
    """Upload one segment to Gemini and return clips with timing info."""
    seg_dur = seg["end"] - seg["start"]
    seg_dur_mmss = f"{int(seg_dur)//60:02d}:{int(seg_dur)%60:02d}"
    third = seg_dur / 3
    one_third_mmss = f"{int(third)//60:02d}:{int(third)%60:02d}"
    two_third_mmss = f"{int(2*third)//60:02d}:{int(2*third)%60:02d}"

    prompt = prompt_template.format(
        duration=seg_dur,
        duration_mmss=seg_dur_mmss,
        one_third_mmss=one_third_mmss,
        two_third_mmss=two_third_mmss,
        user_prompt=user_prompt,
    )
    prompt += (
        f"\n\nNOTE: This is {part_label} of the full video. "
        f"Provide timestamps relative to the START of this segment (starting at 0:00)."
    )

    try:
        uploaded = gemini.upload_video(str(seg["path"]))
        clips = gemini.find_clips(uploaded, prompt)

        if isinstance(clips, list):
            for c in clips:
                if "start_seconds" not in c and "start" in c:
                    c["start_seconds"] = _parse_ts(c["start"])
                if "end_seconds" not in c and "end" in c:
                    c["end_seconds"] = _parse_ts(c["end"])

        return {
            "index": seg["index"],
            "clips": clips if isinstance(clips, list) else [],
            "start": seg["start"],
            "end": seg["end"],
        }
    except Exception as e:
        return {
            "index": seg["index"],
            "clips": [],
            "start": seg["start"],
            "end": seg["end"],
            "error": str(e),
        }


def get_job(job_id: str) -> dict:
    if job_id not in jobs:
        raise KeyError(f"Job {job_id} not found")
    return jobs[job_id]


# ── Routes ────────────────────────────────────────────────────────────────────


@app.route("/")
def index():
    resp = send_from_directory("frontend", "index.html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.route("/api/info")
def info():
    return jsonify({
        "model": MODEL,
        "video_effects": {k: v["description"] for k, v in VIDEO_EFFECTS.items()},
        "sound_effects": {k: v["description"] for k, v in SOUND_EFFECTS.items() if v["file"] is not None},
        "edit_styles": {k: v["label"] for k, v in EDIT_STYLES.items()},
    })


# ── Stage 0: Upload & Probe ──────────────────────────────────────────────────


@app.route("/api/upload", methods=["POST"])
def upload():
    if "video" not in request.files:
        return jsonify({"error": "No video file provided"}), 400

    video = request.files["video"]
    job_id = uuid.uuid4().hex[:12]
    job_dir = WORKSPACE / job_id
    job_dir.mkdir(parents=True)

    source_path = job_dir / "source.mp4"
    video.save(source_path)

    try:
        meta = probe_video(source_path)
    except Exception as e:
        return jsonify({"error": f"FFprobe failed: {e}"}), 400

    jobs[job_id] = {
        "id": job_id,
        "dir": str(job_dir),
        "source": str(source_path),
        "meta": meta,
        "status": "uploaded",
        "clips": None,
        "edit_plan": None,
        "output": None,
    }

    # Log metadata
    _log(job_dir, "upload", {"job_id": job_id, "filename": video.filename, "meta": meta})

    return jsonify({"job_id": job_id, "meta": meta})


# ── Stage 1: Gemini Clip Finder ──────────────────────────────────────────────


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json
    job_id = data.get("job_id")
    user_prompt = data.get("prompt", "")
    n_splits = max(1, min(4, int(data.get("splits", 1))))

    try:
        job = get_job(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404

    dur = job["meta"]["duration"]
    template = (PROMPTS_DIR / "clip_finder.txt").read_text()

    try:
        t0 = time.time()

        if n_splits == 1:
            # Original single-video path
            dur_mmss = f"{int(dur)//60:02d}:{int(dur)%60:02d}"
            third = dur / 3
            one_third_mmss = f"{int(third)//60:02d}:{int(third)%60:02d}"
            two_third_mmss = f"{int(2*third)//60:02d}:{int(2*third)%60:02d}"
            prompt = template.format(
                duration=dur,
                duration_mmss=dur_mmss,
                one_third_mmss=one_third_mmss,
                two_third_mmss=two_third_mmss,
                user_prompt=user_prompt,
            )

            job["status"] = "uploading_to_gemini"
            print(f"[{job_id}] Uploading video to Gemini...")
            uploaded = gemini.upload_video(job["source"])
            upload_time = time.time() - t0
            print(f"[{job_id}] Upload + processing done in {upload_time:.1f}s")

            job["status"] = "analyzing"
            print(f"[{job_id}] Finding clips...")
            clips = gemini.find_clips(uploaded, prompt)

            if isinstance(clips, list):
                for c in clips:
                    if "start_seconds" not in c and "start" in c:
                        c["start_seconds"] = _parse_ts(c["start"])
                    if "end_seconds" not in c and "end" in c:
                        c["end_seconds"] = _parse_ts(c["end"])
                clips.sort(key=lambda c: c.get("start_seconds", 0))

        else:
            # Split video and analyze segments in parallel
            job["status"] = "splitting_video"
            print(f"[{job_id}] Splitting video into {n_splits} segments...")
            source_path = Path(job["source"])
            segments = _split_video(source_path, n_splits, dur)

            job["status"] = "analyzing"
            print(f"[{job_id}] Analyzing {n_splits} segments in parallel...")

            results = []
            with ThreadPoolExecutor(max_workers=n_splits) as pool:
                futures = {
                    pool.submit(
                        _analyze_segment, seg, template,
                        SPLIT_LABELS[n_splits][seg["index"]], user_prompt
                    ): seg
                    for seg in segments
                }
                for future in as_completed(futures):
                    results.append(future.result())

            # Sort by segment index
            results.sort(key=lambda r: r["index"])

            # Check for errors
            errors = [r for r in results if "error" in r]
            if errors:
                err_msgs = "; ".join(f"Segment {r['index']}: {r['error']}" for r in errors)
                print(f"[{job_id}] Segment errors: {err_msgs}")

            # Offset timestamps and merge all clips
            clips = []
            for r in results:
                offset_clips = _offset_clip_timestamps(r["clips"], r["start"])
                clips.extend(offset_clips)

            clips.sort(key=lambda c: c.get("start_seconds", 0))

            # Clean up segment files
            for seg in segments:
                seg["path"].unlink(missing_ok=True)

        job["clips"] = clips
        job["status"] = "analyzed"
        elapsed = round(time.time() - t0, 1)

        _log(job["dir"], "clips", {
            "elapsed": elapsed, "prompt": user_prompt,
            "splits": n_splits, "clips": clips,
        })

        print(f"[{job_id}] Found {len(clips)} clips in {elapsed}s (splits={n_splits})")
        return jsonify({"clips": clips, "elapsed": elapsed, "splits": n_splits})

    except Exception as e:
        job["status"] = "error"
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


EDIT_STYLES = {
    "hype_montage": {
        "label": "Hype Montage",
        "instructions": (
            "Go ALL OUT. This should feel like an esports highlight reel. "
            "Use heavy effects: slow_motion on kills, saturation_boost + contrast_pop for intensity, "
            "text overlays on big moments (text_highlight, text_clutch), shake + glitch on deaths. "
            "Layer 2-3 VFX per clip. Use dramatic SFX generously — bass_drop, za_warudo, jojos_golden_wind for highlights, "
            "roblox_death, spongebob_fail, clown_music for fails. Multiple SFX per clip at key moments. "
            "Start strong, build to the best clip at the end."
        ),
    },
    "clean_edit": {
        "label": "Clean Edit",
        "instructions": (
            "Keep it clean and professional. Let the gameplay speak for itself. "
            "Use minimal effects — mostly 'none' or subtle ones like light_sharpen, light_grain, vignette. "
            "Only use text overlays sparingly on the very best moments. "
            "SFX should be rare and tasteful — maybe 1-2 sound effects total across all clips. "
            "Favor good pacing and flow over flashy effects. No meme sounds."
        ),
    },
    "meme_edit": {
        "label": "Meme Edit",
        "instructions": (
            "Make it FUNNY. Lean heavily into comedy. "
            "For fails: use desaturate + shake + text_bruh or text_fail or text_rip, black_and_white for dramatic deaths. "
            "For highlights: over-the-top with heavy_saturation, zoom_in_center + text_nice. "
            "Use the funniest SFX: roblox_death, spongebob_fail, clown_music, my_leg, thats_rough for fails. "
            "hello_there, surprise, anime_wow, kinda_cringe for good moments. "
            "Multiple SFX per clip is encouraged. Include MORE bad moments than good for comedic effect. "
            "Invert_colors or glitch for shock value. Go nuts."
        ),
    },
    "cinematic": {
        "label": "Cinematic",
        "instructions": (
            "Make it feel like a movie trailer. "
            "Use slow_motion on the best moments, vignette + dark_mood + light_grain for atmosphere. "
            "warm_tint for victories, cold_tint for tense moments, black_and_white for dramatic deaths. "
            "Text overlays only for the climax (text_clutch or text_gg). "
            "Use cinematic_boom, prowler, death_note for atmosphere. No meme sounds. "
            "Build tension — start quiet, escalate to the best plays at the end. "
            "Favor fade_in transitions between clips."
        ),
    },
}


# ── Stage 2: Gemini Edit Planner ─────────────────────────────────────────────


@app.route("/api/plan", methods=["POST"])
def plan():
    data = request.json
    job_id = data.get("job_id")
    user_prompt = data.get("prompt", "")
    max_duration = data.get("max_duration", 180)
    edit_style = data.get("edit_style", "hype_montage")

    try:
        job = get_job(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404

    if not job["clips"]:
        return jsonify({"error": "No clips found yet — run analyze first"}), 400

    style = EDIT_STYLES.get(edit_style, EDIT_STYLES["hype_montage"])
    template = (PROMPTS_DIR / "editor.txt").read_text()
    prompt = template.format(
        max_duration=max_duration,
        clips_json=json.dumps(job["clips"], indent=2),
        video_effects=effects_for_prompt(),
        sound_effects=sfx_for_prompt(),
        edit_style=style["label"],
        style_instructions=style["instructions"],
        user_prompt=user_prompt,
    )

    try:
        job["status"] = "planning"
        t0 = time.time()

        print(f"[{job_id}] Planning edit...")
        edit_plan = gemini.plan_edit(prompt)

        # Wrap if Gemini returns bare list
        if isinstance(edit_plan, list):
            edit_plan = {"segments": edit_plan}

        job["edit_plan"] = edit_plan
        job["status"] = "planned"
        elapsed = round(time.time() - t0, 1)

        _log(job["dir"], "edit_plan", {"elapsed": elapsed, "prompt": user_prompt, "max_duration": max_duration, "edit_plan": edit_plan})

        print(f"[{job_id}] Edit plan ready: {len(edit_plan.get('segments', []))} segments in {elapsed}s")
        return jsonify({"edit_plan": edit_plan, "elapsed": elapsed})

    except Exception as e:
        job["status"] = "error"
        return jsonify({"error": str(e)}), 500


# ── Stage 3: FFmpeg Render ────────────────────────────────────────────────────


@app.route("/api/render", methods=["POST"])
def render():
    data = request.json
    job_id = data.get("job_id")
    # Allow passing a custom edit plan (e.g. user edited it in the UI)
    custom_plan = data.get("edit_plan")

    try:
        job = get_job(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404

    edit_plan = custom_plan or job["edit_plan"]
    if not edit_plan:
        return jsonify({"error": "No edit plan — run plan first"}), 400

    try:
        job["status"] = "rendering"
        t0 = time.time()

        runner = FFmpegRunner(
            workspace=Path(job["dir"]),
            source=Path(job["source"]),
            width=job["meta"]["width"],
            height=job["meta"]["height"],
            fps=job["meta"]["fps"],
        )

        output_path = runner.render(edit_plan)
        job["output"] = str(output_path)
        job["status"] = "done"
        elapsed = round(time.time() - t0, 1)

        _log(job["dir"], "render", {"elapsed": elapsed, "output": str(output_path), "segments_count": len(edit_plan.get("segments", []))})

        print(f"[{job_id}] Render complete in {elapsed}s → {output_path}")
        return jsonify({"elapsed": elapsed, "download_url": f"/api/download/{job_id}"})

    except Exception as e:
        job["status"] = "error"
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ── Download & Status ─────────────────────────────────────────────────────────


@app.route("/api/download/<job_id>")
def download(job_id):
    try:
        job = get_job(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404

    if not job.get("output") or not Path(job["output"]).exists():
        return jsonify({"error": "No rendered output yet"}), 404

    return send_file(job["output"], mimetype="video/mp4", as_attachment=True,
                     download_name=f"highlight_{job_id}.mp4")


@app.route("/api/log/<job_id>")
def get_log(job_id):
    try:
        job = get_job(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404

    log_path = Path(job["dir"]) / "log.txt"
    if log_path.exists():
        return log_path.read_text(), 200, {"Content-Type": "text/plain"}
    return "No log yet.\n", 200, {"Content-Type": "text/plain"}


@app.route("/api/stream/<job_id>")
def stream_video(job_id):
    """Stream the source video for in-browser preview."""
    try:
        job = get_job(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404

    return send_file(job["source"], mimetype="video/mp4")


@app.route("/api/status/<job_id>")
def status(job_id):
    try:
        job = get_job(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404

    return jsonify({
        "job_id": job_id,
        "status": job["status"],
        "has_clips": job["clips"] is not None,
        "has_plan": job["edit_plan"] is not None,
        "has_output": job["output"] is not None,
    })


if __name__ == "__main__":
    print(f"Model: {MODEL}")
    print(f"Workspace: {WORKSPACE}")
    print("Open http://localhost:8000")
    app.run(debug=True, port=8000, host="0.0.0.0")
