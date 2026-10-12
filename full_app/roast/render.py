"""Compile roast specs into an unlabeled FFmpeg -vf chain, composable with FX."""

from fx import REGISTRY, Timing

from .planner import RoastPlan, TEMPLATES
from .safety import safe_line


def video_filter(plan: RoastPlan) -> str:
    """Preserve source duration and geometry. Audio is untouched by this filter.

    Top/bottom and two-panel templates use graphic text panels, no external art.
    Caption font scales with both frame width and text length for mobile layouts.
    """
    parts = ["setpts=PTS-STARTPTS"]
    for beat in plan.beats:
        t = Timing(plan.duration, beat.start, beat.end, plan.fps)
        parts.append(f"select='not(gt(t,{t.start})*lt(t,{t.end}))',fps={t.fps}:round=up,"
                     f"tpad=stop_mode=clone:stop_duration={t.duration},trim=duration={t.duration}")
        parts.append(REGISTRY["zoom_punch"].filter(t, zoom=beat.zoom))
    for overlay in plan.overlays:
        t = Timing(plan.duration, overlay.start, overlay.end, plan.fps)
        if overlay.template not in TEMPLATES or not safe_line(overlay.caption):
            raise ValueError("Unsafe or unsupported overlay")
        gate = f":enable='{t.enable}'"

        def box(y, height, color):
            parts.append(f"drawbox=x=0:y=ih*{y}:w=iw:h=ih*{height}:color={color}:t=fill" + gate)

        def text(value, y, color="white"):
            # All values are safety-checked captions or internal constants.
            # Colon needs escaping even in a quoted drawtext value.
            escaped = value.replace(":", "\\:")
            size = f"min(h/12,w/{max(10, len(value) * 0.65)})"
            parts.append(f"drawtext=text='{escaped}':expansion=none:fontsize='{size}':"
                         f"fontcolor={color}:borderw=1:bordercolor=black:x=(w-tw)/2:y=h*{y}" + gate)

        if overlay.template == "top_bottom":
            box(0, 0.16, "black@0.7")
            box(0.82, 0.18, "black@0.7")
            text("THE PLAN WAS PERFECT", 0.04)
            text(overlay.caption, 0.87)
        elif overlay.template == "two_panel":
            box(0, 0.5, "red@0.55")
            box(0.5, 0.5, "green@0.55")
            text("NO - HITTING THE TARGET", 0.12)
            text("YES - COMMITTING TO THE BIT", 0.58)
            text(overlay.caption, 0.78)
        elif overlay.template == "wasted":
            box(0.32, 0.36, "black@0.7")
            text("WASTED", 0.36, "red")
            text(overlay.caption, 0.53)
        else:
            box(0.05, 0.38, "black@0.8")
            text("FAKE STATS - FOR THE BIT", 0.08)
            text("Aim: 3%   Confidence: 100%", 0.2)
            text(overlay.caption, 0.32)
    return ",".join(parts)
