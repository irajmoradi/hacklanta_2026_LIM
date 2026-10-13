"""Shared names at the planner, pipeline and renderer boundaries."""
from typing import Literal
from services.provider_errors import MESSAGES, ProviderFailure

Style = Literal['hype montage', 'clean edit', 'meme edit', 'cinematic']
Aspect = Literal['16:9', '9:16', '1:1']
Preset = Literal['landscape', 'vertical', 'square']
ASPECT_PRESETS = {'16:9': 'landscape', '9:16': 'vertical', '1:1': 'square'}
STYLE_IDS = {'hype montage': 'hype_montage', 'clean edit': 'clean_edit',
             'meme edit': 'meme_edit', 'cinematic': 'cinematic'}


# The worker transport currently uses ProviderFailure for every stage. Register
# the renderer's safe category when Pipeline imports FFmpegRunner, in both the
# parent and worker, so its allowlist round trip does not relabel it as Gemini.
MESSAGES.setdefault('render', 'Rendering failed; check media and renderer configuration.')


class RenderFailure(ProviderFailure):
    """A media category on the existing safe stage-error transport."""
    code = category = 'render'

    def __init__(self):
        super().__init__('render')


class RenderInputFailure(RenderFailure, ValueError):
    """Retain ValueError compatibility for local callers and input diagnostics."""
    def __init__(self, detail):
        super().__init__()
        self.args = (str(detail),)
