"""Transactional tools. All times are seconds; clip references are current indices."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from render.plan import RenderPlan
from server.validation import plan_valid


class Args(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    rationale: str = Field(default='', max_length=1000)


class Candidates(Args):
    filter: str = Field(default='', max_length=200)


class Window(Args):
    t0: float = Field(ge=0)
    t1: float = Field(gt=0)


class Add(Window):
    pass


class Clip(Args):
    clip: int = Field(ge=0, strict=True)


class Trim(Window, Clip):
    pass


class Order(Args):
    order: list[Annotated[int, Field(strict=True)]] = Field(max_length=100)


class Transition(Args):
    name: Literal['cut', 'fast_zoom', 'whip', 'flash', 'glitch']
    duration: float = Field(default=.15, ge=.05, le=1)


class Caption(Clip):
    text: str = Field(min_length=1, max_length=240)
    start: float = Field(default=0, ge=0)
    duration: float = Field(default=1, gt=0)


class Reaction(Clip):
    label: Literal['sick_kill', 'clutch', 'bruh', 'fail', 'funny', 'wholesome', 'hype', 'roast']
    speaker: str = Field(default='', max_length=80)
    start: float = Field(default=0, ge=0)
    duration: float = Field(default=1, gt=0)


class Music(Args):
    enabled: bool = Field(strict=True)


class Finish(Args):
    summary: str = Field(min_length=1, max_length=2000)


SCHEMAS = dict(list_candidates=Candidates, inspect_window=Window, add_clip=Add,
               remove_clip=Clip, trim_clip=Trim, reorder=Order, set_transition=Transition,
               add_reaction=Reaction, add_caption=Caption, set_music=Music,
               render_preview=Args, watch_preview=Args, finish=Finish)


def bounds(row):
    return (float(row.get('start_seconds', row.get('source_start', row.get('start', 0)))),
            float(row.get('end_seconds', row.get('source_end', row.get('end', 0)))))


class EditorTools:
    def __init__(self, job, plan, preview=None, watch=None):
        self.job = job
        self.plan = deepcopy(plan)
        self.settings = {k: bool(job.get('options', {}).get(k, False)) for k in ('music', 'reactions')}
        self.preview, self.watch = preview, watch
        self.preview_key = None
        self.preview_path = None
        self.critiques = {}
        self.finished = False
        self.summary = ''

    def snapshot(self):
        return dict(plan=deepcopy(self.plan), settings=deepcopy(self.settings))

    def validate(self):
        plan_valid(self.plan, self.job['meta']['duration'], self.job.get('options', {}).get('max_duration', 180))

    def execute(self, name, arguments):
        if name not in SCHEMAS:
            raise ValueError('Unknown tool')
        args = SCHEMAS[name].model_validate(arguments)
        before = self.snapshot()
        try:
            result = self._execute(name, args)
            self.validate()
            return result
        except Exception:
            self.plan, self.settings = before['plan'], before['settings']
            raise

    def _execute(self, name, a):
        import json
        candidates = self.job.get('candidates') or self.job.get('clips') or []
        segments = self.plan['segments']
        if isinstance(a, Window) and not 0 <= a.t0 < a.t1 <= self.job['meta']['duration']:
            raise ValueError('Window must be ordered and inside source duration')
        if isinstance(a, Clip) and a.clip >= len(segments):
            raise ValueError('Unknown clip index')
        if name == 'list_candidates':
            rows = self.job.get('clips') or candidates
            return [deepcopy(c) for c in rows if a.filter.lower() in json.dumps(c).lower()][:500]
        if name == 'inspect_window':
            def overlapping(rows):
                return [deepcopy(c) for c in rows if isinstance(c, dict) and bounds(c)[0] < a.t1 and bounds(c)[1] > a.t0]
            return dict(candidates=overlapping(candidates), clips=overlapping(self.job.get('clips') or []),
                        scores=overlapping(self.job.get('window_scores') or []),
                        signals=deepcopy(self.job.get('audio_signals', {})),
                        transcript=overlapping(self.job.get('transcript') or []))
        if name == 'add_clip':
            segments.append(dict(source_start=a.t0, source_end=a.t1))
        elif name == 'remove_clip':
            segments.pop(a.clip)
        elif name == 'trim_clip':
            segment = segments[a.clip]
            if a.t0 < segment['source_start'] or a.t1 > segment['source_end']:
                raise ValueError('Trim must stay inside the existing clip')
            shift = (a.t0-segment['source_start']) / segment.get('speed', 1)
            duration = (a.t1-a.t0) / segment.get('speed', 1)
            for key in ('texts', 'reactions', 'timed_effects', 'words'):
                kept = []
                for item in segment.get(key, []):
                    start = max(0, item['start']-shift)
                    end = min(duration, item.get('end', item['start']+item.get('duration', 0))-shift)
                    if end > start:
                        item = {**item, 'start': start}
                        item.update({'end': end} if key == 'words' else {'duration': end-start})
                        kept.append(item)
                segment[key] = kept
            segment['sound_effects'] = [{**s, 'offset_in_segment': s.get('offset_in_segment', 0)-shift}
                for s in segment.get('sound_effects', []) if 0 <= s.get('offset_in_segment', 0)-shift < duration]
            if segment.get('sam') or segment.get('fx'):
                raise ValueError('Trim tracked/FX clips only after removing their tracking in the planner')
            segment.update(source_start=a.t0, source_end=a.t1)
        elif name == 'reorder':
            if any(type(i) is not int for i in a.order) or sorted(a.order) != list(range(len(segments))):
                raise ValueError('order must be a permutation of all current clip indices')
            self.plan['segments'] = [segments[i] for i in a.order]
        elif name == 'set_transition':
            self.plan.update(transition=a.name, transition_duration=a.duration)
        elif name == 'add_caption':
            segments[a.clip].setdefault('texts', []).append(dict(content=a.text, start=a.start, duration=a.duration))
            self.plan['captions'] = {**self.plan.get('captions', {}), 'enabled': True}
        elif name == 'add_reaction':
            segments[a.clip].setdefault('reactions', []).append(dict(label=a.label, start=a.start, duration=a.duration))
            self.settings['reactions'] = True
            if a.speaker:
                segments[a.clip].setdefault('texts', []).append(dict(content=f'{a.speaker}: {a.label}', start=a.start, duration=a.duration))
                self.plan['captions'] = {**self.plan.get('captions', {}), 'enabled': True}
        elif name == 'set_music':
            # Only the trusted built-in music provider can choose filesystem assets.
            self.settings['music'] = a.enabled
        elif name in ('render_preview', 'watch_preview'):
            key = json.dumps(self.snapshot(), sort_keys=True)
            if name == 'render_preview':
                if not self.preview:
                    raise ValueError('Preview renderer unavailable')
                if key != self.preview_key:
                    self.preview_path = self.preview(self.plan, self.settings)
                    self.preview_key = key
                return {'preview': 'ready'}
            if key != self.preview_key or not self.preview_path:
                raise ValueError('Render the current plan before watching it')
            if key not in self.critiques:
                if not self.watch:
                    raise ValueError('Preview critic unavailable')
                self.critiques[key] = self.watch(self.preview_path)
            return deepcopy(self.critiques[key])
        elif name == 'finish':
            self.finished, self.summary = True, a.summary
        return self.snapshot()
