"""Offline planner contract tests; no downloaded media or provider calls."""

import random
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from models.effects import SOUND_EFFECTS, VIDEO_EFFECTS
from planner import GeminiRefiner, RankedClip, RenderPlan, plan_edit


def test_documented_quickstart():
    document = (Path(__file__).resolve().parents[2] / "docs" / "planner.md").read_text(encoding="utf-8")
    example = document.split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    exec(compile(example, "docs/planner.md quickstart", "exec"), namespace)
    plan = namespace["plan"]
    assert plan.duration == 14
    assert [c.phase for c in plan.clips] == ["hook", "build_up", "climax"]


def clip(i, *, score=None, label="highlight", kind=None, **signals):
    return dict(id=str(i), start=i * 20, end=i * 20 + 12,
        score=i if score is None else score, label=label,
        caption=f"Moment {i}", reaction_label=None, game_profile="fps",
        signals=dict(action_time=i * 20 + 8, kind=kind or f"kind_{i % 3}", **signals))


def test_story_budget_and_determinism():
    inputs = [clip(i) for i in range(8)]
    plan = plan_edit(inputs, target_length=30)
    assert plan.duration == pytest.approx(30)
    assert plan.clips[0].phase == "hook"
    assert plan.clips[0].start == 0 and plan.clips[0].duration <= 3
    assert plan.clips[0].source_id == plan.clips[-1].source_id == "7"
    assert plan.clips[-1].phase == "climax"
    assert plan.clips[1].phase == "build_up"
    assert [c.score for c in plan.clips[1:]] == sorted(c.score for c in plan.clips[1:])
    assert len({c.source_id for c in plan.clips[1:]}) == len(plan.clips) - 1
    assert plan.text[-1].role == "outro"
    assert plan.text[-1].start + plan.text[-1].duration == pytest.approx(plan.duration)
    assert plan.model_dump() == plan_edit(reversed(inputs), target_length=30).model_dump()
    assert RenderPlan.model_validate_json(plan.model_dump_json()) == plan


def test_mean_roast_arc_uses_worst_fail_last():
    inputs = [clip(1, score=100), *[clip(i, label="lowlight") for i in range(2, 7)]]
    nice = plan_edit(inputs, mode="nice", style="meme edit", target_length=28)
    mean = plan_edit(inputs, mode="mean", style="meme edit", target_length=28)
    assert nice.clips[-1].source_id == "1"
    assert mean.clips[-1].source_id == "6"
    assert mean.clips[1].phase == "setup" and mean.clips[1].label == "highlight"
    assert all(c.label == "lowlight" for c in mean.clips[2:])
    assert any(c.phase == "fail" for c in mean.clips)
    assert any(t.role == "meme" for t in mean.text)
    assert not any(t.role == "meme" for t in nice.text)
    assert mean.reactions[-1].label == "roast"
    assert "spongebob_fail" in {s.name for s in mean.sfx}


@pytest.mark.parametrize("style", ["hype montage", "clean edit", "meme edit", "cinematic"])
def test_effects_speed_peak_trims_and_styles(style):
    inputs = [clip(1), clip(2, clutch=True, multikill=True, kill_time=48)]
    plan = plan_edit(inputs, style=style, target_length=15, aspect="9:16")
    c = plan.clips[-1]
    assert c.source_start <= 48 < c.source_end
    assert c.peak == pytest.approx(c.start + (48 - c.source_start) / c.speed)
    assert c.duration == pytest.approx((c.source_end - c.source_start) / c.speed)
    names = {e.name for e in plan.effects if e.clip_id == c.id}
    if style in ("hype montage", "cinematic"):
        assert c.speed == 0.5 and "slow_motion" in names
    else:
        assert c.speed == 1 and "slow_motion" not in names
    if style in ("hype montage", "meme edit"):
        assert {"flash_white", "zoom_in_center"} <= names
        flash = next(e for e in plan.effects if e.name == "flash_white" and e.clip_id == c.id)
        assert flash.start == pytest.approx(c.peak)
    if style == "clean edit":
        assert not plan.effects and not plan.sfx
    if style == "cinematic":
        assert "vignette" in names
    assert all(r.position == "top_right" for r in plan.reactions)
    assert plan.reactions[-1].start == pytest.approx(c.peak)
    assert all(e.name in VIDEO_EFFECTS for e in plan.effects)
    assert all(s.name in SOUND_EFFECTS for s in plan.sfx)
    assert plan.music.energy_curve[-2].energy == 1
    assert plan.music.energy_curve[-1].energy < plan.music.energy_curve[-2].energy


