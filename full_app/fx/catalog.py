"""Complete tagged inventory. Length is the recommended editorial slice, in seconds."""
from models.effects import SOUND_EFFECTS, VIDEO_EFFECTS

FAIL = ('death', 'whiff', 'fail')
HYPE = ('kill', 'headshot', 'multikill', 'clutch', 'ability', 'play')
ROAST_SOUNDS = set('atla_why clown_music faaah i_need_you kinda_cringe leave_me_alone low_honor sad_cat my_leg roblox_death spongebob_fail thats_rough tuco_get_out you_are_an_idiot should_have_died yowai_mo'.split())
ROAST_VIDEO = set('freeze deep_fry desaturate black_and_white moderate_blur heavy_blur text_fail text_rip text_bruh text_lol text_oof'.split())
SPECIAL = {
    'hitmarker': ('kill', 'headshot'), 'zoom_punch': ('kill', 'headshot', 'multikill'),
    'another_one': ('multikill',), 'again_again': ('multikill',),
    'anime_wow': ('clutch', 'headshot'), 'slow_motion': ('clutch',),
    'text_clutch': ('clutch',), 'freeze': FAIL, 'deep_fry': FAIL,
    'shake': ('multikill', 'death', 'ability'), 'flash_white': ('kill', 'multikill', 'ability'),
    'bass_drop': ('kill', 'headshot', 'multikill'), 'impact_hit': ('kill', 'headshot'),
    'za_warudo': ('clutch', 'ability'), 'text_gg': ('clutch', 'play'),
}


def catalog():
    result = {}
    for kind, registry, roasts in [('vfx', VIDEO_EFFECTS, ROAST_VIDEO), ('sfx', SOUND_EFFECTS, ROAST_SOUNDS)]:
        for name, entry in registry.items():
            if name == 'none':
                continue
            roast = name in roasts
            intense = roast or any(s in name for s in ('heavy', 'glitch', 'shake', 'rage', 'invert', 'bass'))
            length = (1.8 if kind == 'sfx' else .65)
            if name.startswith('text_') or name in ('vignette', 'slow_motion', 'speed_2x'):
                length = 1.5
            result[f'{kind}:{name}'] = dict(name=name, kind=kind, description=entry['description'],
                events=list(SPECIAL.get(name, FAIL if roast else HYPE)), mood='roast' if roast else 'hype',
                intensity=.9 if intense else .45, length=length,
                timing='segment-speed' if name in ('slow_motion', 'speed_2x') else 'event')
    return result
