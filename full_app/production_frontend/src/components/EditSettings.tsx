import type { Options, Preset } from "../api";
import { extensionDefaults, type Capabilities } from "../features";

export function EditSettings({ options, change, capabilities, legacy, preset, setPreset, uploadAsset, hasJob }: {
  options: Options; change: <K extends keyof Options>(key: K, value: Options[K]) => void;
  capabilities: Capabilities; legacy: boolean; preset: Preset; setPreset: (p: Preset) => void;
  uploadAsset: (kind: "music" | "chat", file: File) => void; hasJob: boolean;
}) {
  const o = { ...extensionDefaults, ...options };
  const supports = (key: string) => !legacy && capabilities.options.includes(key);
  const toggles = [
    ["transitions", "Varied transitions", "Join clips with short zoom, whip, flash and glitch transitions."],
    ["cards", "Intro and outro", "Frame the montage with short title cards."],
    ["beat_sync", "Music beat sync", "Snap cuts near the music beat."],
    ["use_signals", "Gameplay signals", "Find action using HUD events, motion and audio."],
    ["audio_ai", "Audio AI", "Detect speech, shouting and laughter."],
    ["window_scoring", "Gemini window scoring", "Score candidate moments with video understanding."],
    ["planner_v2", "Story planner v2", "Build an opening, escalation and payoff."],
    ["captions", "Captions", "Add speech captions when transcription is available."],
    ["reactions", "Meme reactions", "Place reactions around key moments."],
    ["sam", "SAM spotlight", "Highlight the action with a subject mask."],
    ["sam_reframe", "Subject-aware vertical crop", "Follow the subject in vertical exports."],
    ["privacy_blur", "Privacy blur", "Blur kill feed, chat and party HUD regions in the export. Review the result."],
    ["narration", "AI narration", "Add cached speech or an offline computer-voice caster when available."],
    ["chat", "Twitch chat signal", "Use replay activity to find crowd favorites."],
    ["gemini_image", "AI thumbnails", "Generate two covers for your share kit (uses image calls)."],
    ["plan_refinement", "Gemini plan refinement", "Refine captions and effects using editing instructions (uses a model call)."],
    ["share_kit", "Share kit", "Prepare covers and posting copy after rendering."],
  ] as const;
  return <details className="edit-settings" open>
    <summary>Edit settings</summary>
    <label>Chaos {Math.round(o.chaos * 100)}%<input aria-label="Chaos" type="range" min="0" max="100"
      disabled={!supports('chaos')} value={Math.round(o.chaos * 100)}
      onChange={e => change('chaos', Number(e.target.value) / 100)} /></label>
    <label>Reaction size<select disabled={!supports('reaction_size')} value={o.reaction_size}
      onChange={e => change('reaction_size', e.target.value)}>
      <option value="small">Small</option><option value="medium">Medium</option><option value="large">Large</option>
    </select></label>
    <label><input type="checkbox" disabled={!supports('clean')} checked={o.clean}
      onChange={e => change('clean', e.target.checked)} />Clean reactions (exclude explicit clips)</label>
    <button type="button" disabled={!supports("full_experience")} onClick={() => {
      change("full_experience", true);
      for (const key of ["planner_v2", "audio_ai", "captions", "reactions", "sam", "sam_reframe", "beat_sync", "transitions", "cards", "narration", "share_kit", "gemini_image", "window_scoring", "use_signals"] as const) change(key, true);
      change("privacy_blur", false); change("music", "energetic");
    }}>Full experience</button>
    <label>Game<select value={o.game} onChange={e => change("game", e.target.value)}>
      <option value="auto">Auto-detect</option><option value="generic">Generic game</option>
      <option value="valorant">Valorant</option><option value="overwatch2">Overwatch 2</option>
      <option value="deadlock">Deadlock</option><option value="league_of_legends">League of Legends</option>
    </select></label>
    <label>Profile<select value={o.profile} onChange={e => change("profile", e.target.value)}>
      <option value="balanced">Balanced moments</option><option value="competitive">Competitive plays</option><option value="comedy">Comedy & chaos</option>
    </select></label>
    <label>Mode<select value={o.mode} onChange={e => change("mode", e.target.value as Options["mode"])}>
      <option value="nice">Nice / hype</option><option value="mean">Mean / roast</option>
    </select></label>
    <label>Style<select value={o.style} onChange={e => change("style", e.target.value)}>
      <option value="hype_montage">Hype montage</option><option value="clean_edit">Clean edit</option><option value="meme_edit">Meme edit</option><option value="cinematic">Cinematic</option>
    </select></label>
    <label>Canvas preset<select value={preset} disabled={legacy} onChange={e => setPreset(e.target.value as Preset)}>
      <option value="landscape">Landscape - 16:9</option><option value="vertical">Vertical - 9:16</option><option value="square">Square - 1:1</option>
    </select></label>
    <label>Max duration (seconds)<input type="number" min="10" max="600" step="1"
      value={o.max_duration ?? (preset === "landscape" ? 60 : 30)} onChange={e => change("max_duration", Number(e.target.value))} /></label>
    <label>Analysis instructions<textarea maxLength={8000} value={o.analysis_instructions ?? ""}
      placeholder="Which moments should we look for?" onChange={e => change("analysis_instructions", e.target.value)} /></label>
    <label>Editing instructions<textarea maxLength={8000} value={o.editing_instructions ?? ""}
      placeholder="How should the montage feel?" onChange={e => change("editing_instructions", e.target.value)} /></label>
    <p className="hint">Story planner: instructions go to Gemini refinement when enabled; otherwise the Director edits the draft. Both use the job call budget.</p>
    <label>Provider<select disabled={legacy} value={o.provider} onChange={e => change("provider", e.target.value)}>
      <option value="gemini">Gemini</option><option value="local">Local VLM</option>
    </select></label>
    <div className="feature-toggles">{toggles.map(([key, label, hint]) => {
      const available = ["use_signals", "captions", "reactions", "sam"].includes(key) ? !legacy : supports(key);
      return <label key={key} className={!available ? "unavailable" : ""}>
        <span><input type="checkbox" checked={available && Boolean(o[key])} disabled={!available}
          onChange={e => change(key, e.target.checked)} />{label}</span>
        <small>{available ? hint : "Unavailable on this backend"}</small>
      </label>;
    })}</div>
    <label>Keep my name<input maxLength={80} disabled={!supports("keep_my_name") || !o.privacy_blur}
      value={o.keep_my_name} placeholder="Your exact in-game name" onChange={e => change("keep_my_name", e.target.value)} /></label>
    <label>Narration persona<select disabled={!supports("narration_persona") || !o.narration}
      value={o.narration_persona} onChange={e => change("narration_persona", e.target.value)}>
      <option value="hype_caster">Hype caster</option><option value="deadpan_roast">Deadpan roast</option><option value="nature_documentary">Nature documentary</option>
    </select></label>
    <label>Music bed<select disabled={!supports("music")} value={o.music} onChange={e => change("music", e.target.value)}>
      <option value="off">Gameplay audio only</option><option value="energetic">Original energetic bed</option><option value="chill">Original chill bed</option>
      <option value="upload" disabled={!capabilities.music_upload}>Upload my own track</option>
    </select></label>
    {o.music === "upload" && <label>Upload music<input type="file" accept="audio/*,.wav,.mp3,.m4a,.ogg,.flac"
      disabled={!hasJob || !capabilities.music_upload} onChange={e => { if (e.target.files?.[0]) uploadAsset("music", e.target.files[0]); e.target.value = ""; }} />
      <small>{o.music_asset_id ? "Music attached" : "Create a job first, then upload a track you own or may use."}</small></label>}
    <label>FX intensity: {Math.round(o.fx_intensity * 100)}%<input aria-label="FX intensity" type="range" min="0" max="1" step="0.05"
      disabled={!supports("fx_intensity")} value={o.fx_intensity} onChange={e => change("fx_intensity", Number(e.target.value))} />
      <small>From subtle accents to frequent montage effects.</small></label>
    {o.chat && supports("chat") && <div className="subsettings">
      <label>Twitch VOD ID<input inputMode="numeric" value={o.twitch_vod_id} onChange={e => change("twitch_vod_id", e.target.value.replace(/\D/g, ""))} /></label>
      <label>Or upload chat replay<input type="file" accept=".json,.jsonl" disabled={!hasJob || !capabilities.chat_upload}
        onChange={e => { if (e.target.files?.[0]) uploadAsset("chat", e.target.files[0]); e.target.value = ""; }} />
        <small>{o.chat_asset_id ? "Chat replay attached" : "Create a job before attaching replay JSON."}</small></label>
      <label>Chat offset (seconds)<input type="number" value={o.chat_offset} onChange={e => change("chat_offset", Number(e.target.value))} /></label>
    </div>}
  </details>;
}
