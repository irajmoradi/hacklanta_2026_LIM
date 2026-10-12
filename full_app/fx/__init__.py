"""Pure, composable FFmpeg effects. Importing this package runs no subprocesses."""

from dataclasses import dataclass, field
import math
import re
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class Timing:
    """Seconds on the current clip timeline; end is exclusive."""

    duration: float
    start: float = 0.5
    end: float = 1.0
    fps: float = 30

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.duration, self.start, self.end, self.fps)):
            raise ValueError("Timing must be finite")
        if not (0 <= self.start < self.end <= self.duration and 1 <= self.fps <= 240):
            raise ValueError("Require 0 <= start < end <= duration and 1 <= fps <= 240")

    @property
    def enable(self) -> str:
        return f"gte(t,{self.start})*lt(t,{self.end})"


@dataclass(frozen=True)
class Param:
    default: Any
    description: str
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple = ()

    def validate(self, value: Any) -> Any:
        if isinstance(self.default, (int, float)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Expected a finite number")
            if isinstance(self.default, int) and int(value) != value:
                raise ValueError("Expected an integer")
            if self.minimum is not None and value < self.minimum:
                raise ValueError(f"Value below {self.minimum}")
            if self.maximum is not None and value > self.maximum:
                raise ValueError(f"Value above {self.maximum}")
        elif not isinstance(value, str):
            raise ValueError("Expected text")
        if self.choices and value not in self.choices:
            raise ValueError(f"Expected one of {self.choices}")
        return value


@dataclass(frozen=True)
class Effect:
    description: str
    cost: str
    params: Mapping[str, Param]
    builder: Callable
    changes_duration: bool = False
    required_filters: tuple[str, ...] = ()

    def values(self, params: Mapping[str, Any]) -> dict[str, Any]:
        unknown = params.keys() - self.params.keys()
        if unknown:
            raise ValueError(f"Unknown parameters: {sorted(unknown)}")
        return {k: spec.validate(params.get(k, spec.default)) for k, spec in self.params.items()}

    def filter(self, timing: Timing, **params) -> str:
        """Return an unlabeled -vf snippet, with no IO or global state changes."""
        return self.builder(timing, **self.values(params))

    def output_duration(self, timing: Timing, **params) -> float:
        p = self.values(params)
        if not self.changes_duration:
            return timing.duration
        return (timing.duration - timing.end + timing.start) / p["fast"] + (timing.end - timing.start) / p["slow"]

    def preview(self, source, output, timing: Timing, **params):
        from .preview import render_preview
        return render_preview(source, output, self, timing, **params)


def _gate(t: Timing, chain: list[str]) -> str:
    return ",".join(f"{f}:enable='{t.enable}'" for f in chain)


def _freeze(t: Timing, annotate=True) -> str:
    # Keep the first hit frame, drop subsequent frames in the hold, retain timestamps.
    # round=up makes the fps filter hold the previous frame until the next timestamp.
    chain = (f"select='not(gt(t,{t.start})*lt(t,{t.end}))',fps={t.fps}:round=up,"
             f"tpad=stop_mode=clone:stop_duration={t.duration},trim=duration={t.duration}")
    if annotate:
        # Center/crosshair cue only: this is not a claim of detected enemy location.
        chain += ',' + _gate(t, [
            "drawbox=x=iw*.38:y=ih*.34:w=iw*.24:h=ih*.32:c=white:t=6",
            "drawtext=text='<<<':fontsize=min(w\\,h)*.13:fontcolor=yellow:borderw=4:"
            "bordercolor=black:x=w*.64:y=(h-th)/2"])
    return chain


def impact_frame(t, brightness=0.65):
    flash_end = min(t.end, t.start + 2 / t.fps)
    return _freeze(t, annotate=False) + f",eq=brightness={brightness}:enable='gte(t,{t.start})*lt(t,{flash_end})'"


def speed_ramp(t, fast=2.0, slow=0.5, interpolation="none"):
    a, b = t.start, t.end
    pts = f"if(lt(T,{a}),T/{fast},if(lt(T,{b}),{a}/{fast}+(T-{a})/{slow},{a}/{fast}+({b}-{a})/{slow}+(T-{b})/{fast}))"
    duration = (t.duration - b + a) / fast + (b - a) / slow
    interpolate = f"minterpolate=fps={t.fps}:mi_mode=mci" if interpolation == "minterpolate" else f"fps={t.fps}:round=up"
    return (f"settb=AVTB,setpts='{pts}/TB'," + interpolate +
            f",tpad=stop_mode=clone:stop_duration={duration},trim=duration={duration}")


def zoom_punch(t, zoom=1.18):
    inset = (1 - 1 / zoom) / 2
    return _gate(t, [f"perspective=x0=W*{inset}:y0=H*{inset}:"
                     f"x1=W*(1-{inset}):y1=H*{inset}:x2=W*{inset}:"
                     f"y2=H*(1-{inset}):x3=W*(1-{inset}):y3=H*(1-{inset}):sense=source"])


def screen_shake(t, pixels=8, frequency=25):
    # Padding followed by crop keeps the original geometry; black border is deliberate.
    p = int(pixels)
    return (f"pad=iw+{2*p}:ih+{2*p}:{p}:{p},"
            f"crop=iw-{2*p}:ih-{2*p}:x='{p}+{p}*sin(t*{frequency})*({t.enable})':"
            f"y='{p}+{p}*cos(t*{frequency}*1.3)*({t.enable})'")


def chromatic_aberration(t, pixels=3):
    return _gate(t, [f"chromashift=cbh={int(pixels)}:crh={-int(pixels)}:edge=smear"])


def rgb_split(t, pixels=6):
    return "format=gbrp," + _gate(t, [f"rgbashift=rh={int(pixels)}:bh={-int(pixels)}:edge=smear"])


def vhs_crt(t, noise=12):
    return _gate(t, [f"noise=alls={noise}:allf=t+u", "eq=saturation=0.7:contrast=1.15",
                     "drawgrid=w=iw:h=4:t=1:c=black@0.25"])


def motion_blur_trail(t, frames=4):
    return _gate(t, [f"tmix=frames={int(frames)}:weights='{' '.join(['1'] * int(frames))}'"])


def letterbox(t, fraction=0.12):
    return _gate(t, [f"drawbox=x=0:y=0:w=iw:h=ih*{fraction}:c=black:t=fill",
                     f"drawbox=x=0:y=ih*(1-{fraction}):w=iw:h=ih*{fraction}:c=black:t=fill"])


def color_grade(t, preset="teal-orange"):
    grades = {
        "teal-orange": ["colorbalance=rs=-0.12:bs=0.12:rh=0.15:bh=-0.1", "eq=saturation=1.2"],
        "high-contrast": ["eq=contrast=1.4:brightness=-0.04:saturation=1.1"],
        "neon": ["colorbalance=rm=0.15:bm=0.2:gm=-0.1", "eq=saturation=1.7:contrast=1.15"],
    }
    return _gate(t, grades[preset])


def _text(value: str) -> str:
    # Deliberately limited display alphabet prevents FFmpeg expression/filter injection.
    if not re.fullmatch(r"[\w .!?#@+()/-]{1,48}", value, flags=re.UNICODE):
        raise ValueError("Text must be 1-48 letters, numbers, spaces or .!?#@+()/-")
    return value


def kill_counter(t, count=1):
    return _gate(t, [f"drawtext=text='KILLS {int(count)}':expansion=none:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.6:x=12:y=12"])


def freeze_name_tag(t, name="PLAYER"):
    return _freeze(t, annotate=False) + "," + _gate(t, [f"drawtext=text='{_text(name)}':expansion=none:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.6:x=(w-tw)/2:y=h-th-20"])


REGISTRY = {
    "impact_frame": Effect("Flash and hold the hit frame", "low", {"brightness": Param(0.65, "Flash brightness", 0, 1)}, impact_frame),
    "speed_ramp": Effect("Fast / slow kill window / fast time remap", "high with interpolation; low otherwise", {
        "fast": Param(2.0, "Outside-window playback speed", 1, 8), "slow": Param(0.5, "Kill-window playback speed", 0.125, 1),
        "interpolation": Param("none", "Optional optical flow", choices=("none", "minterpolate"))}, speed_ramp, True),
    "zoom_punch": Effect("Centered zoom during the hit", "medium", {"zoom": Param(1.18, "Magnification", 1, 2)}, zoom_punch),
    "screen_shake": Effect("Two-axis shake with padded edges", "low", {"pixels": Param(8, "Displacement", 0, 64), "frequency": Param(25, "Radians per second", 1, 100)}, screen_shake),
    "chromatic_aberration": Effect("Opposed chroma offsets", "low", {"pixels": Param(3, "Chroma displacement", 0, 32)}, chromatic_aberration),
    "rgb_split": Effect("Opposed red/blue offsets", "medium", {"pixels": Param(6, "Channel displacement", 0, 32)}, rgb_split),
    "vhs_crt": Effect("Analog noise, desaturation and scan lines", "medium", {"noise": Param(12, "Noise strength", 0, 100)}, vhs_crt),
    "motion_blur_trail": Effect("Temporal frame blending", "medium", {"frames": Param(4, "History length", 2, 16)}, motion_blur_trail),
    "letterbox": Effect("Cinematic bars without changing dimensions", "low", {"fraction": Param(0.12, "Height of each bar", 0, 0.4)}, letterbox),
    "color_grade": Effect("Gameplay color looks", "low", {"preset": Param("teal-orange", "Color look", choices=("teal-orange", "high-contrast", "neon"))}, color_grade),
    "kill_counter": Effect("Kill count for a timed interval; repeat for successive kills", "low", {"count": Param(1, "Visible kill count", 0, 9999)}, kill_counter, required_filters=("drawtext",)),
    "freeze_name_tag": Effect("Hold hit frame with player name", "low", {"name": Param("PLAYER", "Display name (restricted punctuation)")}, freeze_name_tag, required_filters=("drawtext",)),
}


def metadata() -> dict[str, dict[str, Any]]:
    """JSON-serializable planner catalog; costs are qualitative, not benchmarks."""
    from dataclasses import asdict
    return {key: {"description": e.description, "cost": e.cost, "changes_duration": e.changes_duration,
                  "required_filters": list(e.required_filters),
                  "params": {k: asdict(v) for k, v in e.params.items()}} for key, e in REGISTRY.items()}


@dataclass(frozen=True)
class Request:
    name: str
    timing: Timing
    params: Mapping[str, Any] = field(default_factory=dict)


def compose(requests: list[Request]) -> str:
    """Chain snippets; each request uses the preceding effect's output timeline."""
    previous_duration = None
    parts = ["setpts=PTS-STARTPTS"]
    for request in requests:
        if previous_duration is not None and not math.isclose(previous_duration, request.timing.duration, abs_tol=1e-6):
            raise ValueError("Timing.duration must match the preceding effect's output duration")
        effect = REGISTRY[request.name]
        parts.append(effect.filter(request.timing, **request.params))
        previous_duration = effect.output_duration(request.timing, **request.params)
    return ",".join(parts)
