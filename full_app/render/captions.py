"""ASS word pop captions and optional local faster-whisper transcription."""

import re
import warnings

from .plan import Word


def transcribe(path, model_name):
    try:
        from faster_whisper import WhisperModel
        # No implicit model download during a render. Install/cache the model first.
        model = WhisperModel(model_name, device="cpu", compute_type="int8", local_files_only=True)
        segments, _ = model.transcribe(str(path), word_timestamps=True, vad_filter=True)
        return [Word(start=w.start, end=w.end, text=w.word.strip())
                for segment in segments for w in (segment.words or []) if w.end > w.start]
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        warnings.warn(f"Automatic captions unavailable ({type(exc).__name__}); continuing without transcription",
                      RuntimeWarning, stacklevel=2)
        return []


def ass_time(seconds):
    ticks = max(0, round(seconds * 100))
    return f"{ticks // 360000}:{ticks // 6000 % 60:02}:{ticks // 100 % 60:02}.{ticks % 100:02}"


def safe_text(text):
    # Never permit input to inject ASS override blocks or linebreak commands.
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", " ").replace("\r", " ")


def write_ass(path, words, size, preset, options, duration, title=None, title_duration=3, texts=()):
    width, height = size
    margin = round(height * (0.20 if preset == "vertical" else 0.10))
    font = round(min(width, height) * 0.065)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Word,DejaVu Sans,{font},&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,{width // 10},{width // 10},{margin},1
Style: Title,DejaVu Sans,{font},&H0000FFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,8,{width // 10},{width // 10},{height // 10},1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    def fitted(text):
        # Bound even very long unbroken tokens to a single safe-zone line.
        size = min(font, width*.78/max(1, len(text)))
        return r'{\q2\fs' + str(round(size, 2)) + '}' + safe_text(text)
    blocked = {w.casefold() for w in options.profanity}
    for word in sorted(words, key=lambda w: (w.start, w.end)):
        if word.start >= duration:
            continue
        text = word.text
        if options.mask_profanity:
            text = re.sub(r"\w+", lambda m: "*" * len(m[0]) if m[0].casefold() in blocked else m[0], text)
        pop = r"{\fscx85\fscy85\t(0,80,\fscx100\fscy100)}"
        lines.append(f"Dialogue: 0,{ass_time(word.start)},{ass_time(min(word.end, duration))},Word,,0,0,0,,{pop}{fitted(text)}\n")
    for event in texts:
        alignment = r'{\an5}' if event.position == 'center' else ''
        lines.append(f"Dialogue: 1,{ass_time(event.start)},{ass_time(min(duration, event.start+event.duration))},Word,,0,0,0,,{alignment}{fitted(event.content)}\n")
    if title:
        lines.append(f"Dialogue: 1,0:00:00.00,{ass_time(min(title_duration, duration))},Title,,0,0,0,,{safe_text(title)}\n")
    path.write_text("".join(lines), encoding="utf-8")

