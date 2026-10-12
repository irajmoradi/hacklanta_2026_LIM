"""Upload probe restricted to recognized local video containers."""
from fractions import Fraction
import json
import subprocess


def probe_upload(path):
    from ingest.media import sniff_video
    sniff_video(path)
    result = subprocess.run([
        'ffprobe', '-v', 'error', '-max_alloc', '67108864',
        '-protocol_whitelist', 'file', '-format_whitelist', 'mov,matroska,webm,avi,flv,mpegts,mpeg',
        '-probesize', '5000000', '-analyzeduration', '5000000',
        '-show_entries', 'format=duration:stream=codec_type,codec_name,duration,avg_frame_rate,width,height:stream_disposition=attached_pic',
        '-of', 'json', str(path)], capture_output=True, check=True, timeout=20)
    data = json.loads(result.stdout)
    video = next(s for s in data['streams'] if s['codec_type'] == 'video' and not s.get('disposition', {}).get('attached_pic'))
    audio = next((s for s in data['streams'] if s['codec_type'] == 'audio'), {})
    duration = float(data['format']['duration'])
    return dict(duration=max(duration, float(video.get('duration') or duration)),
                container_duration=duration, width=video['width'], height=video['height'],
                fps=float(Fraction(video['avg_frame_rate'])), video_codec=video['codec_name'],
                audio_codec=audio.get('codec_name', 'none'))
