"""Original procedural montage visuals; no downloaded artwork or runtime assets.

Templates stay single-input/single-output so both renderer modes use the existing
one-graph-per-segment placement path. Sizes scale to the short edge for mobile.
"""

HYPE = ('kill', 'headshot', 'multikill', 'clutch', 'ability', 'play')
FAIL = ('death', 'whiff', 'fail')
ALL = HYPE + FAIL
BOLD = {}


def add(name, filters, phase, events=ALL, mood='both', length=.7, text=False):
    BOLD[name] = dict(description=name.replace('_', ' '), filter=filters,
                      category='text' if text else 'distortion', audio_filter=None,
                      events=list(events), mood=mood, intensity=.95, length=length,
                      min_visible_duration=.35, bold=True, phase=phase, word=text)


def word(value, color='white', y='.22', size='.13'):
    return ("drawtext=text='" + value + "':fontfile={fontpath}:"
            "fontsize=min(w\\,h)*" + size + ":fontcolor=" + color +
            ":borderw=5:bordercolor=black:box=1:boxcolor=black@0.35:boxborderw=12:"
            "x=(w-tw)/2+sin(t*35)*w*.012:y=h*" + y + "+abs(sin(t*16))*h*.025")


# Build-up choices deliberately visible even without the following hit.
for name, angle in [('camera_roll_left', '-.075'), ('camera_roll_right', '.075'),
                    ('camera_roll_sway', '.08*sin(t*5)')]:
    add(name, "rotate='"+angle+"':c=black,crop=iw*.86:ih*.86,scale={width}:{height}", 'build')
for name, z in [('push_in', '.84'), ('push_in_tight', '.76'), ('push_in_drift', '.80')]:
    add(name, f"crop=iw*{z}:ih*{z}:x='(iw-ow)/2+sin(t*3)*iw*.025':y=(ih-oh)/2,scale={{width}}:{{height}}", 'build')
for name, color in [('clutch_bars', 'black'), ('clutch_bars_gold', 'black')]:
    add(name, 'drawbox=x=0:y=0:w=iw:h=ih*.14:c='+color+':t=fill,'
        'drawbox=x=0:y=ih*.86:w=iw:h=ih*.14:c='+color+':t=fill,'
        'drawbox=x=0:y=ih*.14:w=iw:h=ih*.008:c=gold:t=fill', 'build', HYPE)

add('punch_blur', 'crop=iw*.69:ih*.69,scale={width}:{height},tmix=frames=3:weights=1 2 4', 'hit')
add('earthquake', "crop=iw*.86:ih*.86:x='(iw-ow)/2+sin(t*67)*iw*.06':y='(ih-oh)/2+cos(t*83)*ih*.06',scale={width}:{height}", 'hit')
add('rgb_split_heavy', 'format=gbrp,rgbashift=rh=24:bh=-24:rv=-8:bv=8:edge=smear', 'hit')
add('vhs_burst', 'chromashift=cbh=24:crh=-24,noise=alls=48:allf=t+u,drawgrid=w=iw:h=6:t=2:c=black@0.6', 'hit')
add('datamosh_burst', 'tmix=frames=5,shuffleplanes=1:2:0:3,noise=alls=25:allf=t', 'hit')
add('deep_fry_flare', 'eq=saturation=4:contrast=2.3:brightness=.12,unsharp=5:5:2,'
    'drawbox=x=iw*.08:y=ih*.16:w=iw*.84:h=ih*.018:c=yellow@0.7:t=fill', 'hit')
for name, color in [('hitmarker_burst', 'white'), ('hitmarker_gold', 'gold'), ('hitmarker_red', 'red'),
                    ('hitmarker_cyan', 'cyan'), ('hitmarker_lime', 'lime')]:
    add(name, 'eq=brightness=.13,'+word('X', color, '.42', '.19'), 'hit', HYPE)
for name, color in [('damage_flash', 'red'), ('damage_pulse', '0xff3300')]:
    # Force an opaque working pixel format before drawbox: on RGBA, drawbox
    # can otherwise change alpha that a later overlay composites a second time.
    # Edge-only vignette: even stacked damage cues leave the crosshair untinted.
    edges = []
    for fraction, alpha in ((.035, .28), (.07, .16), (.11, .10)):
        edges.append(f'drawbox=x=0:y=0:w=iw:h=ih:c={color}@{alpha}:t=min(iw\\,ih)*{fraction}')
    add(name, 'format=yuv420p,'+','.join(edges), 'hit', FAIL, 'roast', .4)

# Original speed streaks, kept at the margins so the crosshair remains readable.
streaks = []
for i in range(8):
    for x in ('.02', '.78'):
        streaks.append(f'drawbox=x=iw*{x}:y=ih*{.08+i*.115:.3f}:w=iw*.20:h=ih*.009:c=white@0.85:t=fill')
add('speed_lines', ','.join(streaks), 'hit')
add('radial_trail', 'crop=iw*.78:ih*.78,scale={width}:{height},tmix=frames=4,'+','.join(streaks), 'hit')

for label in ('SHEESH', 'NO SHOT', 'BRUH', '-1000 AURA', '+1000 AURA', 'COOKED', 'W', 'L'):
    roast = label in ('BRUH', '-1000 AURA', 'COOKED', 'L')
    add('pop_'+label.lower().replace(' ', '_').replace('+', 'plus').replace('-', 'minus'),
        word(label, 'yellow' if roast else 'lime', size='.10' if len(label)>7 else '.15'),
        'after', FAIL if roast else HYPE, 'roast' if roast else 'hype', 1.0, True)
for label in ('ELIMINATED', 'SKILL ISSUE', 'CLIPPED'):
    add('banner_'+label.lower().replace(' ', '_'),
        'format=yuv420p,drawbox=x=0:y=ih*.18:w=iw:h=ih*.22:c=black@0.65:t=fill,'
        "drawtext=text='"+label+"':fontfile={fontpath}:fontsize=min(w\\,h)*.085:"
        'fontcolor=red:borderw=2:bordercolor=black:x=(w-tw)/2:y=h*.29-th/2',
        'after', FAIL, 'roast', 1.2, True)
add('fail_arrow', word('NEXT TIME  >>>', 'yellow', '.43', '.08'), 'after', FAIL, 'roast', 1.1, True)
add('freeze', 'null', 'after', ALL, 'both', 1.0)

# Rain uses original ASCII faces/flames/skulls, not copyrighted emoji glyphs.
for name, face, color, events, mood in [
        ('skull_rain', '(x_x)', 'white', FAIL, 'roast'),
        ('laugh_rain', 'XD', 'yellow', FAIL, 'roast'),
        ('fire_rain', '/W\\\\', 'orange', HYPE, 'hype'),
        ('confetti_ace', '*', 'lime', ('multikill', 'clutch'), 'hype')]:
    parts = []
    for i in range(7):
        parts.append("drawtext=text='"+face+"':fontfile={fontpath}:fontsize=min(w\\,h)*.07:"
                     f"fontcolor={color}:borderw=3:bordercolor=black:x=w*{.03+i*.14:.2f}:"
                     f"y='mod(t*h*.45+h*{i*.17:.2f},h*1.1)-h*.1'")
    add(name, ','.join(parts), 'after', events, mood, 1.2)


def register(registry):
    registry.update(BOLD)
