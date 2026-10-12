"""Opt-in, declarative render engine. Legacy plans retain their existing behavior."""

from .plan import RenderPlan

__all__ = ["RenderPlan"]


def render_plan(source, plan, preset='landscape', workspace=None, output_path=None):
    """Local convenience adapter shared by the offline demo and Python callers.

    Accept the integrated segment schema; optional privacy belongs to the job API.
    """
    from pathlib import Path
    import copy
    import shutil
    from pipeline import Pipeline
    from services.probe import probe_video
    if workspace is None:
        raise ValueError('workspace is required')
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    data = plan.model_dump(mode='json') if hasattr(plan, 'model_dump') else copy.deepcopy(plan)
    data.setdefault('resolution', 720)
    job = dict(source=str(source), dir=str(workspace), meta=probe_video(source),
               options=dict(preset=preset, privacy=False), warnings=[], clips=[], edit_plan=data)
    Pipeline().render(job, None)
    output = Path(job['output'])
    if output_path is not None and output != Path(output_path):
        shutil.copyfile(output, output_path)
        output = Path(output_path)
    return output


__all__.append('render_plan')
