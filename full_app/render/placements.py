"""Output-local placement filters, independent of source playback speed."""
import re
from models.effects import build_vf_chain


def tempo(speed):
    filters = []
    while speed > 2:
        filters.append('atempo=2')
        speed /= 2
    while speed < .5:
        filters.append('atempo=.5')
        speed *= 2
    return ','.join([*filters, f'atempo={speed}']) + ','


def effects_graph(effects, size, fps, duration=None):
    graph = ''
    for i, effect in enumerate(effects):
        start, length = effect.start, effect.duration
        if effect.name in ('zoom_punch', 'shake', 'chromatic_aberration', 'freeze'):
            from fx import Timing, zoom_punch, screen_shake, chromatic_aberration, _freeze
            builder = dict(zoom_punch=zoom_punch, shake=screen_shake,
                           chromatic_aberration=chromatic_aberration, freeze=_freeze)[effect.name]
            vf = builder(Timing(duration or start+length, start, start+length, fps))
        elif effect.name in ('fade_in', 'fade_out', 'flash_white'):
            direction = 'out' if effect.name == 'fade_out' else 'in'
            color = ':color=white' if effect.name == 'flash_white' else ''
            vf = f'fade=t={direction}:st={start}:d={length}{color}'
        else:
            vf, _ = build_vf_chain([effect.name], *size, fps)
            # Legacy text filters gated at t=0 must instead follow this placement.
            if vf and effect.name.startswith('text_'):
                vf = re.sub(r":enable='[^']*'", '', vf)
        if not vf:
            vf = 'null'
        # Overlay the transformed stream only during its requested interval.
        vf += f',scale={size[0]}:{size[1]},setsar=1'
        incoming = 'placement_input' if i == 0 else f'placed{i-1}'
        graph += (f';[{incoming}]split[plain{i}][effect{i}];[effect{i}]{vf}[filtered{i}];'
                  f"[plain{i}][filtered{i}]overlay=enable='gte(t,{start})*lt(t,{start+length})'[placed{i}]")
    if graph:
        graph += f';[placed{len(effects)-1}]null[vplaced]'
        graph = graph.replace('[vplaced]', '[v]')
    return graph
