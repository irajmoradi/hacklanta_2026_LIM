export const extensionDefaults = {
  audio_ai: false, planner_v2: false, window_scoring: false, sam_reframe: false,
  narration: false, narration_persona: "hype_caster", privacy_blur: true,
  keep_my_name: "", music: "off", music_asset_id: "", chat: false,
  chat_asset_id: "", chat_offset: 0, twitch_vod_id: "", fx_intensity: 0.5,
  share_kit: false, team_mode: "best",
};
export type ExtensionOptions = typeof extensionDefaults;
export interface Capabilities {
  options: string[];
  team_upload: boolean;
  url_import: boolean;
  music_upload: boolean;
  chat_upload: boolean;
}
export const baseCapabilities: Capabilities = {
  options: ["window_scoring", "sam_reframe"], team_upload: false,
  url_import: false, music_upload: false, chat_upload: false,
};
export const demoCapabilities: Capabilities = {
  options: [...Object.keys(extensionDefaults), "game"], team_upload: true,
  url_import: true, music_upload: true, chat_upload: true,
};
export interface ShareKit {
  titles: string[];
  description: string;
  chapters: string;
  thumbnails: { url: string; label: string }[];
  downloads: { url: string; label: string }[];
}
// Only server-served relative paths and web URLs may become links or image sources.
export function mediaUrl(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  if (/^\/(?!\/)/.test(value) && !value.includes("\\")) return value;
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : undefined; }
  catch { return undefined; }
}
export function normalizeKit(raw: any): ShareKit | undefined {
  if (!raw || typeof raw !== "object") return undefined;
  const links = (items: any) => Array.isArray(items) ? items.flatMap((item: any) => {
    const url = mediaUrl(item?.url);
    return url ? [{ url, label: String(item.label ?? "Download") }] : [];
  }) : [];
  return {
    titles: Array.isArray(raw.titles) ? raw.titles.filter((t: unknown) => typeof t === "string") : [],
    description: typeof raw.description === "string" ? raw.description : "",
    chapters: typeof raw.chapters === "string" ? raw.chapters : "",
    thumbnails: links(raw.thumbnails), downloads: links(raw.downloads),
  };
}
export function signalChips(raw: Record<string, any>): string[] {
  const signals = raw.signals ?? {};
  const groups: [string, string[]][] = [
    ["Kill-feed", ["kill_feed", "killfeed", "ocr", "kills"]],
    ["Audio spike", ["audio_spike", "audio", "audio_rms", "audio_peak"]],
    ["Laughter", ["laughter", "laugh"]],
    ["Chat spike", ["chat_spike", "chat_emote_spike", "chat_clip_it"]],
  ];
  const chips = groups.filter(([, keys]) => keys.some(k =>
    signals[k] === true || (typeof signals[k] === "number" && Number.isFinite(signals[k]) && signals[k] > 0),
  )).map(([label]) => label);
  const hype = raw.hype ?? raw.gemini_hype ?? signals.gemini_hype;
  if (typeof hype === "number" && Number.isFinite(hype)) chips.push(`Gemini hype ${hype}/10`);
  return chips;
}
export function validateVod(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new Error("Enter a valid HTTPS Twitch or YouTube VOD URL."); }
  if (url.protocol !== "https:" || url.username || url.password || url.port ||
      !["twitch.tv", "www.twitch.tv", "clips.twitch.tv", "youtube.com", "www.youtube.com", "youtu.be"].includes(url.hostname))
    throw new Error("Use an HTTPS Twitch or YouTube VOD URL.");
  return url.href;
}
