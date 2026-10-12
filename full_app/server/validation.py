"""Validation shared by HTTP inputs and provider outputs."""
import math

from typing import Literal
from pydantic import Field, model_validator
from render.plan import RenderPlan, Segment

class LegacySegment(Segment):
    speed: float = Field(default=1, ge=.1, le=8)
    transition_in: Literal['cut', 'none', 'fade_in', 'flash_white'] = 'cut'

    # Legacy effects are prepared first; validate the converted metadata below.
    @model_validator(mode='after')
    def ordered(self):
        return self

class LegacyPlan(RenderPlan):
    render_version: Literal[1] = 1
    segments: list[LegacySegment] = Field(min_length=1, max_length=100)


EXTENSION_FLAGS = {'profiles', 'audio_ai', 'planner', 'vjepa', 'social', 'ingest',
                   'fx', 'narration', 'privacy', 'multipov', 'music', 'perf'}


def number(value, name, low=0, high=86400):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be a finite number between {low} and {high}')
    return value


def clips_valid(clips, duration):
    if not isinstance(clips, list) or len(clips) > 500:
        raise ValueError('clips must be a list of at most 500 clips')
    ids = set()
    for i, clip in enumerate(clips):
        if not isinstance(clip, dict):
            raise ValueError('each clip must be an object')
        start = number(clip.get('start_seconds'), 'start_seconds', high=duration)
        end = number(clip.get('end_seconds'), 'end_seconds', high=duration)
        if end <= start:
            raise ValueError('clip end must be after start')
        clip.setdefault('id', str(i))
        if not isinstance(clip['id'], str) or clip['id'] in ids:
            raise ValueError('clip ids must be unique strings')
        ids.add(clip['id'])
        if 'keep' in clip and not isinstance(clip['keep'], bool):
            raise ValueError('keep must be boolean')
    return clips


def plan_valid(plan, duration, max_duration=3600):
    """One legacy/v2 boundary for HTTP admission and generated plans.

    Validate the exact v2 representation, or the legacy representation plus the
    metadata that survives preparation. Preserve the caller's wire shape.
    """
    import copy
    from models.effects import VIDEO_EFFECTS, SOUND_EFFECTS

    if isinstance(plan, list):
        plan = {'segments': plan}
    plan = copy.deepcopy(plan)
    if not isinstance(plan, dict) or type(plan.get('render_version', 1)) is not int or plan.get('render_version', 1) not in (1, 2):
        raise ValueError('render_version must be 1 or 2')
    version = plan.get('render_version', 1)
    # No client-controlled server filesystem reads. An asset API is not exposed.
    if plan.get('music') is not None:
        raise ValueError('HTTP music paths are unsupported; use the music option')
    try:
        parsed = (RenderPlan if version == 2 else LegacyPlan).model_validate(plan, strict=True)
        if len(parsed.captions.profanity) > 100 or any(len(w) > 200 for w in parsed.captions.profanity):
            raise ValueError('Too many or oversized caption terms')
        if parsed.captions.model not in ('tiny', 'base', 'small'):
            raise ValueError('Unsupported transcription model')
        durations = []
        for raw, seg in zip(plan['segments'], parsed.segments):
            start = number(raw.get('source_start'), 'source_start', high=duration)
            end = number(raw.get('source_end'), 'source_end', high=duration)
            if end <= start:
                raise ValueError('segment end must be after start')
            for entry in seg.fx:
                if set(entry) - {'name', 'start', 'end', 'params'}:
                    raise ValueError('Unknown FX fields')
                if any(isinstance(v, str) and len(v) > 200 for v in entry.get('params', {}).values()):
                    raise ValueError('Oversized FX parameter')
            effects = seg.video_effects
            if len(effects) > 16 or len(set(effects)) != len(effects) or any(e not in VIDEO_EFFECTS for e in effects):
                raise ValueError('Invalid or excessive video effects')
            length = end - start
            if version == 1:
                length /= number(raw.get('speed', 1), 'speed', .1, 8)
                length *= (2 if 'slow_motion' in effects else 1) * (.5 if 'speed_2x' in effects else 1)
                converted = seg.model_dump(exclude={'speed', 'transition_in'})
                converted['video_effects'] = [e for e in effects if e not in {'slow_motion', 'speed_2x', 'chromatic_aberration', 'fade_out'}]
                Segment.model_validate(converted)
            if len(seg.sound_effects) > 32 or len(seg.words) > 1000:
                raise ValueError('Too many sounds or words')
            for sound in seg.sound_effects:
                if sound.sfx_key not in SOUND_EFFECTS or sound.offset_in_segment > length:
                    raise ValueError('Invalid sound name or offset')
            if any(w.end > length for w in seg.words) or seg.sam and any(p.time > length for p in seg.sam.subject_track):
                raise ValueError('Clip-local text/track exceeds segment')
            durations.append(max(1, round(length * parsed.fps)) / parsed.fps)
        if version == 2:
            durations += [round(c.duration * parsed.fps) / parsed.fps for c in (parsed.intro, parsed.outro) if c]
            overlap = (max(1, round(min(parsed.transition_duration, min(durations) / 3) * parsed.fps)) / parsed.fps
                       if parsed.transition != 'cut' else 0)
            if overlap and min(durations) <= 2 * overlap:
                raise ValueError('Clips too short for transition')
        else:
            # Legacy top-level cards/transitions are not consumed by its adapter.
            if set(plan) - {'segments', 'render_version', 'resolution'}:
                raise ValueError('Use render_version 2 for top-level render settings')
            overlap = 0
        if sum(durations) - overlap * (len(durations) - 1) > max_duration + 1e-6:
            raise ValueError('Plan exceeds max_duration')
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError('Malformed nested render plan') from exc
    return plan


