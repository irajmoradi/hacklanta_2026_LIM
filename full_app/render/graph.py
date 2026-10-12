"""Pure filtergraph builders: no probing, I/O, or optional dependencies."""

TRANSITIONS = {"fast_zoom": "zoomin", "whip": "slideleft", "flash": "fadewhite", "glitch": "pixelize"}


def number(value):
    return f"{value:.6f}".rstrip("0").rstrip(".") or "0"


def track_expression(points, axis):
    if not points:
        return "0.5"
    # A sum of clamped ramps avoids deeply nested if() expressions on long tracks.
    terms = [number(getattr(points[0], axis))]
    for a, b in zip(points, points[1:]):
        av, bv = getattr(a, axis), getattr(b, axis)
        terms.append(f"({number(bv-av)})*clip((t-{number(a.time)})/{number(b.time-a.time)},0,1)")
    return "+".join(terms)


def reframe_graph(size, mode="crosshair", points=()):
    width, height = size
    if mode == "blur":
        return (f"[0:v]split=2[bg][fg];[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},gblur=sigma=30[back];"
                f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[front];"
                "[back][front]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    x, y = track_expression(points, "x"), track_expression(points, "y")
    return (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}:x='clip(iw*({x})-ow/2,0,iw-ow)':"
            f"y='clip(ih*({y})-oh/2,0,ih-oh)',setsar=1[v]")


def join_graph(durations, transition, overlap, fps):
    parts = []
    for i in range(len(durations)):
        parts.append(f"[{i}:v]fps={fps},settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v{i}]")
        parts.append(f"[{i}:a]aresample=48000,asetpts=PTS-STARTPTS[a{i}]")
    if len(durations) == 1:
        parts.extend(["[v0]null[outv]", "[a0]anull[outa]"])
    elif transition == "cut":
        inputs = "".join(f"[v{i}][a{i}]" for i in range(len(durations)))
        parts.append(f"{inputs}concat=n={len(durations)}:v=1:a=1[outv][outa]")
    else:
        cursor = durations[0]
        video, audio = "v0", "a0"
        for i, duration in enumerate(durations[1:], 1):
            last = i == len(durations) - 1
            vo, ao = ("outv", "outa") if last else (f"xv{i}", f"xa{i}")
            parts.append(f"[{video}][v{i}]xfade=transition={TRANSITIONS[transition]}:"
                         f"duration={number(overlap)}:offset={number(cursor-overlap)}[{vo}]")
            parts.append(f"[{audio}][a{i}]acrossfade=d={number(overlap)}:c1=tri:c2=tri[{ao}]")
            cursor += duration - overlap
            video, audio = vo, ao
    return ";".join(parts)


def music_graph(volume, duck):
    bed = f"[1:a]aresample=48000,aformat=channel_layouts=stereo,asetnsamples=n=1024,asetpts=N/SR/TB,volume={number(volume)}[bed]"
    if duck:
        return (bed + ";[0:a]asplit=2[voice][key];[bed][key]"
                "sidechaincompress=threshold=0.025:ratio=8:attack=15:release=250[quiet];"
                "[voice][quiet]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[outa]")
    return bed + ";[0:a][bed]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[outa]"
