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
import random
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

# Check FFmpeg is available
def _check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return True
    except FileNotFoundError:
        return False

if not _check_ffmpeg():
    print("=" * 60)
    print("ERROR: FFmpeg not found!")
    print()
    print("Install FFmpeg before running this app:")
    print("  Windows:  winget install FFmpeg")
    print("  macOS:    brew install ffmpeg")
    print("  Linux:    sudo apt install ffmpeg")
    print()
    print("Or download from: https://ffmpeg.org/download.html")
    print("=" * 60)
    sys.exit(1)

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

# API key: use .env if available, otherwise require from frontend
ENV_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini = GeminiVideoClient(api_key=ENV_API_KEY, model=MODEL) if ENV_API_KEY else None


def _get_gemini(req=None) -> GeminiVideoClient:
    """Get a Gemini client — from .env or from the request header/body."""
    global gemini
    if gemini:
        return gemini
    # Try to get key from request
    api_key = None
    if req:
        api_key = req.headers.get("X-API-Key")
        if not api_key and req.is_json:
            api_key = (req.json or {}).get("api_key")
    if not api_key:
        raise ValueError("No Gemini API key configured. Set GEMINI_API_KEY in .env or provide it via the app.")
    return GeminiVideoClient(api_key=api_key, model=MODEL)

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


def _analyze_segment(seg: dict, prompt_template: str, part_label: str, user_prompt: str, client: GeminiVideoClient = None) -> dict:
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

    g = client or gemini
    try:
        uploaded = g.upload_video(str(seg["path"]))
        clips = g.find_clips(uploaded, prompt)

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
        "has_api_key": bool(ENV_API_KEY),
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


ATTITUDE_PROMPTS = {
    "nice": (
        "\n\nFOCUS: Emphasize GOOD gameplay — kills, clutches, multi-kills, outplays. "
        "Still include some deaths for variety but keep the ratio at ~70% good / 30% bad. "
        "This is a hype reel showing how good the player is."
    ),
    "mean": (
        "\n\nFOCUS: Emphasize BAD gameplay — deaths, whiffs, embarrassing fails, getting destroyed. "
        "Include some kills for contrast but keep the ratio at ~70% bad / 30% good. "
        "This is a roast reel dunking on how bad the player is. Find the FUNNIEST deaths."
    ),
}


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json
    job_id = data.get("job_id")
    user_prompt = data.get("prompt", "")
    attitude = data.get("attitude", "nice")
    user_prompt += ATTITUDE_PROMPTS.get(attitude, ATTITUDE_PROMPTS["nice"])
    n_splits = max(1, min(4, int(data.get("splits", 1))))

    try:
        job = get_job(job_id)
    except KeyError:
        return jsonify({"error": "Job not found"}), 404

    dur = job["meta"]["duration"]
    template = (PROMPTS_DIR / "clip_finder.txt").read_text()

    try:
        g = _get_gemini(request)
        job["_gemini_client"] = g  # store for later stages
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
            uploaded = g.upload_video(job["source"])
            upload_time = time.time() - t0
            print(f"[{job_id}] Upload + processing done in {upload_time:.1f}s")

            job["status"] = "analyzing"
            print(f"[{job_id}] Finding clips...")
            clips = g.find_clips(uploaded, prompt)

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
                        SPLIT_LABELS[n_splits][seg["index"]], user_prompt, g
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

        # Post-filter: remove clips whose descriptions suggest spectating/death screen
        SPECTATE_KEYWORDS = [
            "spectating", "kill cam", "killcam", "respawn", "death screen",
            "combat report", "incoming damage", "camera follows",
        ]
        before_count = len(clips)
        clips = [
            c for c in clips
            if not any(kw in c.get("description", "").lower() for kw in SPECTATE_KEYWORDS)
        ]
        if len(clips) < before_count:
            print(f"[{job_id}] Filtered {before_count - len(clips)} spectating/death screen clips")

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

        g = job.get("_gemini_client") or _get_gemini(request)
        print(f"[{job_id}] Planning edit...")
        edit_plan = g.plan_edit(prompt)

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


# ── Intro/Outro Thumbnail Generation ─────────────────────────────────────────

