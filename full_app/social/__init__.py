"""Opt-in, offline-first montage share kits. See docs/social.md."""

import json
import logging
from pathlib import Path
import shutil
import tempfile

from vjepa.media import probe_media

from .metadata import build_metadata, chapter_text, seconds, timeline
from .thumbnails import SIZES, render_thumbnail, select_frame
from .image_candidates import candidates

__all__ = ["build_share_kit"]
logger = logging.getLogger(__name__)


def _local_file(job: Path, name: str | Path) -> Path:
    path = (job / name).resolve()
    if not path.is_relative_to(job) or not path.is_file():
        raise ValueError(f"Expected a file inside the job directory: {name}")
    return path


def _duration(path: Path) -> float:
    return seconds(probe_media(path, entries="format=duration", timeout=30)["format"]["duration"])


def _srt_time(value: float) -> str:
    total = round(seconds(value) * 1000)
    hours, rem = divmod(total, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _captions(job, plan, destination, duration):
    captions = plan.get("captions")
    if captions is not None:
        blocks = []
        for caption in sorted(captions, key=lambda item: seconds(item["start"])):
            start, end = seconds(caption["start"]), seconds(caption["end"])
            if end <= start or end > duration + .1:
                raise ValueError("Captions must use valid rendered-video timestamps")
            text = "\n".join(line.strip() for line in str(caption["text"]).splitlines() if line.strip())
            if text:
                blocks.append(f"{len(blocks) + 1}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
        if blocks:
            destination.write_text("\n".join(blocks), encoding="utf-8")
    else:
        name = plan.get("social", {}).get("captions_path", "captions.srt")
        if "captions_path" in plan.get("social", {}) or (job / name).exists():
            shutil.copy2(_local_file(job, name), destination)


def build_share_kit(job_dir, clips, plan, game, *, client=None, job=None) -> Path:
    """Export to job_dir.parent/share/job_dir.name; return its Path.

    Network is disabled unless client is explicitly supplied AND an associated
    plan['social'] flag is true. Client follows GeminiVideoClient's interface.
    Existing destinations are rejected; no previous exports are overwritten.
    """
    job_state = job
    job = Path(job_dir).resolve(strict=True)
    if not job.is_dir():
        raise ValueError("job_dir must be a directory")
    clips = [c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in clips]
    plan = plan.model_dump() if hasattr(plan, "model_dump") else dict(plan)
    options = {**(job_state.get("options", {}) if job_state is not None else {}), **plan.get("social", {})}
    video_name = options.get("video_path")
    if not video_name:
        video_name = next((name for name in ("final_with_thumbs.mp4", "final_edit.mp4") if (job / name).is_file()), None)
    if not video_name:
        raise FileNotFoundError("Render a final_edit.mp4 first, or set social.video_path")
    video = _local_file(job, video_name)
    duration = _duration(video)
    intro = options.get("intro_duration")
    if intro is None:
        intro = _duration(job / "intro.mp4") if video.name == "final_with_thumbs.mp4" and (job / "intro.mp4").is_file() else 0
    intro = seconds(intro)
    entries = timeline(clips, plan, intro)
    if entries[-1]["end"] > duration + .25:
        raise ValueError("Plan timeline exceeds rendered video; check speed and intro_duration")
    chapters = chapter_text(entries, intro)
    metadata = build_metadata(entries, game, chapters, client if options.get("gemini_metadata") else None)
    if intro:
        metadata["chapters"].insert(0, {"start": 0, "title": "Intro"})
    top = max(entries, key=lambda entry: entry["score"])
    source_name = options.get("source_path", "source.mp4")
    if "source_path" in options or (job / source_name).is_file():
        source = _local_file(job, source_name)
        start, end = top["source_start"], top["source_end"]
        timebase = "source"
    else:
        source, start, end, timebase = video, top["start"], top["end"], "montage"
    if end > _duration(source) + .1:
        raise ValueError("Top clip extends beyond thumbnail source")
    destination = job.parent / "share" / job.name
    if destination.exists():
        raise FileExistsError(f"Share kit already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{job.name}-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "kit"
        staging.mkdir()
        frame, selection = select_frame(source, start, end)
        selection["timebase"] = timebase
        selection["clip"] = top["title"]
        warnings = []
        budget_dir = Path(job_state["dir"]) if job_state is not None and job_state.get("dir") else job
        title, images = candidates(frame, options, game, client, Path(temporary), budget_dir, warnings)
        selected = next((info["id"] for _, info in images if info["provider"] == "gemini"), 1)
        metadata["thumbnail_candidates"] = []
        metadata["thumbnails"] = {}
        for image, evidence in images:
            variants = {}
            for variant, size in SIZES.items():
                thumbnail, details = render_thumbnail(image, title, size, options.get("subject_cutout", False),
                    preserve_scene=evidence["provider"] == "gemini", reaction=evidence["reaction"] is not None)
                filename = f"thumbnail_candidate_{evidence['id']}_{variant}.jpg"
                thumbnail.save(staging / filename, quality=94)
                variants[variant] = {"file": filename, **evidence, **details}
                if evidence["id"] == selected:
                    selected_file = f"thumbnail_{variant}.jpg"
                    shutil.copy2(staging / filename, staging / selected_file)
                    metadata["thumbnails"][variant] = {**variants[variant], "file": selected_file}
            metadata["thumbnail_candidates"].append({**evidence, "variants": variants})
        metadata["selected_thumbnail_candidate"] = selected
        metadata["warnings"] = warnings
        for warning in warnings:
            logger.warning(warning)
            if job_state is not None and warning not in job_state.setdefault("warnings", []):
                job_state["warnings"].append(warning)
        metadata["frame_selection"] = selection
        metadata["video"] = "video.mp4"
        metadata["duration"] = duration
        metadata["intro_duration"] = intro
        shutil.copy2(video, staging / "video.mp4")
        (staging / "chapters.txt").write_text(chapters, encoding="utf-8")
        _captions(job, plan, staging / "captions.srt", duration)
        metadata["captions"] = "captions.srt" if (staging / "captions.srt").exists() else None
        (staging / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # Publish only after all artifacts are ready; the temporary directory shares the filesystem.
        staging.rename(destination)
    return destination
