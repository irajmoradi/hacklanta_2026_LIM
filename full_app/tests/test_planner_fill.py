"""DEMO-02 target-fill and dead-player regression tests (offline)."""
import pytest
from planner import plan_edit, RenderPlan
from pipeline.ranking import rank_merge
from pipeline.extensions import planner_plan
from pipeline.orchestrator import Pipeline


def rows(n=12):
    return [dict(id=str(i), start=i*20, end=i*20+12, score=n-i,
                 label="highlight", signals={"kill_time": i*20+7}) for i in range(n)]


@pytest.mark.parametrize("target", [20, 30, 60, 59.5])
def test_fill_uniform_candidates_without_overrunning(target):
    plan = plan_edit(rows(), fill_target=True, target_length=target, max_clip_length=10)
    assert plan.duration == pytest.approx(target)
    assert plan == plan_edit(reversed(rows()), fill_target=True, target_length=target, max_clip_length=10)
    assert RenderPlan.model_validate_json(plan.model_dump_json()) == plan
    assert len({c.source_id for c in plan.clips[1:]}) == len(plan.clips)-1
    for c in plan.clips:
        peak = int(c.source_id)*20+7
        assert c.source_start <= peak < c.source_end


def test_insufficient_evidence_reports_shortfall():
    plan = plan_edit(rows(1), fill_target=True, target_length=60)
    assert plan.duration == 8
    assert any("Under budget" in note for note in plan.notes)


def test_dead_player_is_only_recovered_with_death_evidence():
    candidates = [dict(start=i*20, end=i*20+10, score=2, signals={}) for i in range(4)]
    scores = [{**c, "player_alive": alive, "kind": "neutral", "hype": 0,
               "reaction": "bruh", "caption": caption} for c, alive, caption in zip(candidates,
        [False, False, None, False], ["Phoenix dies during the duel", "Spectating a teammate kill",
                                    "Unknown player death", "Death screen combat report"])]
    ranked = rank_merge(candidates, scores, [])
    assert len(ranked) == 1
    assert ranked[0]["type"] == "bad" and ranked[0]["nice_veto"]


def test_pipeline_fills_local_evidence_and_prefers_mean_deaths():
    candidates = [dict(start=i*20, end=i*20+12, score=2, signals={},
                       events=[dict(time=i*20+7, type="kill")]) for i in range(12)]
    scored = [{**c, "player_alive": False, "kind": "neutral", "hype": 0,
               "reaction": "fail", "caption": "Phoenix dies in a duel"} for c in candidates[:3]]
    job = dict(clips=rank_merge(candidates, scored, []), options=dict(mode="nice", max_duration=60),
               game="valorant", warnings=[])
    planner_plan(Pipeline(), job)
    assert job["planner_plan"]["duration"] == 60
    assert all(c["label"] == "highlight" for c in job["planner_plan"]["clips"])
    job["options"].update(mode="mean", max_duration=20, preset="vertical")
    planner_plan(Pipeline(), job)
    assert job["planner_plan"]["duration"] == 20
    assert job["planner_plan"]["clips"][-1]["label"] == "lowlight"


def test_reviewed_moment_precedes_high_scoring_unvalidated_fallback():
    clips=rows()
    clips[-1].update(validated=True, score=.2)
    plan=plan_edit(clips, fill_target=True, target_length=60, max_clip_length=10)
    assert plan.duration == 60
    assert plan.clips[-1].source_id == clips[-1]["id"]
    assert plan.clips[-1].score == .2
    assert len(plan.clips)>2


def test_scarce_lowlights_use_honest_context_to_fill():
    clips=rows()
    clips[0]["label"]="lowlight"
    plan=plan_edit(clips, mode="mean", fill_target=True, target_length=30, max_clip_length=10)
    assert plan.duration == 30
    assert plan.clips[-1].label == "lowlight"
    by_id={c.id:c for c in plan.clips}
    assert all(by_id[t.clip_id].label == "lowlight" for t in plan.text if t.role == "meme")


@pytest.mark.parametrize("preset,target", [("landscape",60),("vertical",30)])
def test_pipeline_default_targets(preset,target):
    candidates=[dict(start=i*20,end=i*20+12,score=2,signals={}) for i in range(12)]
    job=dict(clips=rank_merge(candidates,[],[]),options=dict(preset=preset),warnings=[])
    planner_plan(Pipeline(),job)
    assert job["planner_plan"]["duration"]==target


def test_rejected_user_selection_is_not_used_as_filler():
    candidates=[dict(start=i*20,end=i*20+12,score=2,signals={}) for i in range(12)]
    clips=rank_merge(candidates,[],[])
    for c in clips[1:]:c["keep"]=False
    job=dict(clips=clips,options=dict(max_duration=60),warnings=[])
    planner_plan(Pipeline(),job)
    assert job["planner_plan"]["duration"]==12
    assert {c["source_id"] for c in job["planner_plan"]["clips"]}=={clips[0]["id"]}


def test_grounded_kill_takes_precedence_over_earlier_audio_event():
    c=dict(id="one",start_seconds=0,end_seconds=20,score=1,type="good",
           events=[dict(time=1,type="sustained_audio"),dict(time=15,type="kill")])
    job=dict(clips=[c],options=dict(max_duration=12),warnings=[])
    planner_plan(Pipeline(),job)
    climax=job["planner_plan"]["clips"][-1]
    assert climax["source_start"] < 15 < climax["source_end"]
    assert climax["peak"] == pytest.approx(climax["start"]+15-climax["source_start"])


def test_stronger_late_audio_burst_beats_early_ability_and_scene_cut():
    c=dict(id="one",start_seconds=0,end_seconds=20,score=1,type="good",
           suggested_reaction_label="clutch",events=[dict(time=1,type="scene_cut"),
           dict(time=2,end=3,type="sustained_audio"),dict(time=12,end=16,type="sustained_audio")])
    job=dict(clips=[c],options=dict(max_duration=12),warnings=[])
    planner_plan(Pipeline(),job)
    climax=job["planner_plan"]["clips"][-1]
    assert climax["source_start"] <= 14 < climax["source_end"]
    assert climax["speed"] == .5


def test_explicit_lowlight_precedes_caption_inferred_death():
    clips=[dict(id="inferred",start_seconds=0,end_seconds=15,score=.99,type="bad",source="signals+vlm",nice_veto=True),
           dict(id="explicit",start_seconds=20,end_seconds=35,score=.4,type="bad",source="signals+vlm")]
    job=dict(clips=clips,options=dict(mode="mean",max_duration=20),warnings=[])
    planner_plan(Pipeline(),job)
    assert job["planner_plan"]["clips"][-1]["source_id"]=="explicit"
    assert job["planner_plan"]["duration"]==20


def test_human_review_can_confirm_death_without_promoting_it_in_nice():
    clips=[dict(id="death",start_seconds=0,end_seconds=15,score=.9,type="bad",source="signals+vlm",nice_veto=True,
                editorial_review=True,signals=dict(fail_time=10)),
           dict(id="low",start_seconds=20,end_seconds=35,score=.4,type="bad",source="signals+vlm"),
           dict(id="good",start_seconds=40,end_seconds=55,score=.3,type="good",source="signals+vlm")]
    job=dict(clips=clips,options=dict(mode="mean",max_duration=20),warnings=[])
    planner_plan(Pipeline(),job)
    assert job["planner_plan"]["clips"][-1]["source_id"]=="death"
    job['options']['mode']='nice'
    planner_plan(Pipeline(),job)
    assert all(c['source_id']!='death' for c in job['planner_plan']['clips'])
