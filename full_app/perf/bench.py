"""Reproducible offline benchmark: python -m perf.bench --seconds 2 --effects."""
import argparse
import json
import os
import platform
import tempfile
import time
from pathlib import Path
from .cache import Cache
from .encoders import best, Encoder
from .graph import Clip, render
from .media import run, concatenate, copy_cut, probe
from .parallel import render_all


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--seconds", type=float, default=2)
    parser.add_argument("--effects", action="store_true", help="profile every registered effect")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    from services.ffmpeg_runner import FFmpegRunner
    from models.effects import VIDEO_EFFECTS, SOUND_EFFECTS
    rows = []
    def measure(label, fn):
        start = time.perf_counter()
        value = fn()
        elapsed = time.perf_counter() - start
        print(f"{label}: {elapsed:.3f}s", flush=True)
        return value, elapsed
    def pair(label, before, after):
        _, a = measure(label + " baseline", before)
        _, b = measure(label + " optimized", after)
        rows.append(dict(stage=label, baseline=a, optimized=b))
    with tempfile.TemporaryDirectory(prefix="lim-perf-") as tmp:
        root = Path(tmp)
        source, sfx, image = root / "source.mp4", root / "tone.wav", root / "title.bmp"
        d = args.seconds
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=1920x1080:r=60:d={d*2}",
             "-f", "lavfi", "-i", f"sine=frequency=440:duration={d*2}", "-vf", "noise=alls=6:allf=t+u:all_seed=42",
             "-c:v", "libx264", "-preset", "veryfast", "-threads", "2", "-g", "60", "-bf", "0", "-sc_threshold", "0",
             "-c:a", "aac", "-ar", "48000", "-ac", "2", source])
        run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=0.5", sfx])
        run(["ffmpeg", "-v", "error", "-y", "-i", source, "-frames:v", "1", image])
        slow = FFmpegRunner(root, source, 1920, 1080, 60)
        encoder = best()
        cache = Cache(root / "cache")
        SOUND_EFFECTS["perf_synthetic"] = {"file": str(sfx)}
        clip = lambda name, **kw: Clip(source, root / (name + ".mp4"), 0, d, **kw)
        pair("extraction", lambda: slow.extract_segment(0, 0, d), lambda: render(clip("extract"), encoder=encoder))
        pair("keyframe cut", lambda: slow.extract_segment(1, 0, d), lambda: copy_cut(source, root / "copy.mp4", 0, d))
        names = [n for n in VIDEO_EFFECTS if n != "none"] if args.effects else ["heavy_blur", "text_gg", "contrast_pop"]
        for i, name in enumerate(names, 20):
            try:
                pair("effect " + name, lambda n=name, j=i: slow.extract_segment(j, 0, d, [n]),
                     lambda n=name: render(clip("effect_" + n), [n], encoder=encoder))
            except RuntimeError as exc:
                rows.append(dict(stage="effect " + name, error=str(exc)))
                print(f"effect {name} failed: {exc}", flush=True)
        pair("blur approximation", lambda: render(clip("blur_exact"), ["heavy_blur"], encoder=encoder),
             lambda: render(clip("blur_cheap", cheap_blur=True), ["heavy_blur"], encoder=encoder))
        pair("SFX decode cold/warm", lambda: cache.audio(sfx), lambda: cache.audio(sfx))
        pair("proxy cold/warm", lambda: cache.proxy(source), lambda: cache.proxy(source))
        base = root / "seg_000.mp4"
        pair("SFX mix", lambda: slow.overlay_sfx(base, [{"sfx_key": "perf_synthetic", "offset_in_segment": .2}], 0),
             lambda: render(clip("sfx_mix"), sfx=[{"file": sfx, "offset": .2}], encoder=encoder, cache=cache))
        pair("transition", lambda: slow.apply_transition(base, "fade_in", 0),
             lambda: render(clip("transition", transition="fade_in"), encoder=encoder))
        pair("concat (no final encode)", lambda: slow.concatenate([base, base]),
             lambda: concatenate([base, base], root / "concat_fast.mp4"))
        pair("intro/outro sequential/parallel",
             lambda: [slow.image_to_clip(image, 1, x) for x in ("intro", "outro")],
             lambda: render_all([lambda: slow.image_to_clip(image, 1, "intro_p"), lambda: slow.image_to_clip(image, 1, "outro_p")], encoder))
        pair("encoder legacy/preview", lambda: slow.extract_segment(90, 0, d), lambda: render(clip("preview"), encoder=encoder))
        pair("encoder legacy/final", lambda: slow.extract_segment(91, 0, d), lambda: render(clip("final"), preset="final", encoder=encoder))
        def baseline():
            paths = []
            for i in (100, 101):
                p = slow.extract_segment(i, 0, d, ["heavy_blur", "text_gg"])
                p = slow.overlay_sfx(p, [{"sfx_key": "perf_synthetic", "offset_in_segment": .2}], i)
                paths.append(slow.apply_transition(p, "fade_in", i))
            return slow.concatenate(paths)
        def optimized():
            paths = render_all([lambda i=i: render(clip(f"full_{i}", transition="fade_in"), ["heavy_blur", "text_gg"],
                    [{"file": sfx, "offset": .2}], encoder=encoder, cache=cache) for i in (0, 1)], encoder)
            return concatenate(paths, root / "optimized.mp4")
        before, a = measure("end to end baseline", baseline)
        after, b = measure("end to end optimized", optimized)
        assert abs(float(probe(before)["format"]["duration"]) - float(probe(after)["format"]["duration"])) < .15
        rows.append(dict(stage="end to end (2 clips)", baseline=a, optimized=b))
        metadata = dict(platform=platform.platform(), cores=os.cpu_count(), encoder=encoder.name,
                        threads=encoder.threads, seconds=d, ffmpeg=run(["ffmpeg", "-version"]).stdout.splitlines()[0])
    report = dict(environment=metadata, rows=rows)
    print(json.dumps(metadata, indent=2))
    print("| Stage | Baseline s | Optimized s | Speedup |\n|---|---:|---:|---:|")
    for row in rows:
        if "error" in row:
            print(f"| {row['stage']} | ERROR | ERROR | — |")
        else:
            print(f"| {row['stage']} | {row['baseline']:.3f} | {row['optimized']:.3f} | {row['baseline']/max(row['optimized'], 1e-9):.2f}x |")
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
