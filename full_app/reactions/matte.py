"""Offline light-background matting. No model downloads or network calls."""
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np


class LightMatte:
    """Border-connected color key; keep enclosed whites and stabilize static edges."""

    def __init__(self, low=10., high=65., smoothing=.25, segmenter=None):
        if not 0 <= low < high <= 255 or not 0 <= smoothing < 1:
            raise ValueError('Require 0 <= low < high <= 255 and 0 <= smoothing < 1')
        self.low, self.high, self.smoothing = low, high, smoothing
        self.previous = None
        self.segmenter = segmenter

    def __call__(self, rgb):
        pixels = rgb.astype(np.float32)
        border = np.concatenate((pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]))
        if np.median(border, axis=0).min() < 160:
            raise ValueError('Expected a near-uniform light background at the frame border')
        # LAM backgrounds often have a subtle vertical cream/green gradient.
        # Interpolate clean side borders instead of assuming a single white RGB.
        left = np.median(pixels[:, :3], axis=1)[:, None, :]
        right = np.median(pixels[:, -3:], axis=1)[:, None, :]
        left = cv2.GaussianBlur(left, (1, 31), 8).reshape(left.shape)
        right = cv2.GaussianBlur(right, (1, 31), 8).reshape(right.shape)
        weight = np.linspace(0, 1, rgb.shape[1])[None, :, None]
        background = left*(1-weight)+right*weight
        distance = np.max(np.abs(pixels - background), axis=2)
        candidate = (distance < self.low).astype(np.uint8)
        _, labels = cv2.connectedComponents(candidate, connectivity=8)
        border_ids = np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))
        border_ids = border_ids[border_ids != 0]
        outside = np.isin(labels, border_ids)
        support = (~outside).astype(np.uint8)
        if self.segmenter is not None:
            support = self.segmenter.segment(rgb, 'person head, hair, glasses and beard', support)
            outside = support == 0
        radius = max(3, round(min(rgb.shape[:2])*.025))
        core = (cv2.erode(support, np.ones((2*radius+1, 2*radius+1), np.uint8)) > 0) | (distance >= self.high)
        if not core.any():
            self.previous = np.zeros(rgb.shape[:2], np.float32)
            return np.zeros((*rgb.shape[:2], 4), np.uint8)
        # Estimate edge coverage against the nearest opaque foreground color.
        # This removes the pale premultiplied fringe rather than just making it transparent.
        _, nearest = cv2.distanceTransformWithLabels((~core).astype(np.uint8), cv2.DIST_L2, 5,
                                                     labelType=cv2.DIST_LABEL_PIXEL)
        colors = np.zeros((int(nearest.max())+1, 3), np.float32)
        colors[nearest[core]] = pixels[core]
        foreground = colors[nearest]
        direction = background-foreground
        alpha = np.clip(np.sum((background-pixels)*direction, axis=2) /
                        np.maximum(np.sum(direction*direction, axis=2), 1), 0, 1)
        alpha = np.where(core, 1., np.where(outside, 0., alpha))
        if self.previous is not None:
            stable = np.abs(alpha-self.previous) < .12
            alpha = np.where(stable, alpha*(1-self.smoothing)+self.previous*self.smoothing, alpha)
        self.previous = alpha
        # Undo light background contamination in fractional edge pixels (straight alpha).
        color = (pixels-(1-alpha[..., None])*background) / np.maximum(alpha[..., None], .01)
        color[alpha == 0] = 0
        return np.dstack((np.clip(color, 0, 255).astype(np.uint8),
                          np.rint(alpha*255).astype(np.uint8)))


def _probe(path):
    return json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams',
                                              '-show_format', '-of', 'json', str(path)]))


def _inside(root, name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Pack paths must be nonempty strings')
    path = (root/name).resolve()
    if not path.is_relative_to(root):
        raise ValueError('Pack paths must stay inside the pack')
    return path


def save_check(path, rgb, rgba):
    """Original, dark gameplay-like test pattern, bright test pattern; no real gameplay required."""
    h, w = rgb.shape[:2]
    pattern = subprocess.check_output(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                                      f'testsrc2=s={w}x{h}', '-frames:v', '1',
                                      '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'])
    pattern = np.frombuffer(pattern, np.uint8).reshape(h, w, 3).astype(float)
    alpha = rgba[..., 3:4].astype(float)/255
    panels = [rgb]
    for background in (pattern*.18, pattern*.18+205):
        panels.append(np.clip(rgba[..., :3]*alpha + background*(1-alpha), 0, 255).astype(np.uint8))
    cv2.imwrite(str(path), cv2.cvtColor(np.concatenate(panels, axis=1), cv2.COLOR_RGB2BGR))


