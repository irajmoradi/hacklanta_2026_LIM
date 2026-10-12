"""Deterministic narrated motion graphics, rendered on the Linux ffmpeg runner.

No generative API calls. Runtime evidence/media/audio live only in ignored paths.
"""
import argparse
from functools import lru_cache
import hashlib
import json
import math
import re
from pathlib import Path
import subprocess
import time
import wave

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from narration import PLAYBACK

HERE = Path(__file__).resolve().parent
W, H, FPS = 1920, 1080, 30
BG, FG, MUTED, LIME, PURPLE = "#090d13", "#f4f4ed", "#a4b0be", "#dcff55", "#ae97ff"


def run(args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *map(str, args)], check=True)


def probe(path):
    return json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]))


def duration(path):
    return float(probe(path)["format"]["duration"])


def read(path):
    return json.loads(Path(path).read_text())


def select_source(root, wait_minutes=40):
    """Check now, then every five minutes, for at most forty minutes."""
    start = time.monotonic()
    deadline = start + wait_minutes * 60
    while True:
        latest = root / "demo02"
        if (latest / "montage_landscape.mp4").exists():
            # Fail visibly if upstream delivered an incomplete MP4, never silently mislabel.
            probe(latest / "montage_landscape.mp4")
            return latest
        if time.monotonic() >= deadline:
            return root / "demo01"
        print("DEMO-02 montage pending; next check in five minutes", flush=True)
        # Short sleeps allow graceful interruption; asset checks remain five minutes apart.
        next_check = min(time.monotonic() + 300, deadline)
        while time.monotonic() < next_check:
            time.sleep(min(30, max(0, next_check - time.monotonic())))


def evidence(source):
    analysis = read(source / "analysis.json")
    land_path = source / "landscape.json"
    if not land_path.exists():
        land_path = source / "nice_landscape.json"
    land = read(land_path) if land_path.exists() else analysis
    timings = analysis.get("timings", {})
    lt = land.get("timings", {})
    note = "Recorded stage times · render includes share kit"
    if source.name == "demo01":
        e = read(source / "evidence.json")
        timings = e["cold_analysis_timings"]
        lt = e["landscape_timings"]
        note = "DEMO-01 · combined Gemini stage · editor-reviewed picks"
    values = [timings.get("signals"), timings.get("window_scoring"),
              lt.get("edit_plan", timings.get("edit_plan")), lt.get("render"), lt.get("social")]
    if any(v is None for v in values):
        raise ValueError(f"Missing measured pipeline timings in {source}; never invent numbers")
    return {"source": source.name, "candidates": len(analysis["candidates"]),
            "scored": len(analysis.get("window_scores", [])),
            "seconds": [float(v) for v in values], "note": note,
            "provenance": [str(source / "analysis.json"), str(land_path)]}


def captions(alignment, speaker, offset):
    chars = alignment["characters"]
    starts = alignment["character_start_times_seconds"]
    ends = alignment["character_end_times_seconds"]
    groups, begin = [], 0
    for i, char in enumerate(chars):
        text = "".join(chars[begin:i + 1])
        if (char in ".!?" or (char == " " and len(text.strip()) >= 42) or i == len(chars) - 1):
            if text.strip():
                groups.append({"speaker": speaker, "text": text.strip(),
                               "start": offset + starts[begin], "end": offset + ends[i]})
            begin = i + 1
    return groups


def timeline(cache):
    blocks, subs, cursor = [], [], 0.5
    for i, cache_id in enumerate(PLAYBACK):
        meta = read(cache / f"voice_{cache_id}.json")
        length = duration(cache / f"voice_{cache_id}.mp3")
        block = {"id": i, "cache_id": cache_id, "start": cursor, "end": cursor + length,
                 "speaker": meta["speaker"], "text": meta["text"]}
        alignment = meta["alignment"]
        joined = "".join(alignment["characters"])
        block["words"] = [{"text": m.group(), "start": cursor + alignment["character_start_times_seconds"][m.start()]}
                          for m in re.finditer(r"\S+", joined)]
        blocks.append(block)
        subs.extend(captions(meta["alignment"], meta["speaker"], cursor))
        cursor += length + (0.55 if i in (1, 4, 6) else 0.35)
    total = max(60, math.ceil(cursor + 3))
    if total > 90:
        raise ValueError("Narration exceeds 90 seconds; no silent truncation")
    return blocks, subs, total


