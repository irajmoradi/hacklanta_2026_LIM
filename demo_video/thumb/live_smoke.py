"""EXPLICIT LIVE SMOKE: at most 8 paid attempts, key from stdin/env only.

Run on runner 1 after syncing via tools/remote_run.sh. Outputs are gitignored.
No API calls occur on import or during pytest discovery.
"""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "full_app"))


def recompose(report, output):
    from PIL import Image, ImageOps, ImageDraw
    from social.thumbnails import render_thumbnail
    tiles = []
    for entry in report["jobs"]:
        for evidence in entry["candidates"]:
            generated = evidence["provider"] == "gemini"
            source = f"generated_{evidence['id']}.png" if generated else "highlight.png"
            with Image.open(output / entry["game"] / source) as master:
                for variant, layout in evidence["variants"].items():
                    thumbnail, details = render_thumbnail(master, layout["text"], tuple(layout["size"]),
                        preserve_scene=generated, reaction=evidence["reaction"] is not None)
                    thumbnail.save(output / layout["file"], quality=94)
                    layout.update(details)
                    tile = ImageOps.contain(thumbnail, (384, 300))
                    panel = Image.new("RGB", (384, 330), "#151520")
                    panel.paste(tile, ((384-tile.width)//2, 25))
                    ImageDraw.Draw(panel).text((8, 6), f"{entry['game']} {evidence['id']} {variant} {evidence['provider']}", fill="white")
                    tiles.append(panel)
    sheet = Image.new("RGB", (384*3, 330*((len(tiles)+2)//3)))
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % 3)*384, (index // 3)*330))
    sheet.save(output / "contact_sheet.jpg", quality=92)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "out")
    parser.add_argument("--retry-failed", action="store_true", help="Reuse existing ledgers; retry only jobs without generated candidates")
    parser.add_argument("--compose-only", action="store_true", help="Offline: recompose saved masters without any API calls")
    args = parser.parse_args()
    if args.compose_only:
        report_path = args.output / "report.json"
        report = json.loads(report_path.read_text())
        recompose(report, args.output)
        report_path.write_text(json.dumps(report, indent=2)+"\n")
        return
    key = os.environ.get("GOOGLE_API_KEY") or sys.stdin.readline().strip()
    if not key:
        raise SystemExit("GOOGLE_API_KEY required through environment or stdin")
    from services.gemini_client import GeminiProvider
    from services.call_budget import CallBudget
    from services.provider_errors import classify
    from social.image_candidates import candidates
    from social.thumbnails import select_frame, render_thumbnail, SIZES

    args.output.mkdir(parents=True, exist_ok=True)
    client = GeminiProvider(api_key=key, vertexai=True)
    del key
    client.budget = CallBudget(args.output / "live-budget.sqlite3", limit=8)
    report_path = args.output / "report.json"
    if report_path.exists() and not args.retry_failed:
        raise SystemExit("Existing live report: use --retry-failed to preserve the run budget")
    report = json.loads(report_path.read_text()) if report_path.exists() else {
        "backend": "vertex_express", "limit": 8, "jobs": [], "probe": {}}
    inputs = [
        ("valorant", Path("/srv/demo_out/demo02/automatic_montage_landscape.mp4"), 2, 10, "nice", "iraj-hype.alpha.webm"),
        ("deadlock", Path("/srv/demo_in/deadlock_ccby_aXZYyd4SoWM.mp4"), 120, 128, "mean", "lance-bruh.alpha.webm"),
    ]
    try:
        if not report["probe"]:
            first, _ = select_frame(inputs[0][1], inputs[0][2], inputs[0][3])
            reference = args.output / "probe_reference.png"
            first.save(reference)
            # Test the task's original ID once, then use the documented replacement.
            client.image_model = "gemini-3.1-flash-image-preview"
            try:
                client.generate_thumbnail(reference, "Dramatically enhance this gaming frame. No text.", args.output / "model_probe.png")
                report["probe"] = {"model": client.image_model, "provider": "gemini", "reason": None}
            except Exception as error:
                report["probe"] = {"model": client.image_model, "provider": "local", "reason": classify(error).code}
                client.image_model = "gemini-3.1-flash-image"
        else:
            client.image_model = report["selected_model"]
        report["selected_model"] = client.image_model
        print(json.dumps({"probe": report["probe"], "selected_model": client.image_model}), flush=True)
        for game, source, start, end, mode, reaction in inputs:
            previous = next((j for j in report["jobs"] if j["game"] == game), None)
            if previous and any(c["provider"] == "gemini" for c in previous["candidates"]):
                continue
            work = args.output / game
            work.mkdir(exist_ok=True)
            frame, selection = select_frame(source, start, end)
            frame.save(work / "highlight.png")
            warnings = []
            title, images = candidates(frame, {"gemini_image": True, "mode": mode, "reaction_head": reaction},
                game, client, work, work, warnings)
            entry = {"game": game, "source": str(source), "frame_selection": selection,
                "mode": mode, "warnings": warnings, "candidates": []}
            for image, evidence in images:
                variants = {}
                for variant, size in SIZES.items():
                    thumbnail, layout = render_thumbnail(image, title, size,
                        preserve_scene=evidence["provider"] == "gemini", reaction=evidence["reaction"] is not None)
                    name = f"candidate_{evidence['id']}_{variant}.jpg"
                    thumbnail.save(work / name, quality=94)
                    variants[variant] = {"file": f"{game}/{name}", **layout}
                entry["candidates"].append({**evidence, "variants": variants})
            if previous:
                report.setdefault("previous_attempts", []).append(previous)
                report["jobs"].remove(previous)
            report["jobs"].append(entry)
            print(json.dumps({"game": game, "providers": [e["provider"] for _, e in images], "warnings": warnings}), flush=True)
        recompose(report, args.output)
    finally:
        report["live_attempts"] = 8-client.budget.remaining
        report_path.write_text(json.dumps(report, indent=2)+"\n")
        client.close()
    if any(c["provider"] != "gemini" for j in report["jobs"] for c in j["candidates"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
