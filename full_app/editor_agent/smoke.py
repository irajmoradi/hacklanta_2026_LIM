"""Explicit LIVE smoke: EDITOR_AGENT_LIVE=1 python -m editor_agent.smoke.

Uses existing runner analysis; budget reservations persist across attempts.
Credentials are inherited from the environment, never written to artifacts.
"""
from copy import deepcopy
import json
import os
from pathlib import Path


def main():
    if os.getenv('EDITOR_AGENT_LIVE') != '1':
        raise SystemExit('Set EDITOR_AGENT_LIVE=1 to authorize the paid smoke test')
    from .loop import run_agent
    source = Path('/srv/demo_in/valorant_phoenix_44k.mp4')
    analysis = next((p for p in (Path('/srv/demo_out/demo02/analysis.json'),
                                Path('/srv/demo_out/demo01/analysis.json')) if p.exists()), None)
    if analysis is None:
        raise SystemExit('No reusable analysis found; this smoke requires stored analysis')
    job = json.loads(analysis.read_text())
    directory = Path(__file__).parent / 'smoke_artifacts'
    directory.mkdir(exist_ok=True)
    job.update(dir=str(directory), source=str(source))
    job['options'].update(music=False, reactions=False)
    before = deepcopy(job['edit_plan'])
    def log(step):
        print(json.dumps(dict(step=step['step'], tool=step['tool'], args=step['args'], error=step['error'],
                              result=step.get('result') if step['tool'] == 'watch_preview' else None)), flush=True)
    result = run_agent(job,
        'Make this nice Valorant draft tighter. Inspect the stored candidates, remove the repeated opening clutch teaser '
        'if it repeats the ending, render and watch the draft, then make one evidence-based trim if useful. '
        'Finish within 12 total calls, reserving one call for finish. Do not add music or reactions for this smoke.',
        call_limit=12, max_steps=11, emit=log)
    report = dict(analysis=str(analysis), before=before, **result)
    (directory / 'report.json').write_text(json.dumps(report, indent=2))
    def cuts(plan):
        return [[s['source_start'], s['source_end'], s.get('speed', 1)] for s in plan['segments']]
    print(json.dumps(dict(fallback=result['fallback'], reason=result['reason'], calls_used=12-result['calls_remaining'],
                          before=cuts(before), after=cuts(result['plan']), summary=result['summary'])), flush=True)
    raise SystemExit(1 if result['fallback'] else 0)


if __name__ == '__main__':
    main()