def beats_for(blocks, total):
    styles = [
        [("title", "REMEMBER", "THE PLAY."), ("monitor", "FIND", "THE MOMENT."), ("wipe", "LESS", "SCRUBBING."), ("title", "MEET", "LIM STUDIO.")],
        [("monitor", "KEEP", "THE CLUTCH."), ("phone", "KEEP", "THE CHAOS."), ("bruh", "MISSED", "THAT SHOT.")],
        [("signal", "01", "SIGNALS"), ("pipeline", "02", "GEMINI"), ("pipeline", "03", "PLANNER"), ("pipeline", "04", "RENDER")],
        [("pipeline", "05", "SHARE KIT"), ("ui", "CHECK", "THE PICKS."), ("ui", "TRIM.", "REORDER."), ("stats", "REAL RUN.", "REAL NUMBERS.")],
        [("monitor", "THAT ONE", "STAYS."), ("bruh", "THIS ONE?", "BRUH."), ("phone", "NICE CUT.", "ROAST CUT.")],
        [("wipe", "SAME MATCH.", "NEW EDIT."), ("monitor", "WATCH", "IT WIDE."), ("phone", "TAKE IT", "VERTICAL."), ("share", "EXPORT.", "READY TO POST.")],
        [("title", "LESS", "SCRUBBING."), ("monitor", "MORE", "WATCHING."), ("share", "KEEP", "THE SHARE KIT."), ("monitor", "RUN", "THAT BACK.")],
        [("monitor", "YOUR", "HIGHLIGHTS."), ("bruh", "YOUR", "DECISIONS."), ("end", "LIM STUDIO", "Make every play count")],
    ]
    beats = []
    for block, patterns in zip(blocks, styles):
        start = 0 if block["id"] == 0 else block["start"] - 0.15
        end = blocks[block["id"] + 1]["start"] - 0.15 if block["id"] < 7 else total
        # Even subdivisions of each spoken passage preserve 1–3 second beats.
        anchors = [
            [None,"Finding","That's","LIM"], [None,"chaos.","And"],
            [None,"Gemini","planner","renderer"], [None,"Check","Trim","Put"],
            [None,"This","Give"], [None,"Watch","vertical.","share"],
            [None,"More","Keep","Wait,"], [None,"questionable","LIM"],
        ][block["id"]]
        starts = [start]
        for j, anchor in enumerate(anchors[1:], 1):
            match = next((w["start"] for w in block.get("words", []) if w["text"] == anchor), start+(end-start)*j/len(patterns))
            starts.append(max(starts[-1]+1, min(end-(len(patterns)-j), match-.08)))
        for j, pattern in enumerate(patterns):
            stop = starts[j+1] if j+1<len(starts) else end
            count = math.ceil((stop-starts[j])/3)
            for k in range(count):
                style,line1,line2=pattern
                beats.append({"start": starts[j]+(stop-starts[j])*k/count,
                              "end": starts[j]+(stop-starts[j])*(k+1)/count,
                              "kind":style,"a":line1,"b":line2,"block":block["id"],"index":len(beats)})
    return beats


@lru_cache(maxsize=200)
def font(size, bold=True):
    return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans" + ("-Bold" if bold else "") + ".ttf", size)


def text(draw, xy, value, size=40, fill=FG, bold=True):
    draw.text(xy, str(value), font=font(size, bold), fill=fill, stroke_width=0)


def fit(draw, xy, value, size, width, fill=FG):
    while draw.textlength(str(value), font=font(size)) > width and size > 16:
        size -= 2
    text(draw, xy, value, size, fill)


def ease(x):
    return 1 - (1 - max(0, min(1, x))) ** 3


