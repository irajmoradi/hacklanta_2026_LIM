"""Video effect and sound effect registries.

Video effects use a category-based system for ordered filter chaining.
Multiple effects can be applied per clip — they are sorted by category
order before being joined into one FFmpeg -vf chain.

Category order: speed → distortion → blur/sharpen → color → text → grain/noise → pixelate
"""

from pathlib import Path

# ── Video Effects ─────────────────────────────────────────────────────────────

CATEGORY_ORDER = {
    "speed": 0,
    "transition": 1,
    "distortion": 2,
    "blur": 3,
    "sharpen": 4,
    "color": 5,
    "text": 6,
    "grain": 7,
    "pixelate": 8,
}

VIDEO_EFFECTS = {
    # ── None ──
    "none": {
        "description": "No effect",
        "filter": None,
        "category": "speed",
        "audio_filter": None,
    },

    # ── Speed ──
    "slow_motion": {
        "description": "0.5x slow-mo for epic moments",
        "filter": "setpts=2.0*PTS",
        "category": "speed",
        "audio_filter": "atempo=0.5",
    },
    "speed_2x": {
        "description": "2x speed for filler/transitions",
        "filter": "setpts=0.5*PTS",
        "category": "speed",
        "audio_filter": "atempo=2.0",
    },

    # ── Transitions ──
    "fade_in": {
        "description": "1s fade from black",
        "filter": "fade=t=in:st=0:d=1",
        "category": "transition",
        "audio_filter": None,
    },
    "fade_out": {
        "description": "1s fade to black at end",
        "filter": None,  # applied dynamically
        "category": "transition",
        "audio_filter": None,
    },
    "flash_white": {
        "description": "Brief white flash at start",
        "filter": "fade=t=in:st=0:d=0.15:color=white",
        "category": "transition",
        "audio_filter": None,
    },

    # ── Distortion ──
    "shake": {
        "description": "Camera shake — impact/fail moments",
        "filter": "crop=in_w-20:in_h-20:10*random(0):10*random(1),scale={width}:{height}",
        "category": "distortion",
        "audio_filter": None,
    },
    "zoom_in_center": {
        "description": "Slow Ken Burns zoom into center",
        "filter": "zoompan=z='min(zoom+0.0015,1.3)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}",
        "category": "distortion",
        "audio_filter": None,
    },
    "chromatic_aberration": {
        "description": "RGB channel split — glitchy/broken feel",
        "filter": "split=3[r][g][b];[r]lutrgb=g=0:b=0,crop=iw-4:ih:0:0[r1];[g]lutrgb=r=0:b=0,crop=iw-4:ih:2:0[g1];[b]lutrgb=r=0:g=0,crop=iw-4:ih:4:0[b1];[r1][g1]blend=all_mode=addition[rg];[rg][b1]blend=all_mode=addition",
        "category": "distortion",
        "audio_filter": None,
    },

    # ── Blur ──
    "light_blur": {
        "description": "Subtle gaussian blur — dreamy/flashback feel",
        "filter": "gblur=sigma=1.5",
        "category": "blur",
        "audio_filter": None,
    },
    "moderate_blur": {
        "description": "Medium gaussian blur — transition/death screen",
        "filter": "gblur=sigma=3.0",
        "category": "blur",
        "audio_filter": None,
    },
    "heavy_blur": {
        "description": "Heavy blur — disorientation/drunk effect",
        "filter": "gblur=sigma=6.0",
        "category": "blur",
        "audio_filter": None,
    },

    # ── Sharpen ──
    "light_sharpen": {
        "description": "Subtle sharpen — crisp detail pop",
        "filter": "unsharp=5:5:0.6:5:5:0.0",
        "category": "sharpen",
        "audio_filter": None,
    },
    "moderate_sharpen": {
        "description": "Medium sharpen — enhanced clarity",
        "filter": "unsharp=5:5:1.2:5:5:0.0",
        "category": "sharpen",
        "audio_filter": None,
    },
    "heavy_sharpen": {
        "description": "Aggressive sharpen — hyper-detailed look",
        "filter": "unsharp=5:5:2.0:5:5:0.0",
        "category": "sharpen",
        "audio_filter": None,
    },

    # ── Color ──
    "saturation_boost": {
        "description": "Boosted color saturation — vibrant look",
        "filter": "eq=saturation=1.5",
        "category": "color",
        "audio_filter": None,
    },
    "heavy_saturation": {
        "description": "Heavy saturation — oversaturated/anime style",
        "filter": "eq=saturation=1.8",
        "category": "color",
        "audio_filter": None,
    },
    "desaturate": {
        "description": "Desaturated/washed out — sad/failure moment",
        "filter": "eq=saturation=0.3",
        "category": "color",
        "audio_filter": None,
    },
    "black_and_white": {
        "description": "Full grayscale — dramatic/death moment",
        "filter": "eq=saturation=0",
        "category": "color",
        "audio_filter": None,
    },
    "contrast_pop": {
        "description": "High contrast — punchy/aggressive look",
        "filter": "eq=contrast=1.3",
        "category": "color",
        "audio_filter": None,
    },
    "warm_tint": {
        "description": "Warm golden tint — nostalgic/victory feel",
        "filter": "colorbalance=rs=0.1:gs=0.05:bs=-0.1",
        "category": "color",
        "audio_filter": None,
    },
    "cold_tint": {
        "description": "Cool blue tint — cold/menacing feel",
        "filter": "colorbalance=rs=-0.1:gs=-0.05:bs=0.15",
        "category": "color",
        "audio_filter": None,
    },
    "vignette": {
        "description": "Dark vignette overlay — cinematic framing",
        "filter": "vignette=PI/4",
        "category": "color",
        "audio_filter": None,
    },
    "bright_boost": {
        "description": "Brightness boost — flashy/heavenly moment",
        "filter": "eq=brightness=0.08",
        "category": "color",
        "audio_filter": None,
    },
    "dark_mood": {
        "description": "Darkened — sinister/intense atmosphere",
        "filter": "eq=brightness=-0.1:contrast=1.2",
        "category": "color",
        "audio_filter": None,
    },
    "invert_colors": {
        "description": "Inverted colors — shock/glitch effect",
        "filter": "negate",
        "category": "color",
        "audio_filter": None,
    },

    # ── Text Overlays ──
    "text_highlight": {
        "description": "Big 'HIGHLIGHT' text splash on screen",
        "filter": "drawtext=text='HIGHLIGHT':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=72:fontcolor=white:borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,1.5)'",
        "category": "text",
        "audio_filter": None,
    },
    "text_fail": {
        "description": "Big 'FAIL' text in red",
        "filter": "drawtext=text='FAIL':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=80:fontcolor=red:borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,1.5)'",
        "category": "text",
        "audio_filter": None,
    },
    "text_clutch": {
        "description": "'CLUTCH' text in gold",
        "filter": "drawtext=text='CLUTCH':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=72:fontcolor=gold:borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,1.5)'",
        "category": "text",
        "audio_filter": None,
    },
    "text_rip": {
        "description": "'RIP' text — death/fail moment",
        "filter": "drawtext=text='RIP':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=80:fontcolor=white:borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,1.5)'",
        "category": "text",
        "audio_filter": None,
    },
    "text_nice": {
        "description": "'NICE' text in green — clean play",
        "filter": "drawtext=text='NICE':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=72:fontcolor=lime:borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,1.5)'",
        "category": "text",
        "audio_filter": None,
    },
    "text_bruh": {
        "description": "'BRUH' meme text — dumb/funny fail",
        "filter": "drawtext=text='BRUH':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=80:fontcolor=white:borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,1.5)'",
        "category": "text",
        "audio_filter": None,
    },
    "text_gg": {
        "description": "'GG' text — round/match ending moment",
        "filter": "drawtext=text='GG':fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:fontsize=72:fontcolor=cyan:borderw=3:bordercolor=black:x=(w-text_w)/2:y=(h-text_h)/2:enable='between(t,0,1.5)'",
        "category": "text",
        "audio_filter": None,
    },

    # ── Grain / Noise ──
    "light_grain": {
        "description": "Subtle film grain — cinematic texture",
        "filter": "noise=alls=6:allf=t+u",
        "category": "grain",
        "audio_filter": None,
    },
    "moderate_grain": {
        "description": "Medium film grain — retro/VHS feel",
        "filter": "noise=alls=12:allf=t+u",
        "category": "grain",
        "audio_filter": None,
    },
    "heavy_grain": {
        "description": "Heavy noise — damaged/corrupted footage look",
        "filter": "noise=alls=20:allf=t+u",
        "category": "grain",
        "audio_filter": None,
    },
    "glitch": {
        "description": "Glitch/datamosh noise — error/broken feel",
        "filter": "noise=alls=40:allf=t",
        "category": "grain",
        "audio_filter": None,
    },
}