def test_variety_includes_teaser_and_climax_even_with_no_alternatives():
    plan = plan_edit([clip(i, kind="kill") for i in range(10)])
    assert len(plan.clips) == 2
    assert plan.clips[-1].source_id == "9"
    assert any("variety" in note for note in plan.notes)


def test_variety_selects_lower_ranked_alternatives_and_reconsiders_candidates():
    inputs = [clip(i, kind="kill") for i in range(2, 10)] + [clip(1, kind="clutch")]
    plan = plan_edit(inputs, target_length=20)
    assert plan.duration == pytest.approx(20)
    assert [c.source_id for c in plan.clips] == ["9", "1", "8", "9"]


def test_mean_fallback_does_not_repeat_setup_source():
    plan = plan_edit([clip(i) for i in range(8)], mode="mean", target_length=60)
    ids = [c.source_id for c in plan.clips[1:]]
    assert len(ids) == len(set(ids))


def test_event_at_source_start_and_end_trims_stay_in_bounds():
    for peak in (0, 11.999):
        c = clip(0)
        c["signals"]["action_time"] = peak
        plan = plan_edit([c], target_length=8)
        for item in plan.clips:
            assert 0 <= item.source_start <= peak < item.source_end <= 12


def test_kill_timing_is_distinct_from_action_timing():
    plan = plan_edit([clip(0, kill_time=8.2)], target_length=8)
    c = plan.clips[-1]
    flash = next(e for e in plan.effects if e.clip_id == c.id and e.name == "flash_white")
    assert flash.start == pytest.approx(c.start + (8.2 - c.source_start) / c.speed)


def test_empty_short_budget_and_missing_label():
    assert plan_edit([]).duration == 0
    c = clip(0)
    c.update(end=0.2, signals={})
    assert not plan_edit([c]).clips
    plan = plan_edit([clip(1)], target_length=1)
    assert len(plan.clips) == 1 and plan.clips[0].phase == "hook_climax"
    assert plan.duration == 1
    fallback = plan_edit([clip(1)], mode="mean")
    assert any("unavailable" in n for n in fallback.notes)


def test_short_clutch_source_can_be_slowed_for_minimum_length():
    c = clip(0, clutch=True)
    c.update(end=0.6, signals={"clutch": True, "action_time": 0.3})
    plan = plan_edit([c], target_length=5)
    assert all(x.speed == 0.5 for x in plan.clips)
    assert all(1 <= x.duration <= 6 for x in plan.clips)


@pytest.mark.parametrize("kwargs", [
    {"target_length": 0}, {"target_length": float("nan")}, {"target_length": float("inf")},
    {"min_clip_length": 4}, {"max_clip_length": 0.5}, {"mode": "evil"}, {"aspect": "4:3"},
])
def test_invalid_options(kwargs):
    with pytest.raises(ValidationError):
        plan_edit([clip(1)], **kwargs)


@pytest.mark.parametrize("patch", [
    {"end": 0}, {"score": float("nan")}, {"signals": {"action_time": 99}},
    {"signals": {"kill_time": float("inf")}}, {"label": "good"},
])
def test_invalid_inputs(patch):
    with pytest.raises(ValidationError):
        plan_edit([clip(1) | patch])