class Footage:
    def __init__(self, source, fallback):
        self.paths = {"land": source / "montage_landscape.mp4",
                      "phone": source / "montage_vertical.mp4",
                      "mean": source / "montage_mean_vertical.mp4",
                      "ui": source / "ui_raw.webm",
                      "share": fallback / "ui_raw.webm",
                      "old": fallback / "montage_landscape.mp4"}
        self.caps = {}
        for key, path in self.paths.items():
            if not path.exists() and key == "ui":
                path = fallback / "ui_raw.webm"
                self.paths[key] = path
            if not path.exists() and key in ("phone", "mean"):
                raise FileNotFoundError(f"Required framed export missing: {path}")
            cap = cv2.VideoCapture(str(path))
            if not cap.isOpened():
                raise ValueError(f"Cannot decode {path}")
            self.caps[key] = cap
        self.last = {}
        self.scenes = read(source / "ui_scenes.json")
        self.share_scenes = read(fallback / "ui_scenes.json")
        own_share = next((s for s in self.scenes if "share kit" in s["label"].lower()), None)
        if own_share:
            self.caps["share"].release()
            self.paths["share"] = source / "ui_raw.webm"
            self.caps["share"] = cv2.VideoCapture(str(self.paths["share"]))
            self.share_scenes = self.scenes

    def ui_time(self, mode, local):
        keyword = {"share":"share kit", "THE PICKS.":"evidence", "REORDER.":"trim"}[mode]
        scenes = self.share_scenes if mode == "share" else self.scenes
        scene = next((s for s in scenes if keyword in s["label"].lower()), None)
        if scene is None:
            scene = next((s for s in scenes if "why" in s["label"].lower()), scenes[0])
        return scene["start"] + min(local, max(0,scene["end"]-scene["start"]-.1))

    def get(self, key, seconds, size):
        cap = self.caps[key]
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame = int(seconds * fps) % count
        if self.last.get(key, -2) != frame - 1:
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        ok, bgr = cap.read()
        if not ok:
            raise ValueError(f"Failed decoding {key} frame {frame}")
        self.last[key] = frame
        bgr = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)
        return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

    def close(self):
        for cap in self.caps.values():
            cap.release()


