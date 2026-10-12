"""Validation shared by HTTP inputs and provider outputs."""
import math

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


def plan_valid(plan, duration):
    if isinstance(plan, list):
        plan = {'segments': plan}
    if not isinstance(plan, dict) or not isinstance(plan.get('segments'), list) or not 1 <= len(plan['segments']) <= 500:
        raise ValueError('plan must contain 1 to 500 segments')
    for seg in plan['segments']:
        if not isinstance(seg, dict):
            raise ValueError('segments must be objects')
        start = number(seg.get('source_start'), 'source_start', high=duration)
        end = number(seg.get('source_end'), 'source_end', high=duration)
        if end <= start:
            raise ValueError('segment end must be after start')
        number(seg.get('speed', 1), 'speed', .1, 8)
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
