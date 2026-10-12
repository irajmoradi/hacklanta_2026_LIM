"""A paid call is reserved before every model request, including video critique."""
from copy import deepcopy
import os
from pathlib import Path

from services.call_budget import CallBudget
from .tools import EditorTools


def starting_plan(job):
    from planner.adapter import to_render_plan
    if job.get('edit_plan'):
        plan = deepcopy(job['edit_plan'])
        if plan.get('version') == 2:
            return to_render_plan(plan)
        if plan.get('render_version') == 2:
            return plan
        # Preserve legacy semantics; reject incompatible effects instead of silently dropping them.
        from render.plan import RenderPlan
        plan['render_version'] = 2
        return RenderPlan.model_validate(plan).model_dump(mode='json')
    if job.get('planner_plan'):
        return to_render_plan(job['planner_plan'])
    from pipeline.extensions import planner_plan
    from pipeline import Pipeline
    plan = planner_plan(Pipeline(), job)
    if not plan:
        raise ValueError('Analyze clips before running the editor')
    return plan


def run_agent(job, instruction, model=None, *, max_steps=16, call_limit=None,
              emit=lambda step: None, cancelled=lambda: False, preview=None):
    limit = int(call_limit if call_limit is not None else os.getenv('EDITOR_AGENT_CALL_BUDGET', '12'))
    if not 0 <= limit <= 100 or not 1 <= max_steps <= 100:
        raise ValueError('Invalid agent limits')
    # Shared with analysis/planning, durable across chat requests and restarts.
    budget = CallBudget(Path(job['dir']) / 'gemini-budget.sqlite3', limit=limit)
    original = deepcopy(job.get('edit_plan'))
    trace = []
    owned_model = model is None
    tools = None
    reason = None
    try:
        draft = starting_plan(job)
        if 'preset' in job.get('options', {}):
            draft['preset'] = job['options']['preset']
        if model is None:
            from .model import GeminiEditor
            model = GeminiEditor()
        if preview is None:
            from .preview import render_preview
            preview = lambda plan, settings: render_preview(job, plan, settings)
        def watch(path):
            import hashlib
            import json
            from .model import Critique
            if cancelled():
                raise RuntimeError('cancelled')
            artifact = Path(path)
            cache = None
            if artifact.is_file():
                digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
                cache = Path(job['dir']) / 'agent_critiques' / (digest + '.json')
                if cache.is_file():
                    try:
                        return Critique.model_validate_json(cache.read_text()).model_dump()
                    except ValueError:
                        pass
            budget.reserve()
            try:
                raw = model.critique(path)
            except Exception as exc:
                raise RuntimeError(f'Critique failed ({type(exc).__name__})') from None
            critique = Critique.model_validate(raw).model_dump()
            if cache:
                cache.parent.mkdir(exist_ok=True)
                temporary = cache.with_suffix('.part')
                temporary.write_text(json.dumps(critique))
                temporary.replace(cache)
            return critique
        tools = EditorTools(job, draft, preview, watch)
        tools.validate()
        context = dict(instruction=instruction, brief=job.get('options', {}).get('prompt', ''),
                       mode=job.get('options', {}).get('mode', 'nice'),
                       target_length=job.get('options', {}).get('max_duration', 180),
                       preset=job.get('options', {}).get('preset', 'landscape'),
                       draft=tools.snapshot())
        feedback = []
        for step in range(max_steps):
            if cancelled():
                reason = 'cancelled'
                break
            if not budget.remaining:
                reason = 'budget_exhausted'
                break
            budget.reserve()
            context['calls_remaining'] = budget.remaining
            context['steps_remaining'] = max_steps-step
            call = model.next(context, feedback)
            if cancelled():
                reason = 'cancelled'
                break
            before = tools.snapshot()
            name, args = call.get('tool', ''), call.get('args', {})
            record = dict(step=step+1, tool=name, args=args,
                          rationale=args.get('rationale', '') if isinstance(args, dict) else '',
                          diff={}, error=None)
            try:
                result = tools.execute(name, args)
                after = tools.snapshot()
                record['diff'] = {key: dict(before=before[key], after=after[key])
                                  for key in before if before[key] != after[key]}
            except ValueError as exc:
                # Validation errors are actionable; provider/renderer exception strings may contain secrets.
                from pydantic import ValidationError
                message = ('; '.join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
                           if isinstance(exc, ValidationError) else str(exc))
                result = {'error': message}
                record['error'] = message
            except Exception as exc:
                record['error'] = f'Tool failed ({type(exc).__name__})'
                trace.append(record)
                emit(deepcopy(record))
                raise
            record['result'] = result
            trace.append(record)
            emit(deepcopy(record))
            feedback.append(dict(tool=name, args=args, result=result))
            if tools.finished:
                break
        else:
            reason = 'step_limit'
    except Exception as exc:
        reason = f'agent_failed:{type(exc).__name__}'
    finally:
        if owned_model and model is not None:
            try:
                model.close()
            except Exception:
                pass
    finished = tools is not None and tools.finished and not cancelled()
    # Unfinished/failed runs never publish a partially edited draft.
    fallback = original if original is not None else (draft if 'draft' in locals() else None)
    return dict(plan=tools.plan if finished else fallback, trace=trace,
                settings=tools.settings if finished else {k: bool(job.get('options', {}).get(k, False)) for k in ('music', 'reactions')},
                summary=tools.summary if finished else 'Retained the starting draft',
                fallback=not finished, reason=None if finished else reason,
                calls_remaining=budget.remaining)