def options_valid(data, styles):
    allowed = {'mode', 'style', 'provider', 'use_signals', 'window_scoring', 'sam_reframe', 'captions', 'reactions', 'sam',
               'prompt', 'splits', 'max_duration', 'preset', 'generate_thumbnails', 'edit_plan',
               'attitude', 'edit_style', 'job_id', 'api_key', 'game', 'privacy_options',
               'chat', 'team_mode'} | EXTENSION_FLAGS
    if set(data) - allowed:
        raise ValueError('unknown options: ' + ', '.join(sorted(set(data) - allowed)))
    result = {k: v for k, v in data.items() if k not in ('api_key', 'job_id', 'attitude', 'edit_style', 'edit_plan')}
    if 'attitude' in data:
        result['mode'] = data['attitude']
    if 'edit_style' in data:
        result['style'] = data['edit_style']
    if result.get('mode', 'nice') not in ('nice', 'mean'):
        raise ValueError('mode must be nice or mean')
    if not isinstance(result.get('style', 'hype_montage'), str) or result.get('style', 'hype_montage') not in styles:
        raise ValueError('unknown style')
    if result.get('preset', 'landscape') not in ('landscape', 'vertical', 'square'):
        raise ValueError('unknown preset')
    for name in EXTENSION_FLAGS | {'use_signals', 'window_scoring', 'sam_reframe', 'captions', 'reactions', 'sam', 'generate_thumbnails'}:
        if name in result and not isinstance(result[name], bool):
            raise ValueError(f'{name} must be boolean')
    for name in ('prompt', 'provider'):
        if name in result and (not isinstance(result[name], str) or len(result[name]) > (8000 if name == 'prompt' else 64)):
            raise ValueError(f'invalid {name}')
    if 'splits' in result and (type(result['splits']) is not int or not 1 <= result['splits'] <= 4):
        raise ValueError('splits must be an integer from 1 to 4')
    if 'max_duration' in result:
        number(result['max_duration'], 'max_duration', 1, 3600)
    if result.get('game', 'auto') not in {'auto', 'generic', 'valorant', 'overwatch2', 'deadlock', 'league_of_legends'}:
        raise ValueError('unknown game')
    if result.get('team_mode', 'best') not in {'best', 'split', 'pip'}:
        raise ValueError('unknown team_mode')
    if 'privacy_options' in result:
        from privacy import PrivacyOptions
        result['privacy_options'] = PrivacyOptions.model_validate(result['privacy_options']).model_dump(mode='json', exclude_unset=True)
    if 'chat' in result:
        chat = result['chat']
        if not isinstance(chat, list) or len(chat) > 100000:
            raise ValueError('chat must be a list of at most 100000 replay bins')
        # Accept numerical counts only; never persist chat text or usernames.
        for row in chat:
            if not isinstance(row, dict) or set(row) != {'time', 'activity', 'emotes', 'clip_it'}:
                raise ValueError('chat requires time, activity, emotes and clip_it counts')
            for name, value in row.items():
                number(value, 'chat.' + name, high=864000)
    return result
