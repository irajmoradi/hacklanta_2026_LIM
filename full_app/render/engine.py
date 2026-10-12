"""Execute a validated plan in isolated scratch space, then publish final_edit.mp4."""

import json
from pathlib import Path
import subprocess
import tempfile

from models.effects import build_vf_chain
from .analysis import detect_beats, motion_track, smooth_track, snap_durations
from .captions import transcribe, write_ass
from .graph import join_graph, music_graph, reframe_graph
from .plan import RenderPlan


def probe(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                             "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


class Renderer:
    def __init__(self, runner, segment_processor=None):
        self.runner = runner
        self.segment_processor = segment_processor
        self.source = runner.source.resolve()
        self.workspace = runner.workspace.resolve()

    def encode(self, arguments, output, directory):
        from services.ffmpeg_runner import HAS_NVENC
        arguments = list(arguments)
        if "-filter_complex" in arguments:
            index = arguments.index("-filter_complex")
            graph_path = directory / f"{output.stem}.filters"
            graph_path.write_text(arguments[index + 1], encoding="utf-8")
            arguments[index:index + 2] = ["-filter_complex_script", str(graph_path)]
        encoders = [["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22"]] if HAS_NVENC else []
        encoders.append(["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-threads", "2"])
        if self.runner.perf:
            from perf.encoders import best, Encoder
            selected = best(threads=2)
            # VAAPI requires graph hwupload; use CPU for graphs ending in ASS/RGB.
            if selected.name == 'h264_vaapi':
                selected = Encoder()
            encoders = [selected.args(), Encoder().args()]
        for encoder in encoders:
            command = ["ffmpeg", "-v", "error", "-y", "-filter_complex_threads", "1",
                       "-filter_threads", "1", *arguments, *encoder, "-pix_fmt", "yuv420p",
                       "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                       "-movflags", "+faststart", str(output)]
            result = subprocess.run(command, cwd=directory, capture_output=True, text=True)
            if result.returncode == 0:
                return output
        raise RuntimeError(f"Render v2 FFmpeg failed: {result.stderr[-2000:]}")

    def render(self, plan):
        plan = RenderPlan.model_validate(plan)
        info = probe(self.source)
        if not any(s["codec_type"] == "video" for s in info["streams"]):
            raise ValueError("Source must have a video stream")
        source_duration = float(info["format"]["duration"])
        if any(s.source_end > source_duration + 0.001 for s in plan.segments):
            raise ValueError("Segment extends past source duration")
        has_audio = any(s["codec_type"] == "audio" for s in info["streams"])
        durations = [s.duration for s in plan.segments]
        # Quantize to whole frames, and use one overlap for the entire timeline.
        durations = [max(1, round(d * plan.fps)) / plan.fps for d in durations]
        cards = [round(c.duration * plan.fps) / plan.fps for c in (plan.intro, plan.outro) if c]
        overlap = (max(1, round(min(plan.transition_duration, min(durations + cards) / 3) * plan.fps))
                   / plan.fps) if plan.transition != "cut" else 0
        if overlap and min(durations + cards) <= 2 * overlap:
            raise ValueError("Clips must be longer than twice the transition overlap")
        music_path = Path(plan.music.path).resolve() if plan.music else None
        if music_path and not music_path.is_file():
            raise ValueError(f"Music file does not exist: {music_path}")
        if plan.music and plan.music.beat_sync:
            beats = plan.music.beats
            if beats is None:
                beats = detect_beats(music_path, sum(durations + cards))
            durations = snap_durations(durations, beats, plan.music.snap_tolerance, overlap,
                                       cards[0] - overlap if plan.intro else 0,
                                       max(1 / plan.fps, 2 * overlap + 1 / plan.fps))
            durations = [round(d * plan.fps) / plan.fps for d in durations]
        self.workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="render_v2_", dir=self.workspace) as temporary:
            directory = Path(temporary)
            paths, timeline = [], []
            segment_captions = {}
            self.caption_events = []
            if plan.intro:
                path, duration = self.card(plan.intro, "intro", plan, directory)
                paths.append(path)
                timeline.append(duration)
            def render_segment(item):
                index, (segment, duration) = item
                points = []
                if segment.sam and segment.sam.subject_track:
                    points = smooth_track(segment.sam.subject_track)
                elif plan.reframe == "motion":
                    points = motion_track(self.source, segment.source_start, duration * segment.speed)
                    for point in points:
                        point.time /= segment.speed
                path = directory / f"clip_{index}.mp4"
                args = ["-ss", str(segment.source_start), "-i", str(self.source)]
                if not has_audio:
                    args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
                graph = reframe_graph(plan.size, plan.reframe, points)
                if segment.speed != 1:
                    graph = graph.replace('[0:v]', '[retimed]')
                    graph = f'[0:v]trim=duration={duration*segment.speed},setpts=(PTS-STARTPTS)/{segment.speed}[retimed];' + graph
                if segment.timed_effects:
                    from .placements import effects_graph
                    graph = graph.replace('[v]', '[placement_input]')
                    graph += effects_graph(segment.timed_effects, plan.size, plan.fps)
                vf, _ = build_vf_chain(segment.video_effects, *plan.size, plan.fps)
                if segment.fx:
                    from fx import Request, Timing, compose
                    extra = compose([Request(e['name'], Timing(duration, e['start'], e['end'], plan.fps),
                                             e.get('params', {})) for e in segment.fx])
                    vf = ','.join(p for p in (vf, extra) if p)
                graph += f";[v]{vf + ',' if vf else ''}fps={plan.fps},setpts=PTS-STARTPTS[outv]"
                audio_input = "0:a:0" if has_audio else "1:a:0"
                from .placements import tempo
                graph += f";[{audio_input}]atrim=duration={duration*segment.speed},asetpts=PTS-STARTPTS,{tempo(segment.speed)}aresample=48000,apad[outa]"
                words = segment.words if plan.captions.enabled else []
                texts = segment.texts if plan.captions.enabled else []
                baked_captions = self.runner.perf and (words or segment.title or texts) and not (
                    plan.captions.enabled and plan.captions.transcribe and not words and not texts and has_audio)
                if baked_captions:
                    ass = directory / f'caption_{index}.ass'
                    write_ass(ass, words, plan.size, plan.preset, plan.captions, duration, segment.title, texts=texts)
                    graph = graph.replace('[outv]', '[uncaptioned]')
                    graph += f';[uncaptioned]ass={ass.name}[outv]'
                if self.runner.perf and segment.sound_effects:
                    from models.effects import SOUND_EFFECTS
                    labels = ['[outa]']
                    next_input = 1 if has_audio else 2
                    for s in segment.sound_effects:
                        file = SOUND_EFFECTS.get(s.sfx_key, {}).get('file')
                        if not file or not Path(file).is_file():
                            continue
                        args += ['-i', str(self.runner.cache.audio(file))]
                        trim = f'atrim=duration={s.duration},' if s.duration else ''
                        graph += (f';[{next_input}:a]{trim}adelay={int(s.offset_in_segment*1000)}:all=1,'
                                  f'volume={s.gain}[sfx{next_input}]')
                        labels.append(f'[sfx{next_input}]')
                        next_input += 1
                    if len(labels) > 1:
                        graph += ''.join([';', *labels, f'amix=inputs={len(labels)}:duration=first[mixed]'])
                        graph = graph.replace('[outa]', '[baseaudio]').replace('[mixed]', '[outa]')
                args += ["-filter_complex", graph, "-map", "[outv]", "-map", "[outa]",
                         "-t", str(duration)]
                self.encode(args, path, directory)
                words = segment.words if plan.captions.enabled else []
                if plan.captions.enabled and plan.captions.transcribe and not words and not texts and has_audio:
                    words = transcribe(path, plan.captions.model)
                if (words or segment.title or texts) and not baked_captions:
                    ass = directory / f"caption_{index}.ass"
                    write_ass(ass, words, plan.size, plan.preset, plan.captions, duration, segment.title, texts=texts)
                    captioned = directory / f"captioned_{index}.mp4"
                    self.encode(["-i", str(path), "-vf", f"ass={ass.name}", "-t", str(duration)],
                                captioned, directory)
                    path = captioned
                segment_captions[index] = [dict(start=w.start, end=min(w.end, duration), text=w.text)
                                           for w in words if w.start < duration]
                segment_captions[index] += [dict(start=t.start, end=min(t.start+t.duration, duration), text=t.content)
                                            for t in texts if t.start < duration]
                if segment.title:
                    segment_captions[index].append(dict(start=0, end=min(3, duration), text=segment.title))
                # Reuse the existing meme SFX registry and mixer in this isolated workspace.
                if segment.sound_effects and not self.runner.perf:
                    from services.ffmpeg_runner import FFmpegRunner
                    helper = FFmpegRunner(directory, self.source, *plan.size, plan.fps)
                    path = helper.overlay_sfx(path, [s.model_dump() for s in segment.sound_effects], index)
                if self.segment_processor:
                    path, duration = self.segment_processor(path, index, segment, duration, directory)
                return path, duration
            work = list(enumerate(zip(plan.segments, durations)))
            if self.runner.perf and self.segment_processor is None:
                from perf.parallel import render_all
                from perf.encoders import best
                results = render_all([lambda item=item: render_segment(item) for item in work], best(threads=2))
            else:
                results = [render_segment(item) for item in work]
            cursor = sum(timeline) - overlap * len(timeline)
            for index, (path, duration) in enumerate(results):
                for event in segment_captions[index]:
                    self.caption_events.append(dict(start=cursor+event['start'],
                                                    end=cursor+min(event['end'], duration), text=event['text']))
                cursor += duration - overlap
                paths.append(path)
                timeline.append(duration)
            if plan.outro:
                path, duration = self.card(plan.outro, "outro", plan, directory)
                paths.append(path)
                timeline.append(duration)
            args = []
            for path in paths:
                args += ["-i", str(path)]
            total = sum(timeline) - overlap * (len(timeline) - 1)
            args += ["-filter_complex", join_graph(timeline, plan.transition, overlap, plan.fps),
                     "-map", "[outv]", "-map", "[outa]", "-t", str(total)]
            joined = None
            if self.runner.perf and plan.transition == 'cut':
                from perf.media import concatenate
                try:
                    joined = concatenate(paths, directory / 'joined.mp4')
                except ValueError:
                    pass  # A segment processor may change codecs or stream layout.
            if joined is None:
                joined = self.encode(args, directory / "joined.mp4", directory)
            if plan.music:
                # Mix audio separately: old FFmpeg schedulers can stop amix early
                # when an independently encoded video stream reaches output -t.
                mixed = directory / "mixed.wav"
                self.runner._run([
                    "ffmpeg", "-v", "error", "-y", "-i", str(joined),
                    "-stream_loop", "-1", "-i", str(music_path),
                    "-filter_complex", music_graph(plan.music.volume, plan.music.duck),
                    "-map", "[outa]", "-t", str(total), "-c:a", "pcm_s16le",
                    "-ar", "48000", "-ac", "2", str(mixed)], "v2 music mix")
                muxed = directory / "music.mp4"
                self.runner._run([
                    "ffmpeg", "-v", "error", "-y", "-i", str(joined), "-i", str(mixed),
                    "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-t", str(total), "-movflags", "+faststart", str(muxed)],
                    "v2 music mux")
                joined = muxed
            output = self.workspace / "final_edit.mp4"
            joined.replace(output)
            return output

    def card(self, card, name, plan, directory):
        duration = round(card.duration * plan.fps) / plan.fps
        width, height = plan.size
        ass = directory / f"{name}.ass"
        write_ass(ass, [], plan.size, plan.preset, plan.captions, duration, card.text,
                  title_duration=duration)
        args = ["-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r={plan.fps}",
                "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                "-vf", f"ass={ass.name}", "-t", str(duration)]
        return self.encode(args, directory / f"{name}.mp4", directory), duration