def build_vf_chain(vfx_list: list[str], width: int = 1920, height: int = 1080, fps: int = 60) -> tuple[str | None, str | None]:
    """Build ordered VFX filter chain from a list of effect names.

    Returns (video_filter_string, audio_filter_string) or (None, None) if no effects.
    Skips unknown effect names silently.
    """
    selected = []
    audio_parts = []

    for name in vfx_list:
        if name == "none" or name not in VIDEO_EFFECTS:
            continue
        effect = VIDEO_EFFECTS[name]
        if effect["filter"]:
            selected.append(effect)
        if effect.get("audio_filter"):
            audio_parts.append(effect["audio_filter"])

    if not selected:
        return None, None if not audio_parts else (None, ",".join(audio_parts))

    # Sort by category order
    selected.sort(key=lambda x: CATEGORY_ORDER.get(x["category"], 999))

    # Build filter string, templating in dimensions where needed
    filters = []
    for eff in selected:
        f = eff["filter"].format(width=width, height=height, fps=fps)
        filters.append(f)

    vf = ",".join(filters)
    af = ",".join(audio_parts) if audio_parts else None
    return vf, af


# ── Sound Effects ─────────────────────────────────────────────────────────────

SOUND_EFFECTS = {
    "none": {
        "description": "No sound effect",
        "file": None,
    },
    "few_moments_later": {
        "description": "SpongeBob 'A Few Moments Later' narrator",
        "file": "sfx/a-few-moments-later-sponge-bob-sfx-fun.mp3",
    },
    "again_again": {
        "description": "Excited 'Again! Again!' reaction",
        "file": "sfx/again-again.mp3",
    },
    "among_us_reveal": {
        "description": "Among Us role reveal sound",
        "file": "sfx/among-us-role-reveal-sound.mp3",
    },
    "anime_wow": {
        "description": "Anime wow reaction",
        "file": "sfx/anime-wow-sound-effect.mp3",
    },
    "another_one": {
        "description": "DJ Khaled 'Another One'",
        "file": "sfx/another-one_dPvHt2Z.mp3",
    },
    "atla_why": {
        "description": "Avatar 'Why?' dramatic moment",
        "file": "sfx/atla-why.mp3",
    },
    "agamotto": {
        "description": "Doctor Strange 'By the Eye of Agamotto' dramatic",
        "file": "sfx/by-the-eye-of-agamotto-doctor-strange-marvel.mp3",
    },
    "bye_bye_mewing": {
        "description": "Bye bye mewing meme sound",
        "file": "sfx/bye-bye-mewing_fMVssQz.mp3",
    },
    "lemons": {
        "description": "Caine 'When life gives you lemons' speech",
        "file": "sfx/caine-when-life-gives-you-lemons.mp3",
    },
    "clown_music": {
        "description": "Circus clown music for embarrassing moments",
        "file": "sfx/clown-circus-music.mp3",
    },
    "daddy_chill": {
        "description": "'Daddy chill' meme sound",
        "file": "sfx/daddyy-chill.mp3",
    },
    "deku_hero": {
        "description": "Deku 'World's Greatest Hero' inspirational",
        "file": "sfx/deku-worlds-greatest-hero.mp3",
    },
    "dexter_meme": {
        "description": "Dexter meme sound",
        "file": "sfx/dexter-meme.mp3",
    },
    "faaah": {
        "description": "Dramatic 'Faaah' reaction",
        "file": "sfx/faaah.mp3",
    },
    "gunshot": {
        "description": "Gunshot impact sound",
        "file": "sfx/gunshotjbudden.mp3",
    },
    "homelander_rage": {
        "description": "Homelander angry violin theme — intense/unhinged moment",
        "file": "sfx/homelander-going-crazy-angry-violin-theme-song.mp3",
    },
    "homelander_yummers": {
        "description": "Homelander 'Yummers' — satisfying moment",
        "file": "sfx/homelander-yummers.mp3",
    },
    "i_need_you": {
        "description": "'I need you' emotional plea",
        "file": "sfx/i-need-you-cecil_UfM8J59.mp3",
    },
    "knight_shining_armor": {
        "description": "'I was the knight in shining armor' dramatic",
        "file": "sfx/i-was-the-knight-in-shining-armor-in-your-movie.mp3",
    },
    "i_will_eliminate_you": {
        "description": "'I will eliminate you' threat",
        "file": "sfx/i-will-eliminate-you.mp3",
    },
    "im_better": {
        "description": "'I'm better' flex/boast",
        "file": "sfx/im-better_R4r4MzL.mp3",
    },
    "kinda_cringe": {
        "description": "Jax 'It's kinda cringe'",
        "file": "sfx/its-kinda-cringe-jax.mp3",
    },
    "jojos_golden_wind": {
        "description": "JoJo's Golden Wind dramatic theme",
        "file": "sfx/jojos-golden-wind.mp3",
    },
    "death_note": {
        "description": "Death Note dramatic moment theme",
        "file": "sfx/kyrie-death-note.mp3",
    },
    "leave_me_alone": {
        "description": "'Leave me alone!' frustrated scream",
        "file": "sfx/leave-me-alone-ahh.mp3",
    },
    "low_honor": {
        "description": "RDR2 low honor sound — dishonorable moment",
        "file": "sfx/low-honor-rdr-2.mp3",
    },
    "meow": {
        "description": "Cat meow sound",
        "file": "sfx/m-e-o-w.mp3",
    },
    "sad_cat": {
        "description": "Sad cat meow — sad/pathetic moment",
        "file": "sfx/miau-triste.mp3",
    },
    "movie_clip": {
        "description": "Short movie transition sting",
        "file": "sfx/movie_1.mp3",
    },
    "my_leg": {
        "description": "SpongeBob 'My leg!' scream",
        "file": "sfx/my-leg_2.mp3",
    },
    "cinematic_boom": {
        "description": "Cinematic boom/impact",
        "file": "sfx/my-movie-6_0RlWMvM.mp3",
    },
    "hello_there": {
        "description": "Obi-Wan 'Hello there!'",
        "file": "sfx/obi-wan_says_hello_thereyoutubetomp4.mp3",
    },
    "outro_song": {
        "description": "Outro/ending music",
        "file": "sfx/outro-song_oqu8zAg.mp3",
    },
    "prowler": {
        "description": "Prowler menacing bass sound — threat approaching",
        "file": "sfx/prowler-sound-effect_6bXErot.mp3",
    },
    "rizz": {
        "description": "Rizz sound effect — smooth/cool moment",
        "file": "sfx/rizz-sound-effect.mp3",
    },
    "roblox_death": {
        "description": "Roblox 'oof' death sound",
        "file": "sfx/roblox-death-sound_1.mp3",
    },
    "bass_drop": {
        "description": "Bass drop hit",
        "file": "sfx/sound_6.mp3",
    },
    "spongebob_fail": {
        "description": "SpongeBob fail sound — embarrassing fail",
        "file": "sfx/spongebob-fail.mp3",
    },
    "stand_ready": {
        "description": "'Stand ready for my arrival, worm' — domination",
        "file": "sfx/stand-ready-for-my-arrival-worm.mp3",
    },
    "za_warudo": {
        "description": "JoJo Star Platinum 'ZA WARUDO' bass boosted — time stop moment",
        "file": "sfx/star-platinum-za-warudo-bass-busted_ws2fMMQ.mp3",
    },
    "surprise": {
        "description": "'Surprise motherf-' reveal",
        "file": "sfx/surprise-mother-fer.mp3",
    },
    "taco_bell": {
        "description": "Taco Bell bong sound",
        "file": "sfx/taco-bell-bong-sfx.mp3",
    },
    "nemesis": {
        "description": "Nemesis dramatic theme",
        "file": "sfx/tf_nemesis.mp3",
    },
    "thats_rough": {
        "description": "Zuko 'That's rough, buddy' — sympathy",
        "file": "sfx/thats-rough-buddy.mp3",
    },
    "impact_hit": {
        "description": "Short impact hit sting",
        "file": "sfx/tmp_7901-951678082.mp3",
    },
    "tuco_get_out": {
        "description": "Tuco 'Get out!' — angry dismissal",
        "file": "sfx/tuco-get-out.mp3",
    },
    "you_are_an_idiot": {
        "description": "'You are an idiot' taunt",
        "file": "sfx/you-are-an-idiot.mp3",
    },
    "should_have_died": {
        "description": "'You should have died at birth' — brutal roast",
        "file": "sfx/you-should-have-died-at-birth_f90I620.mp3",
    },
    "yowai_mo": {
        "description": "Yowai mo — anime weakness callout",
        "file": "sfx/yowai-mo.mp3",
    },
}


def effects_for_prompt() -> str:
    """Format video effects list for the Gemini prompt."""
    lines = []
    for key, val in VIDEO_EFFECTS.items():
        if key != "none":
            lines.append(f"- {key}: {val['description']} [{val['category']}]")
    return "\n".join(lines)


def sfx_for_prompt() -> str:
    """Format sound effects list for the Gemini prompt."""
    lines = []
    for key, val in SOUND_EFFECTS.items():
        if val["file"] is not None:
            lines.append(f"- {key}: {val['description']}")
    return "\n".join(lines)
