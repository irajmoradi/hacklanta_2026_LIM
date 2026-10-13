"""Offline matched Full-experience benchmark using saved DEMO-02 jobs."""
import argparse
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import time


def wait_idle(max_percent, timeout):
    """Require five quiet CPU samples; load averages retain old render history."""
    def cpu():
        values = list(map(int, Path('/proc/stat').read_text().splitlines()[0].split()[1:9]))
        return sum(values), values[3] + values[4]
    started, quiet, samples = time.monotonic(), 0, []
    previous = cpu()
    while quiet < 5:
        time.sleep(1)
        current = cpu()
        total, idle = current[0]-previous[0], current[1]-previous[1]
        percent = 100 * (1-idle/max(1, total))
        samples.append(round(percent, 2))
        quiet = quiet + 1 if percent <= max_percent else 0
        previous = current
        if time.monotonic()-started > timeout:
            raise TimeoutError('Runner did not become idle enough for a matched benchmark')
    return samples[-5:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/srv/demo_out/demo02'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--baseline-engine', type=Path)
    parser.add_argument('--memory-gib', type=int, default=0)
    parser.add_argument('--idle-cpu-percent', type=float, default=0)
    parser.add_argument('--idle-timeout', type=float, default=900)
    parser.add_argument('--reaction-pack', type=Path, default=Path('/srv/packs/team'))
    args = parser.parse_args()
    os.environ.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
                      REACTION_PACK=str(args.reaction_pack), SAM_BACKEND='fallback')
    if args.memory_gib:
        import resource
        limit = args.memory_gib * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    from demo.pipeline import offline
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'live_calls': 0, 'privacy': False, 'memory_gib': args.memory_gib,
              'cores': os.cpu_count(), 'results': [],
              'baseline_engine': str(args.baseline_engine) if args.baseline_engine else None,
              'pack_sha256': hashlib.sha256((args.reaction_pack/'pack.json').read_bytes()).hexdigest()}
    with offline():
        from pipeline import Pipeline
        from pipeline.experience import FULL_EXPERIENCE
        from services.probe import probe_video
        if args.baseline_engine:
            import render.engine
            spec = importlib.util.spec_from_file_location('render.baseline_engine', args.baseline_engine)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            render.engine.Renderer = module.Renderer
        for preset in ('landscape', 'vertical'):
            quiet = wait_idle(args.idle_cpu_percent, args.idle_timeout) if args.idle_cpu_percent else []
            job = json.loads((args.root / f'planned_{preset}.json').read_text())
            workspace = args.output / preset
            workspace.mkdir()
            source = args.root / 'jobs' / job['id'] / 'source.mp4'
            job.update(source=str(source), dir=str(workspace), warnings=[], timings={})
            job['options'].update(FULL_EXPERIENCE, full_experience=True, privacy=False,
                                  preset=preset, perf=True, fx=True)
            job['meta'] = probe_video(source)
            record = dict(preset=preset, target=job['options']['max_duration'],
                          load_before=os.getloadavg(), options=job['options'], idle_cpu_samples=quiet,
                          plan_sha256=hashlib.sha256(json.dumps(job['edit_plan'], sort_keys=True).encode()).hexdigest(),
                          source_size=source.stat().st_size, source_mtime_ns=source.stat().st_mtime_ns)
            started = time.monotonic()
            try:
                Pipeline().render(job, None)
                graphs = job.get('render_evidence', {}).get('filter_graphs', [])
                joins = [g for g in graphs if 'xfade=' in g]
                record.update(status='ok', output=probe_video(job['output']),
                              transition_graphs=len(joins),
                              transition_filters=sum(g.count('xfade=') for g in joins))
            except Exception as error:
                record.update(status='failed', error=str(error), cause=str(error.__cause__))
            record.update(seconds=round(time.monotonic()-started, 3),
                          load_after=os.getloadavg(), warnings=job['warnings'], timings=job['timings'])
            report['results'].append(record)
            (workspace / 'job.json').write_text(json.dumps(job, indent=2, default=str))
            (args.output / 'report.json').write_text(json.dumps(report, indent=2))
            print(json.dumps(record), flush=True)
    return 0 if all(r['status'] == 'ok' for r in report['results']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
