"""Existing prompt styles and media helpers, shared by the job pipeline."""
import random
import subprocess
from pathlib import Path
from services.gemini_client import GeminiVideoClient
from services.provider_errors import classify
from services.ffmpeg_runner import FFmpegRunner
gemini = None

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
            capture_output=True, text=True, timeout=3600,
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
            "error": classify(e).code,
        }

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

    except Exception:
        print("  [thumbnails] Failed (non-fatal)")

    return intro_clip, outro_clip
