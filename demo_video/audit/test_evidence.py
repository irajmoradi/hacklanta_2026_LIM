"""Acceptance checks for AUDIT-2 evidence, not mocked product behavior."""
import json
from pathlib import Path
import re
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'demo_video/audit/out'

def test_all_requested_exports_have_real_media_and_event_samples():
    for name in ('landscape','vertical','mean_vertical'):
        job=json.loads((OUT/(name+'.json')).read_text())
        assert job['options']['full_experience'] is True
        assert job['options']['privacy'] is False
        assert job['options']['window_scoring'] is True
        media=OUT/(name+'.mp4')
        assert media.stat().st_size>10000
        data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(media)]))
        assert {s['codec_type'] for s in data['streams']} >= {'audio','video'}
        events=json.loads((OUT/(name+'_frames/events.json')).read_text())
        segs=json.loads((OUT/(name+'_segments.json')).read_text())
        assert sum(' mid' in e['label'] for e in events)==sum(len(s['timed_effects']) for s in segs)
        assert sum('reaction ' in e['label'] for e in events)==sum(len(s['reactions']) for s in segs)
        assert sum('word ' in e['label'] for e in events)==sum(s['words'] for s in segs)

def test_budget_provenance_and_failed_default_are_retained():
    calls=json.loads((OUT/'calls.json').read_text())
    assert calls['total']==calls['gemini_attempts']+calls['metadata_calls']<=25
    assert calls['other_paid_calls']==0
    before=json.loads((OUT/'analyzed_default_model.json').read_text())
    assert before['status']=='error'
    assert 'model unavailable' in before['error']


def test_api_success_and_diagnostic_are_not_conflated():
    summary=json.loads((OUT/'summary.json').read_text())
    assert summary['landscape']['status']=='error'
    assert 'NOT a successful API export' in summary['landscape']['provenance']
    for name in ('vertical','mean_vertical'):
        assert summary[name]['status']=='done'
        assert summary[name]['provenance']=='stock HTTP API output'
    downloads=json.loads((OUT/'http_downloads.json').read_text())
    assert all(row['status']==200 for row in downloads['checks'])
    assert downloads['checks'][0]['sha256']==summary['mean_vertical']['sha256']

def test_browser_evidence_covers_controls_review_director_and_export():
    for name in ('ui_stock_legacy.png','ui_settings_defaults.png','ui_settings_full.png',
                 'ui_review_full.png','ui_director.png','ui_export.png'):
        assert (OUT/name).stat().st_size>1000
    controls=json.loads((OUT/'ui_controls.json').read_text())
    scoring=next(c for c in controls if 'Gemini window scoring' in (c.get('text') or ''))
    assert scoring['checked'] is False  # Reproduces the preset omission.
    result=json.loads((OUT/'ui_result.json').read_text())
    assert result['reroll_controls']==0
    assert result['chaos_controls']==0

def test_report_feature_code_and_named_test_references_exist():
    from findings import FINDINGS, TASK_FEATURES
    from build_report import code_location
    for row in FINDINGS:
        assert re.search(r':\d+$',code_location(row[2]))
        path,_,name=row[4].partition('::')
        p=ROOT/path
        assert p.exists(),row[4]
        if name: assert 'def '+name+'(' in p.read_text(encoding='utf-8'),row[4]
    specs={p.stem for p in (ROOT/'docs/tasks').glob('*.md') if p.stem!='AUDIT-2'}
    assert specs<=TASK_FEATURES.keys()