def test_duplicate_and_mutated_inputs_rejected():
    with pytest.raises(ValueError, match="unique"):
        plan_edit([clip(1), clip(1)])
    c = RankedClip.model_validate(clip(1))
    c.end = 0
    with pytest.raises(ValidationError):
        plan_edit([c])


def test_mocked_gemini_refinement_only_changes_caption():
    generate = Mock(return_value=SimpleNamespace(text='{"captions":[{"text_index":0,"content":"What a finish!"}]}'))
    client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    original = plan_edit([clip(1)])
    refined = plan_edit([clip(1)], refiner=GeminiRefiner(client, "mock-model"))
    assert refined.text[0].content == "What a finish!"
    expected = original.model_dump()
    expected["text"][0]["content"] = "What a finish!"
    assert refined.model_dump() == expected
    generate.assert_called_once()
    args = generate.call_args.kwargs
    assert args["model"] == "mock-model"
    assert "RenderPlan data:" in args["contents"][0]
    assert "response_json_schema" in args["config"]


@pytest.mark.parametrize("response", [
    "not json", {}, {"captions": [{"text_index": 500, "content": "x"}]},
    {"captions": [{"text_index": 0, "content": "x", "duration": 1000}]},
    {"captions": [{"text_index": 0, "content": "x"}] * 2},
    {"clips": []}, {"captions": [{"text_index": 0, "content": "x" * 241}]},
])
def test_refinement_falls_back_atomically(response):
    original = plan_edit([clip(1)])
    refined = plan_edit([clip(1)], refiner=Mock(return_value=response))
    assert refined.clips == original.clips and refined.text == original.text
    if response != {}:
        assert "refinement" in refined.notes[-1]


def test_provider_failure_does_not_leak_exception():
    plan = plan_edit([clip(1)], refiner=Mock(side_effect=RuntimeError("secret-token")))
    assert "secret-token" not in plan.model_dump_json()
    assert "refinement" in plan.notes[-1]


@pytest.mark.parametrize("field,patch", [
    ("effects", {"clip_id": "clip_0", "start": 0, "duration": 1, "name": "unknown"}),
    ("sfx", {"clip_id": "clip_0", "start": 0, "duration": 1, "name": "unknown"}),
    ("effects", {"clip_id": "missing", "start": 0, "duration": 1, "name": "shake"}),
    ("effects", {"clip_id": "clip_0", "start": 0, "duration": 100, "name": "shake"}),
])
def test_render_contract_rejects_bad_placements(field, patch):
    data = plan_edit([clip(1)]).model_dump()
    data[field] = [patch]
    with pytest.raises(ValidationError):
        RenderPlan.model_validate(data)


def test_randomized_bounds_variety_and_source_integrity():
    rng = random.Random(12)
    for _ in range(200):
        inputs = []
        for i in range(rng.randint(1, 20)):
            start = i * 20
            duration = rng.uniform(0.05, 15)
            c = clip(i, score=rng.uniform(-20, 100), label=rng.choice(["highlight", "lowlight"]),
                clutch=rng.choice([True, False]), multikill=rng.choice([True, False]))
            c.update(end=start + duration)
            c["signals"]["action_time"] = start + duration * rng.uniform(0, 0.999)
            inputs.append(c)
        budget = rng.uniform(1, 60)
        plan = plan_edit(inputs, mode=rng.choice(["nice", "mean"]), target_length=budget,
            style=rng.choice(["hype montage", "clean edit", "meme edit", "cinematic"]))
        assert plan.duration <= budget + 1e-6
        RenderPlan.model_validate(plan.model_dump())
        sources = {c["id"]: c for c in inputs}
        for c in plan.clips:
            source = sources[c.source_id]
            assert source["start"] - 1e-6 <= c.source_start < c.source_end <= source["end"] + 1e-6
            assert 1 - 1e-6 <= c.duration <= 6 + 1e-6