def matte_clip(source, alpha_path, mask_path, *, qa_dir=None, low=10., high=65., smoothing=.25,
               sam_local=False):
    """Produce lossless grayscale H.264 matte and decontaminated VP9 alpha, matching CFR frames."""
    started = time.monotonic()
    info = _probe(source)
    video = next(s for s in info['streams'] if s['codec_type'] == 'video')
    width, height = video['width'], video['height']
    fps = video['r_frame_rate']
    from fractions import Fraction
    if Fraction(fps) <= 0 or Fraction(video['avg_frame_rate']) != Fraction(fps):
        raise ValueError('Matting requires constant frame rate; normalize variable-rate sources first')
    backend = None
    if sam_local:
        # Explicit local-only refinement; missing torch/checkpoints fall back to the color seed.
        from sam.backends import BoundedBackend, Config
        backend = BoundedBackend(Config(backend='local', checkpoint=os.getenv('SAM2_CHECKPOINT', ''),
                                        timeout=30, budget=120))
    matte = LightMatte(low, high, smoothing, segmenter=backend)
    command = ['ffmpeg', '-v', 'error', '-y', '-threads', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba',
               '-s', f'{width}x{height}', '-r', fps, '-i', '-', '-filter_complex_threads', '1',
               '-filter_complex', '[0:v]split[a][m];[m]alphaextract[mask]',
               '-map', '[a]', '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-auto-alt-ref', '0',
               '-deadline', 'good', '-cpu-used', '4', '-crf', '18', '-b:v', '0', '-threads', '2',
               str(alpha_path), '-map', '[mask]', '-c:v', 'libx264', '-preset', 'fast',
               '-crf', '0', '-pix_fmt', 'yuv420p', '-threads', '2', str(mask_path)]
    decode = subprocess.Popen(['ffmpeg', '-v', 'error', '-threads', '1', '-i', str(source),
                               '-map', '0:v:0', '-fps_mode', 'passthrough', '-threads', '1',
                               '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL)
    frames = 0
    expected = int(video.get('nb_frames', 0))
    checkpoints = {0, expected//2, max(0, expected-2)}
    with tempfile.TemporaryFile() as errors:
        encode = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
        try:
            while True:
                raw = decode.stdout.read(width*height*3)
                if not raw:
                    break
                if len(raw) != width*height*3:
                    raise RuntimeError('Incomplete decoded frame')
                rgb = np.frombuffer(raw, np.uint8).reshape(height, width, 3)
                rgba = matte(rgb)
                encode.stdin.write(rgba.tobytes())
                if qa_dir is not None and frames in checkpoints:
                    qa_dir = Path(qa_dir)
                    qa_dir.mkdir(parents=True, exist_ok=True)
                    save_check(qa_dir/f'{Path(source).stem}-{frames:04d}.jpg', rgb, rgba)
                frames += 1
            encode.stdin.close()
            if encode.wait() or decode.wait() or not frames or (expected and frames != expected):
                errors.seek(0)
                raise RuntimeError(f'Matting failed: {errors.read().decode(errors="replace")[-2000:]}')
        finally:
            if encode.poll() is None:
                encode.kill()
            if decode.poll() is None:
                decode.kill()
            encode.wait()
            decode.wait()
            decode.stdout.close()
            if not encode.stdin.closed:
                encode.stdin.close()
            if backend is not None:
                backend.close()
    return {'frames': frames, 'seconds': round(time.monotonic()-started, 3)}


def matte_pack(folder, *, qa_dir=None, force=False, only=None, **options):
    """Resume safely; merge each result into the latest manifest so appended clips survive."""
    root = Path(folder).resolve()
    manifest = root/'pack.json'
    snapshot = json.loads(manifest.read_text(encoding='utf-8'))
    results = []
    for entry in snapshot['clips']:
        ident = entry['id']
        if only and ident not in only:
            continue
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', ident):
            raise ValueError('Clip ID is not safe for an output filename')
        if entry.get('background') != 'light':
            continue
        if not force and any(entry.get(key) and _inside(root, entry[key]).is_file() for key in ('alpha_file', 'mask_file')):
            results.append({'id': ident, 'skipped': True})
            continue
        source = _inside(root, entry['file'])
        alpha_name, mask_name = f'{ident}.alpha.webm', f'{ident}.mask.mp4'
        alpha_path, mask_path = _inside(root, alpha_name), _inside(root, mask_name)
        if source in (alpha_path, mask_path):
            raise ValueError('Matte output would overwrite the original')
        with tempfile.TemporaryDirectory(prefix='.matte-', dir=root) as temp:
            temp = Path(temp)
            result = matte_clip(source, temp/'alpha.webm', temp/'mask.mp4', qa_dir=qa_dir, **options)
            os.replace(temp/'alpha.webm', alpha_path)
            os.replace(temp/'mask.mp4', mask_path)
            latest = json.loads(manifest.read_text(encoding='utf-8'))
            match = next((clip for clip in latest['clips'] if clip['id'] == ident), None)
            if match is None or match['file'] != entry['file']:
                raise RuntimeError('Clip changed during matting; manifest was not updated')
            match.update(alpha_file=alpha_name, mask_file=mask_name)
            (temp/'pack.json').write_text(json.dumps(latest, indent=2)+'\n', encoding='utf-8')
            os.replace(temp/'pack.json', manifest)
        result = {'id': ident, **result}
        results.append(result)
        print(json.dumps(result), flush=True)
    return results
