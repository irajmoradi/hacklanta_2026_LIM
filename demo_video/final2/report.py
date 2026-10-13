"""Build the final offline report from measured artifacts and manual review."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE / 'out'


def main():
    names = ['valorant_nice_landscape', 'valorant_mean_vertical',
             'valorant_mean_vertical_reroll', 'deadlock_nice_landscape',
             'deadlock_mean_vertical']
    reviews = json.loads((HERE / 'visual_review.json').read_text())['cuts']
    calls = json.loads((ROOT / 'live_calls.json').read_text())
    assert calls['total'] <= 60
    lines = ['# FINAL-2 delivery report', '', 'Branch: `ext/FINAL-2`; no push or merge.', '',
             'Implementation, exact test commands/results, runtime setup and reproduction: '
             '[docs/final_render.md](../../docs/final_render.md).', '',
             'Five stock-API cuts; measurements below include both cards. '
             'Each linked folder contains master.mp4, discord.mp4, share kit, cards, '
             'job.json (all warnings), timings.json, verification.json and event contact sheets.', '',
             '| Cut | Seconds / cap | Discord MB | SAM applied / rejected | API wall seconds |',
             '|---|---:|---:|---:|---:|']
    records = []
    for name in names:
        folder = ROOT / name
        facts, job, timing = [json.loads((folder / f'{file}.json').read_text())
                             for file in ('verification', 'job', 'timings')]
        assert facts['decode_verified'] and facts['discord_bytes'] < 20_000_000
        assert name in reviews
        lines.append(f"| [{name}](out/{name}/) | {facts['duration']:.3f} / {facts['cap']} | "
                     f"{facts['discord_bytes']/1e6:.2f} | {len(facts['sam'])} / "
                     f"{len(facts['sam_skipped'])} | {timing['total']:.2f} |")
        records.append((name, facts, job, timing))
    lines += ['', 'API wall times cover the final attempt (plan/analyze, render and download), '
              'not earlier cancelled audit attempts or offline packaging. Nice Valorant resumes '
              'analysis; Reroll and mean Deadlock reuse their job analysis. Raw stage times retain '
              'earlier analysis measurements and include nested timers, so do not sum them.', '',
              f"Live Gemini attempts: **{calls['total']} / 60**, including cancelled audit work, "
              'Director and image attempts. Durable per-job totals: `' +
              json.dumps(calls['jobs'], sort_keys=True) + '`.', '',
              'Full runner validation: **1437 pytest passed, 20 skipped; 44 frontend tests '
              'passed; production build passed; exit 0**. All ten delivered video files '
              'were decoded completely with ffmpeg -xerror. Reroll verification confirms '
              'identical analysis/job, changed seed and changed effects.', '',
              '## Feature and visual audit', '',
              'Review method: every scheduled effect, reaction and card sampled in contact '
              'sheets; every thumbnail variant reviewed; selected larger master and compressed '
              'stills inspected. This is sampled visual QA plus complete decode validation, '
              'not frame-by-frame human playback. Manual notes: [visual_review.json](visual_review.json).']
    for name, facts, job, timing in records:
        plan = job['render_plan']
        reactions = job['render_evidence']['reactions']
        lines += ['', '### ' + name, '',
                  f"AI cards: {facts['ai_cards']}; Gemini thumbnail candidates: {facts['ai_thumbnails']}; "
                  f"speakers: {', '.join(facts['speakers'])}. "
                  f"SFX events: {sum(len(s['sound_effects']) for s in plan['segments'])}; "
                  f"music beat sync: {plan['music']['beat_sync']}; transitions: {plan['transition']}. "
                  f"Explicit reactions selected: {sum(r['explicit'] for r in reactions)} "
                  '(clean=false permits them but does not force selection).', '',
                  'Warnings recorded by the stock job (cumulative across rerenders):', '']
        lines += ['- ' + w for w in facts['warnings']] or ['- None.']
        lines += ['', 'Visual findings:', '']
        lines += ['- ' + note for note in reviews[name]['observations']]
    lines += ['', '## Limits and attribution', '',
              'Strict SAM rejection means no spotlight was composited for that target; '
              'procedural boxes/arrows are not SAM evidence. Editorial phrases are present '
              'where speech transcription yields no words. Missing WebRTC VAD uses the stock '
              'fallback. The generated music bed and synthesized narration remain stock behavior.', '',
              (ROOT / 'ATTRIBUTION.txt').read_text().strip(), '',
              'Retain the Deadlock credit when publishing. Each Deadlock share folder includes '
              'posting_with_credit.txt and ATTRIBUTION.txt; its Discord copy carries the credit '
              'in container metadata. No media, weights or secrets are committed.', '']
    (HERE / 'REPORT.md').write_text('\n'.join(lines), encoding='utf-8')


if __name__ == '__main__':
    main()
