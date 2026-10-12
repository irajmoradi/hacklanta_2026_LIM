"""Private subprocess entry point. Credentials arrive only over stdin."""
import contextlib
import json
import os
import sys
from pathlib import Path


def main():
    payload = json.load(sys.stdin)
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    if os.name == 'posix':
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (payload['memory'], payload['memory']))
        resource.setrlimit(resource.RLIMIT_FSIZE, (payload['file_bytes'], payload['file_bytes']))
    # Keep library/ffmpeg diagnostics out of the result channel and logs.
    with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
        if 'path' in payload:
            from .media import probe_upload
            result = probe_upload(payload['path'])
        else:
            from pipeline import Pipeline
            result = payload['job']
            progress = Path(result['dir']) / '.stage-progress.json'
            def report(snapshot):
                temporary = progress.with_suffix('.part')
                temporary.write_text(json.dumps({k: snapshot[k] for k in ('pipeline_stage', 'timings', 'warnings') if k in snapshot}))
                os.replace(temporary, progress)
            Pipeline().run_stage(payload['stage'], result, payload['key'], report)
            if payload['stage'] == 'render':
                from services.probe import probe_video
                if probe_video(result['output'])['duration'] > result['options'].get('max_duration', 180) + .1:
                    raise ValueError('Rendered output exceeds max_duration')
    json.dump(result, sys.stdout, allow_nan=False)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        from services.provider_errors import classify
        json.dump({'_stage_error': classify(error).code}, sys.stdout)
