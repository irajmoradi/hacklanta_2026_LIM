"""Two bounded Nano Banana candidates, with explicit offline/failure evidence."""
import io
from pathlib import Path
import subprocess

from PIL import Image, ImageChops, ImageStat

from services.call_budget import CallBudget
from services.provider_errors import classify
from vjepa.media import probe_media

TEAM_PACK = Path("/srv/packs/team")


def reaction_frame(name, output):
    """Only use a matted teammate from the consented deployment pack.

    Sample an expressive-labelled clip and prefer its greatest visible change.
    This cheap motion heuristic does not claim to recognize facial expressions.
    """
    root = TEAM_PACK.resolve()
    source = (root / name).resolve(strict=True)
    if not source.is_relative_to(root) or not source.name.endswith(".alpha.webm"):
        raise ValueError("Reaction must be a team-pack alpha WebM")
    duration = float(probe_media(source, entries="format=duration", timeout=30)["format"]["duration"])
    frames, previous = [], None
    for fraction in (.2, .4, .6, .8):
        result = subprocess.run([
            "ffmpeg", "-nostdin", "-v", "error", "-c:v", "libvpx-vp9",
            "-ss", str(duration * fraction), "-i", str(source), "-frames:v", "1",
            "-vf", "scale=480:-2", "-pix_fmt", "rgba", "-f", "image2pipe",
            "-vcodec", "png", "-threads", "1", "-"], capture_output=True, check=True, timeout=30)
        with Image.open(io.BytesIO(result.stdout)) as decoded:
            frame = decoded.convert("RGBA")
        alpha = frame.getchannel("A")
        if alpha.getextrema()[0] == 255 or not alpha.getbbox():
            raise ValueError("Team reaction has no usable matte")
        gray = frame.convert("L").resize((96, 96))
        score = ImageStat.Stat(ImageChops.difference(gray, previous)).mean[0] if previous else 0
        frames.append((score, frame, duration * fraction))
        previous = gray
    _, frame, timestamp = max(frames, key=lambda item: item[0])
    frame.crop(frame.getchannel("A").getbbox()).save(output)
    return {"file": source.name, "timestamp": timestamp, "selection": "motion_heuristic"}


def candidates(frame, options, game, client, work, budget_dir, warnings):
    """Return two (image, evidence) pairs, including local fallbacks."""
    mode = options.get("mode", "nice")
    if mode not in ("nice", "mean"):
        raise ValueError("Thumbnail mode must be nice or mean")
    default_text = "SKILL ISSUE" if mode == "mean" else "NO SHOT"
    words = str(options.get("thumbnail_text") or default_text).upper().split()[:4]
    title = " ".join(words) if len(words) >= 2 else default_text
    reason = None
    if options.get("gemini_image") is not True:
        reason = "disabled"
    elif client is None:
        reason = "client_unavailable"
    reference = work / "reference.png"
    frame.save(reference)
    references = [reference]
    reaction = None
    if options.get("reaction_head") and reason is None:
        try:
            cutout = work / "reaction.png"
            reaction = reaction_frame(options["reaction_head"], cutout)
            references.append(cutout)
        except Exception:
            warnings.append("Thumbnail reaction unavailable; continuing with gameplay only.")
    ledger = CallBudget(budget_dir / "thumbnail-budget.sqlite3", limit=4) if reason is None else None
    results = []
    for index in range(2):
        evidence = {"id": index + 1, "provider": "local", "reason": reason, "reaction": reaction}
        image = frame
        if reason is None:
            mood = "triumphant, exciting" if mode == "nice" else "playful roast, comically disastrous"
            style = ("electric cyan and gold rim lighting", "deep purple and fiery orange contrast")[index]
            prompt = (
                f"Create a bold YouTube gaming thumbnail for {str(game)[:100]}. Mood: {mood}. "
                f"Use {style}, dramatic cinematic grade, subject pop, strong visual hierarchy. "
                "Preserve the supplied gameplay action and recognizable game. Compose a 16:9 image, "
                "with the important action in the central third so vertical and square crops work. "
                "Leave the upper third uncluttered for our local title. No text, letters, numbers, "
                "logos, watermarks or invented achievements. Add a bold circle at the focal action. "
                + ("The last reference is a consented teammate cutout: use that same person, "
                   "large on the right beside the central action, with an exaggerated reaction; "
                   "keep their face inside the central crop. " if reaction else "Do not invent a reaction person. ")
            )
            try:
                generated = client.generate_thumbnail(
                    references if reaction else reference, prompt, work / f"generated_{index + 1}.png",
                    image_budget=ledger,
                )
                with Image.open(generated) as enhanced:
                    image = enhanced.convert("RGB")
                evidence.update(provider="gemini", reason=None)
            except Exception as error:
                evidence["reason"] = classify(error).code
        if evidence["reason"]:
            warnings.append(f"Thumbnail candidate {index + 1}: local fallback ({evidence['reason']}).")
        results.append((image, evidence))
    return title, results