def monitor(image, draw, footage, key, seconds, x=666, y=160, width=1160):
    height = width * 9 // 16
    draw.rounded_rectangle((x-12, y-12, x+width+12, y+height+30), radius=22, fill="#202b37", outline="#475565", width=2)
    image.paste(footage.get(key, seconds, (width, height)), (x, y))
    draw.rounded_rectangle((x+width//2-65, y+height+30, x+width//2+65, y+height+53), radius=5, fill="#33414c")
    draw.rounded_rectangle((x+width//2-190, y+height+53, x+width//2+190, y+height+61), radius=4, fill="#475565")


def frame(t, beat, subs, data, footage, total):
    image = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(image)
    for x in range(0, W, 96):
        d.line((x, 0, x, H), fill="#111a24")
    for y in range(0, H, 96):
        d.line((0, y, W, y), fill="#111a24")
    local = t - beat["start"]
    reveal = ease(local / 0.35)
    dx = int(150 * (1-reveal))
    text(d, (72, 44), "LIM", 38, LIME)
    text(d, (170, 51), "STUDIO / PLAYBACK", 22)
    text(d, (1440, 51), f"EXTENSION   /   {data['source'].upper()}", 22, MUTED)
    d.line((72, 112, 1848, 112), fill="#34424f", width=2)
    kind = beat["kind"]
    tick = local / max(0.01, beat["end"]-beat["start"])
    if kind in ("title", "end", "bruh"):
        if kind == "bruh":
            monitor(image, d, footage, "land", 3 + t, 1190, 215, 620)
            # Deterministic chromatic displacement and scan bars on the BRUH beat.
            for k in range(9):
                shift = int(math.sin(t*77 + k)*35) if local < 0.65 else 0
                d.rectangle((80+shift, 325+k*38, 995+shift, 329+k*38), fill=PURPLE if k%2 else LIME)
            fit(d, (74+dx, 272), beat["a"], 70, 1020)
            fit(d, (68-dx, 420), beat["b"], 164, 1060, LIME)
        elif kind == "end":
            text(d, (100+dx, 205), "LIM STUDIO", 144, LIME)
            text(d, (108, 407), "Make every play count", 76)
            text(d, (110, 570), "github.com/irajmoradi/", 44, MUTED)
            text(d, (110, 630), "hacklanta_2026_LIM", 54)
            d.rounded_rectangle((110, 752, 610, 823), radius=35, fill=LIME)
            text(d, (150, 767), "UPLOAD → EDIT → SHARE", 26, BG)
        else:
            fit(d, (95+dx, 230), beat["a"], 135, 1740)
            # Slide upward behind an opaque mask for the second line reveal.
            fit(d, (90, 425 + int(110*(1-reveal))), beat["b"], 172, 1740, LIME)
            d.rectangle((70, 660, 1840, 810), fill=BG)
            text(d, (103, 720), "GAMEPLAY IN.   YOUR STORY OUT.", 31, MUTED)
    elif kind in ("monitor", "ui", "phone", "share", "wipe"):
        fit(d, (73+dx, 240), beat["a"], 76, 550)
        # Compact left column keeps the actual video unobstructed.
        words = beat["b"].split()
        for j, word in enumerate(words):
            fit(d, (72, 345+j*90), word, 80, 550, LIME)
        if kind == "phone":
            monitor(image, d, footage, "land", t, 666, 245, 770)
            x, y, pw, ph = 1460, 155, 342, 608
            d.rounded_rectangle((x-15,y-18,x+pw+15,y+ph+23), radius=43, fill="#273644", outline=MUTED, width=3)
            key = "mean" if beat["block"] == 4 else "phone"
            image.paste(footage.get(key, t, (pw, ph)), (x,y))
            d.rounded_rectangle((x+115,y-8,x+227,y+10), radius=8, fill=BG)
            d.rounded_rectangle((x+115,y+ph+9,x+227,y+ph+14), radius=3, fill=FG)
            text(d, (1500, 825), "9:16 / SHORT", 24, PURPLE)
        elif kind == "wipe":
            x,y,vw,vh = 666,180,1160,652
            old = footage.get("old", t, (vw,vh))
            new = footage.get("land", t+5, (vw,vh))
            image.paste(old, (x,y))
            split = int(vw*ease(tick))
            image.paste(new.crop((0,0,split,vh)), (x,y))
            d.line((x+split,y,x+split,y+vh), fill=LIME, width=7)
            text(d, (x+24,y+24), "NEW CUT" if data["source"]=="demo02" else "EDITED CUT", 25, LIME)
            d.rectangle((x+820,y+20,x+1140,y+60), fill=BG)
            text(d, (x+836,y+25), "DEMO-01 / EARLIER", 21)
        else:
            key = kind if kind in ("ui", "share") else "land"
            sec = footage.ui_time("share" if kind=="share" else beat["b"],local) if kind in ("ui","share") else t
            monitor(image, d, footage, key, sec)
            if kind == "share":
                for j, label in enumerate(("COVER", "POSTING COPY", "EXPORT")):
                    x=700+j*360
                    d.rounded_rectangle((x, 805, x+325, 865), radius=12, fill=LIME if j==2 else "#24313f")
                    text(d, (x+25, 820), label, 24, BG if j==2 else FG)
        text(d, (74, 788), "REAL FOOTAGE / REAL EXPORT", 22, MUTED)
    elif kind in ("pipeline", "signal", "stats"):
        text(d, (80+dx, 175), "FROM MATCH TO SHARE KIT", 70)
        if kind == "signal":
            for j in range(70):
                height = int(20 + 65*abs(math.sin(j*.63+t*4))*abs(math.cos(j*.13)))
                d.rounded_rectangle((90+j*25,370-height,103+j*25,370+height), radius=5, fill=LIME if j<35 else PURPLE)
            text(d, (80, 460), "MOTION     +     SOUND     +     SCENE CHANGES", 36, MUTED)
        else:
            text(d, (82, 302), f"{data['source'].upper()} / MEASURED PIPELINE", 29, MUTED)
        active = {"SIGNALS":0,"GEMINI":1,"PLANNER":2,"RENDER":3,"SHARE KIT":4}.get(beat["b"], min(4,int(tick*5)))
        labels = ["SIGNALS", "GEMINI", "PLANNER", "RENDER", "SHARE KIT"]
        for j, (label,value) in enumerate(zip(labels,data["seconds"])):
            x,y = 80+j*355,555
            color = LIME if j == active else PURPLE if j < active else MUTED
            d.rounded_rectangle((x,y,x+326,y+213), radius=18, fill="#17212c", outline=color, width=3)
            text(d, (x+22,y+20), f"0{j+1}  {label}", 26, color)
            number = value * ease(local/.7)
            text(d, (x+22,y+80), f"{number:.3f}" if value<1 else f"{number:.1f}", 57)
            text(d, (x+24,y+159), "SECONDS", 20, MUTED)
            if j < 4:
                text(d, (x+331,y+90), "›", 31, LIME if j<active else MUTED)
        if kind == "stats":
            n=int(round(data["candidates"]*ease(local/.7)))
            text(d, (80, 400), f"{n} candidate windows  /  {data['scored']} Gemini assessments", 44, LIME)
        elif kind == "pipeline":
            detail = ["Motion + audio + scene evidence", f"{data['scored']} candidate windows assessed",
                      "Rank → sequence → pacing", "Privacy + effects + final encode", "Covers + posting copy + export"][active]
            text(d, (80, 408), detail, 48, LIME)
        text(d, (82, 803), data["note"], 25, MUTED)
    # Caption every spoken phrase; names remain visible in the same protected band.
    sub = next((s for s in subs if s["start"] <= t < s["end"]+0.08), None)
    d.rounded_rectangle((72, 912, 1848, 1030), radius=18, fill="#1c2734")
    if sub:
        name = sub["speaker"].upper()
        color = PURPLE if name != "NARRATOR" else LIME
        text(d, (102, 932), name, 23, color)
        fit(d, (102, 966), sub["text"], 36, 1695)
    else:
        text(d, (102, 950), "LIM STUDIO  /  MAKE EVERY PLAY COUNT", 28, MUTED)
    d.rectangle((0,1068,int(W*t/total),1079), fill=LIME)
    # Six-frame whip at hard cuts, confined to the picture so captions stay readable.
    if 0 < local < .17 and beat["index"]:
        shift = int((1-local/.17)**2 * 320)
        picture = image.crop((0,125,W,888))
        image.paste(picture, (shift,125))
        d.rectangle((0,125,shift,888), fill=LIME if beat["index"]%2 else PURPLE)
    elif .17 <= local < .37:
        punch = 1 + .035*(1-(local-.17)/.2)
        picture = image.crop((0,125,W,888))
        zoom = picture.resize((int(W*punch),int(763*punch)))
        left,top=(zoom.width-W)//2,(zoom.height-763)//2
        image.paste(zoom.crop((left,top,left+W,top+763)),(0,125))
    return image


def write_srt(subs, target):
    def stamp(seconds):
        ms=round(seconds*1000)
        return f"{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}"
    target.write_text("\n\n".join(f"{i+1}\n{stamp(s['start'])} --> {stamp(s['end'])}\n{s['speaker']}: {s['text']}" for i,s in enumerate(subs))+"\n", encoding="utf-8")


def make_audio(cache, out, blocks, total, source):
    inputs, filters, labels = [], [], []
    for i, block in enumerate(blocks):
        inputs += ["-i", cache/f"voice_{block['cache_id']}.mp3"]
        filters.append(f"[{i}:a]aresample=48000,loudnorm=I=-16:TP=-2:LRA=8,asetpts=PTS-STARTPTS,adelay={round(block['start']*1000)}:all=1[v{i}]")
        labels.append(f"[v{i}]")
    filters.append("".join(labels)+f"amix=inputs=8:normalize=0,apad,atrim=0:{total}[voice]")
    run([*inputs,"-filter_complex", ";".join(filters), "-map","[voice]","-c:a","pcm_s16le",out/"narration.wav"])
    # Original synthesized beat bed: no downloaded or third-party music.
    rate=48000
    t=np.arange(total*rate,dtype=np.float64)/rate
    beat=t%0.5
    kick=np.sin(2*np.pi*(48*beat+8*(1-np.exp(-beat*24))))*np.exp(-beat*18)
    pulse=np.sin(2*np.pi*220*t)*np.exp(-(t%.25)*35)
    bass=np.sin(2*np.pi*55*t)*(.55+.45*np.sin(2*np.pi*2*t))
    samples=(.09*kick+.016*pulse+.025*bass)*np.minimum(1,t)*np.minimum(1,(total-t)/2)
    with wave.open(str(out/"music.wav"),"wb") as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(rate)
        wav.writeframes((samples*32767).astype("<i2").tobytes())
    # Voice sidechain ducks both the music and gameplay; mix has a final true-peak limiter.
    graph=("[0:a]asplit=3[voice][sc1][sc2];"
           "[1:a]volume=0.85[m];[m][sc1]sidechaincompress=threshold=0.015:ratio=8:attack=12:release=240[duckmusic];"
           "[2:a]volume=0.12[g];[g][sc2]sidechaincompress=threshold=0.015:ratio=10:attack=8:release=200[duckgame];"
           f"[voice][duckmusic][duckgame]amix=inputs=3:normalize=0,alimiter=limit=0.89:latency=1,apad,atrim=0:{total},afade=t=out:st={total-1}:d=1[a]")
    run(["-i",out/"narration.wav","-i",out/"music.wav","-stream_loop","-1","-i",source/"montage_landscape.mp4",
         "-filter_complex",graph,"-map","[a]","-t",total,"-c:a","pcm_s16le",out/"mix.wav"])


def render(source, cache, out, preview=False):
    out.mkdir(parents=True,exist_ok=True)
    data=evidence(source)
    blocks, subs, total=timeline(cache)
    beats=beats_for(blocks,total)
    manifest={"evidence":data,"blocks":blocks,"captions":subs,"beats":beats,"duration":total,
              "source":str(source),"synthesis":read(cache/"synthesis_ledger.json")}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    write_srt(subs,out/"captions.srt")
    footage=Footage(source,source.parent/"demo01")
    manifest["media"]={k:str(v) for k,v in footage.paths.items()}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2))
    sheets=[]
    try:
        for b in beats:
            still=frame((b["start"]+b["end"])/2,b,subs,data,footage,total)
            thumb=still.resize((480,270))
            sheets.append(thumb)
        sheet=Image.new("RGB",(1920,270*math.ceil(len(sheets)/4)),BG)
        for i,thumb in enumerate(sheets):
            sheet.paste(thumb,((i%4)*480,(i//4)*270))
        sheet.save(out/"contact_sheet.jpg",quality=90)
        if preview:
            return
        make_audio(cache,out,blocks,total,source)
        cmd=["ffmpeg","-hide_banner","-loglevel","error","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}",
             "-r",str(FPS),"-i","pipe:0","-i",str(out/"mix.wav"),"-c:v","libx264","-threads","4","-preset","fast","-crf","19",
             "-pix_fmt","yuv420p","-c:a","aac","-b:a","160k","-movflags","+faststart","-t",str(total),str(out/"extension_demo_v3.mp4")]
        encoder=subprocess.Popen(cmd,stdin=subprocess.PIPE)
        try:
            for f in range(total*FPS):
                t=f/FPS
                b=next(b for b in beats if b["start"]<=t<b["end"])
                encoder.stdin.write(frame(t,b,subs,data,footage,total).tobytes())
                if f%300==0:
                    print(f"Rendered {t:.0f}/{total}s",flush=True)
        finally:
            encoder.stdin.close()
        if encoder.wait():
            raise RuntimeError("Video encoder failed")
        # Two-pass bitrate budget keeps the Discord version reliably below 20 MB decimal.
        bitrate=int((18_500_000*8/total-96_000)/1000)
        common=["-i",out/"extension_demo_v3.mp4","-vf","scale=1280:720","-c:v","libx264","-threads","4","-b:v",f"{bitrate}k",
                "-preset","fast","-passlogfile",out/"discord_pass"]
        run([*common,"-pass","1","-an","-f","null","/dev/null"])
        run([*common,"-pass","2","-c:a","aac","-b:a","96k","-movflags","+faststart",out/"extension_demo_v3_discord.mp4"])
    finally:
        footage.close()


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",type=Path)
    p.add_argument("--root",type=Path,default=Path("/srv/demo_out"))
    p.add_argument("--wait-minutes",type=float,default=40)
    p.add_argument("--preview",action="store_true")
    p.add_argument("--out",type=Path,default=HERE/"out")
    args=p.parse_args()
    source=args.source or select_source(args.root,args.wait_minutes)
    print("Using",source,flush=True)
    render(source,HERE/"cache",args.out,args.preview)


if __name__ == "__main__":
    main()
