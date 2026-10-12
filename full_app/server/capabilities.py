"""Only advertise controls that have an implemented HTTP option or route."""
from importlib.util import find_spec


def frontend_capabilities():
    modules = {name: find_spec(name) is not None for name in
               ('profiles', 'audio_ai', 'planner', 'vjepa', 'social', 'ingest', 'fx',
                'narration', 'privacy', 'multipov', 'music', 'perf', 'sam', 'reactions', 'signals')}
    controls = {'profiles': ['game', 'profiles'], 'planner': ['planner_v2', 'planner'],
                'privacy': ['privacy_blur', 'privacy'], 'social': ['share_kit', 'social'],
                'sam': ['sam', 'sam_reframe'], 'multipov': ['multipov', 'team_mode']}
    options = ['window_scoring', 'captions']
    for module, available in modules.items():
        if available:
            options.extend(controls.get(module, [module]))
    return dict(options=options, modules=modules, team_upload=modules['multipov'],
                url_import=False, music_upload=False, chat_upload=False)
