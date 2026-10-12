"""Cache private source-speed ranges before framing/effects; never scan a whole VOD."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess

from services.probe import probe_video
from services.ffmpeg_runner import FFmpegRunner


def private_range(pipeline, job, source, start, end, scratch):
    from .extensions import private_source
    source = Path(source)
    stat = source.stat()
    signature = dict(version=1, source=str(source.resolve()), size=stat.st_size, mtime=stat.st_mtime_ns,
                     start=start, end=end, game=job.get('game', 'generic'), options=job['options'].get('privacy_options', {}))
    digest = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
    cache = Path(job['dir']) / 'privacy_cache'
    cache.mkdir(exist_ok=True)
    output, record = cache / (digest + '.mp4'), cache / (digest + '.json')
    if output.is_file() and record.is_file():
        job['privacy_track'] = json.loads(record.read_text())
        return output
    raw = scratch / ('range_' + digest + '.mp4')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-ss', str(start), '-i', str(source),
                    '-t', str(end-start), '-map', '0:v:0', '-map', '0:a?', '-vf', 'fps=30',
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-threads', '2',
                    '-c:a', 'aac', str(raw)], check=True, capture_output=True, timeout=600)
    temporary_job = {**job, 'options': copy.deepcopy(job['options'])}
    payload = temporary_job['options'].setdefault('privacy_options', {})
    # Manual masks use source seconds. Intersect and translate for this range.
    if 'manual_boxes' in payload:
        payload['manual_boxes'] = [{**b, 'start': max(start, b['start'])-start,
                                   'end': min(end, b['end'])-start}
                                  for b in payload['manual_boxes'] if b['start'] < end and b['end'] > start]
    try:
        sanitized = private_source(pipeline, temporary_job, raw, scratch)
        if 'privacy_track' not in temporary_job:
            raise RuntimeError('Privacy module unavailable; cannot publish an unsanitized range')
        os.replace(sanitized, output)
        job['privacy_track'] = temporary_job['privacy_track']
        record.write_text(json.dumps(job['privacy_track']))
    finally:
        raw.unlink(missing_ok=True)
    return output


def selected_source(pipeline, job, scratch):
    plan, clips = copy.deepcopy(job['edit_plan']), []
    paths, cursor = [], 0.
    for segment in plan['segments']:
        start, end = segment['source_start'], segment['source_end']
        path = private_range(pipeline, job, job['source'], start, end, scratch)
        length = min(end-start, probe_video(path)['duration'])
        for clip in job.get('clips') or []:
            if clip['start_seconds'] < end and clip['end_seconds'] > start:
                clips.append({**clip, 'start_seconds': cursor + max(start, clip['start_seconds'])-start,
                              'end_seconds': cursor + min(end, clip['end_seconds'])-start})
        segment.update(source_start=cursor, source_end=cursor+length)
        paths.append(path)
        # Concat clocks follow encoded media duration, including frame rounding.
        cursor += probe_video(path)['duration']
    runner = FFmpegRunner(scratch, paths[0], job['meta']['width'], job['meta']['height'], 30)
    source = runner.concatenate(paths)
    plan['segments'][-1]['source_end'] = min(plan['segments'][-1]['source_end'], probe_video(source)['duration'])
    return source, plan, clips
