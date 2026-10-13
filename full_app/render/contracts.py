"""Shared names at the planner, pipeline and renderer boundaries."""
from typing import Literal

Style = Literal['hype montage', 'clean edit', 'meme edit', 'cinematic']
Aspect = Literal['16:9', '9:16', '1:1']
Preset = Literal['landscape', 'vertical', 'square']
ASPECT_PRESETS = {'16:9': 'landscape', '9:16': 'vertical', '1:1': 'square'}
STYLE_IDS = {'hype montage': 'hype_montage', 'clean edit': 'clean_edit',
             'meme edit': 'meme_edit', 'cinematic': 'cinematic'}


class RenderFailure(RuntimeError):
    """A media failure, never a provider failure; detail stays in the cause."""
    code = category = 'render'

    def __init__(self, message='Rendering failed; check media and renderer configuration.'):
        super().__init__(message)
