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
