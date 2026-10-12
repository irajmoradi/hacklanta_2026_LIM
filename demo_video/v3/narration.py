"""Explicit live ElevenLabs synthesis. Never called by tests or render.py.

One attempt per script block, including failed attempts. No automatic retries.
Credentials stay in memory; only consented selections are printed or cached.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
SCRIPT = [
    ("Narrator", "You remember the play. Finding it in a whole match? That's the slow part. LIM Studio turns gameplay into a cut you can actually share."),
    ("Iraj", "Keep the clutch. Keep the chaos. And yes, keep the moment I absolutely should have hit that shot."),
    ("Narrator", "Start with signals: motion, sound, and scene changes. Gemini scores candidate windows. The planner builds a sequence, then the renderer puts it together."),
    ("Narrator", "These are measured stages from a real run. Look at the evidence, check the picks, trim the edges, and move a clip where it belongs."),
    ("Stefanny", "That one stays. This one? Bruh. Give me the nice cut, then show me the roast."),
    ("Narrator", "The same match, a different edit. Watch it wide, or take it vertical. The share kit brings covers and posting copy along with the export."),
    ("Iraj", "Less scrubbing. More watching. That's the part I want back."),
    ("Narrator", "Your highlights. Your questionable decisions. One place to shape the story. LIM Studio. Make every play count."),
    ("Lance", "These are measured stages from a real run. Check the picks. Trim the edges. Put the best moment first. Yep, that one."),
    ("Mario", "Less scrubbing. More watching. Keep the cover and posting copy with the export. Wait, run that back. That's the part I want to share."),
]

# Retain the eight original cache IDs and spend only two additional calls.
PLAYBACK = (0, 1, 2, 8, 4, 5, 9, 7)


def read_key(path):
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            if name.strip() == "ELEVENLABS_API_KEY":
                return value.strip().strip("\"'")
    raise RuntimeError("ELEVENLABS_API_KEY missing")


def request(key, endpoint, body=None):
    req = urllib.request.Request("https://api.elevenlabs.io/v1/" + endpoint,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"xi-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not dump provider bodies, request headers, or credentials.
        raise RuntimeError(f"ElevenLabs HTTP {exc.code}; attempt remains spent") from None


def choose(voices):
    selected = {}
    people = ("Iraj", "Stefanny", "Lance", "Mario")
    for person in people:
        matches = [v for v in voices if re.search(r"\b" + person + r"\b", v["name"], re.I)
                   and not any(re.search(r"\b" + other + r"\b", v["name"], re.I)
                               for other in people if other != person)]
        if len(matches) != 1:
            raise ValueError(f"Expected one unambiguous consented voice for {person}")
        selected[person] = matches[0]
    stock = [v for v in voices if v.get("category") == "premade"]
    # Chris is a stock conversational, energetic American voice. Never substitute a clone.
    stock.sort(key=lambda v: (not v["name"].lower().startswith("chris"), v["name"]))
    if not stock:
        raise ValueError("No stock narrator available")
    selected["Narrator"] = stock[0]
    return selected


def synthesize(key, selected, cache, api=request):
    cache.mkdir(parents=True, exist_ok=True)
    ledger_path = cache / "synthesis_ledger.json"
    # Exclusive lock also prevents concurrent processes spending the budget twice.
    lock = cache / "synthesis.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        ledger = json.loads(ledger_path.read_text()) if ledger_path.exists() else []
        for i, (speaker, words) in enumerate(SCRIPT):
            voice = selected[speaker]
            digest = hashlib.sha256((voice["voice_id"] + words).encode()).hexdigest()
            audio = cache / f"voice_{i}.mp3"
            meta = cache / f"voice_{i}.json"
            previous = next((x for x in ledger if x["block"] == i), None)
            if previous:
                if previous["sha256"] != digest or not audio.exists() or not meta.exists():
                    raise RuntimeError(f"Block {i} already attempted; refusing regeneration")
                continue
            if len(ledger) >= 10 or sum(x["characters"] for x in ledger) + len(words) >= 2500:
                raise RuntimeError("Synthesis budget exhausted")
            ledger.append({"block": i, "speaker": speaker, "sha256": digest,
                           "characters": len(words), "status": "reserved"})
            temporary = ledger_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(ledger, indent=2))
            temporary.replace(ledger_path)
            result = api(key, f"text-to-speech/{voice['voice_id']}/with-timestamps", {
                "text": words, "model_id": "eleven_multilingual_v2",
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.75,
                                   "style": 0.25, "use_speaker_boost": True, "speed": 1.05}})
            alignment = result.get("alignment") or result["normalized_alignment"]
            audio.write_bytes(base64.b64decode(result["audio_base64"]))
            meta.write_text(json.dumps({"speaker": speaker, "text": words,
                "voice_name": voice["name"], "voice_category": voice.get("category"),
                "alignment": alignment}, indent=2))
            ledger[-1]["status"] = "completed"
            temporary.write_text(json.dumps(ledger, indent=2))
            temporary.replace(ledger_path)
            print(f"Cached block {i}: {speaker} ({len(words)} characters)", flush=True)
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default="C:/Users/mourn/Downloads/hacklanta/.env")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--live-synthesize", action="store_true")
    args = parser.parse_args()
    if not args.list and not args.live_synthesize:
        parser.error("Choose --list or explicitly opt into --live-synthesize")
    key = read_key(args.env_file)
    selected = choose(request(key, "voices")["voices"])
    for speaker, voice in selected.items():
        print(speaker, voice["name"], voice["voice_id"], voice.get("category"))
    if args.live_synthesize:
        synthesize(key, selected, HERE / "cache")


if __name__ == "__main__":
    main()