TITLE_WORDS = {
    "w1": ["gaming", "shooter", "gamer", "player", "character", "npc", "pov"],
    "w2": ["maxer", "maxing", "slayer", "professional"],
    "w3": ["compilation", "highlights", "reels", "montage", "edits"],
}


def _generate_title() -> str:
    w1 = random.choice(TITLE_WORDS["w1"])
    w2 = random.choice(TITLE_WORDS["w2"])
    w3 = random.choice(TITLE_WORDS["w3"])
    return f"{w1} {w2} {w3}"


def _generate_intro_outro(runner: FFmpegRunner, duration: float, client: GeminiVideoClient = None) -> tuple[Path | None, Path | None]:
    """Generate intro and outro thumbnail clips using Gemini image generation."""
    intro_clip = None
    outro_clip = None

    try:
        # Pick two random timestamps for frames (avoid first/last 10s)
        safe_start = min(30.0, duration * 0.1)
        safe_end = max(duration - 30.0, duration * 0.9)
        intro_ts = random.uniform(safe_start, safe_end)
        outro_ts = random.uniform(safe_start, safe_end)

        # Extract frames
        print(f"  [thumbnails] Extracting frames at {intro_ts:.0f}s and {outro_ts:.0f}s")
        intro_frame = runner.extract_random_frame(intro_ts)
        outro_frame = runner.extract_random_frame(outro_ts)

        # Generate intro thumbnail
        title = _generate_title()
        print(f"  [thumbnails] Generating intro: '{title}'")
        intro_prompt = (
            f"Edit this gaming screenshot into a flashy TikTok thumbnail. "
            f"Add bold dramatic text that says \"{title.upper()}\" in a gaming font style. "
            f"Make it eye-catching and corny with bright colors, energy effects, and hype vibes. "
            f"Keep the gameplay visible in the background."
        )
        g = client or gemini
        intro_img = g.generate_thumbnail(intro_frame, intro_prompt,
                                               runner.workspace / "intro_thumb.jpg")
        intro_clip = runner.image_to_clip(intro_img, 4.0, "intro")
        print(f"  [thumbnails] Intro clip ready: {title}")

        # Generate outro thumbnail
        print(f"  [thumbnails] Generating outro")
        outro_prompt = (
            "Edit this image into a meme-style outro screen. "
            "Add big bold text that says \"THANKS FOR WATCHING\". "
            "Add a random car and a fish somewhere in the image. "
            "Make it look absurd and funny, like a shitpost meme. "
            "Keep it colorful and ridiculous."
        )
        outro_img = g.generate_thumbnail(outro_frame, outro_prompt,
                                               runner.workspace / "outro_thumb.jpg")
        outro_clip = runner.image_to_clip(outro_img, 4.0, "outro")
        print(f"  [thumbnails] Outro clip ready")

    except Exception as e:
        print(f"  [thumbnails] Failed (non-fatal): {e}")
        import traceback
        traceback.print_exc()

    return intro_clip, outro_clip


# ── Stage 3: FFmpeg Render ────────────────────────────────────────────────────


@app.route("/api/render", methods=["POST"])
def render():
    data = request.json
    job_id = data.get("job_id")
    custom_plan = data.get("edit_plan")
    generate_thumbnails = data.get("generate_thumbnails", True)

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

        # Generate and prepend/append intro/outro
        if generate_thumbnails:
            job["status"] = "generating_thumbnails"
            g = job.get("_gemini_client") or _get_gemini(request)
            intro_clip, outro_clip = _generate_intro_outro(runner, job["meta"]["duration"], g)

            if intro_clip or outro_clip:
                parts = []
                if intro_clip:
                    parts.append(intro_clip)
                parts.append(output_path)
                if outro_clip:
                    parts.append(outro_clip)

                if len(parts) > 1:
                    print(f"[{job_id}] Re-concatenating with intro/outro...")
                    # Re-concatenate with intro/outro
                    concat_file = Path(job["dir"]) / "final_concat.txt"
                    with open(concat_file, "w") as f:
                        for p in parts:
                            f.write(f"file '{p.resolve()}'\n")
                    final_output = Path(job["dir"]) / "final_with_thumbs.mp4"
                    subprocess.run(
                        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                         "-i", str(concat_file), "-c", "copy", str(final_output)],
                        capture_output=True, text=True, check=True,
                    )
                    output_path = final_output

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
