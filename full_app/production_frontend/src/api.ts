export * from "./legacyApi";
import * as legacy from "./legacyApi";
import { baseCapabilities, demoCapabilities, extensionDefaults, normalizeKit, signalChips, validateVod, type Capabilities, type ExtensionOptions, type ShareKit } from "./features";
export type Preset = "landscape" | "vertical" | "square";
export interface Options extends Partial<ExtensionOptions> {
  max_duration?: number;
  analysis_instructions?: string;
  editing_instructions?: string;
  game: string;
  profile: string;
  mode: "nice" | "mean";
  style: string;
  provider: string;
  use_signals: boolean;
  captions: boolean;
  reactions: boolean;
  sam: boolean;
}
export interface ReviewClip {
  id: string;
  start: number;
  end: number;
  caption: string;
  score: number;
  reaction: string;
  keep: boolean;
  thumbnail?: string;
  why?: string[];
}
export interface Job {
  meta?: Record<string, unknown>;
  notes?: string[];
  seed?: number;
  id: string;
  status: string;
  duration: number;
  progress?: number;
  clips: ReviewClip[];
  candidates: ReviewClip[];
  interest: { time: number; score: number }[];
  source_url?: string;
  download_url?: string;
  error?: string;
  warnings?: string[];
  plan?: legacy.EditPlan;
  share_kit?: ShareKit;
  planningSettings?: Record<string, unknown>;
  planningStyle?: string;
  planningMode?: string;
}
export interface AgentStep {
  step: number;
  tool: string;
  args: Record<string, unknown>;
  rationale: string;
  diff: Record<string, unknown>;
}
export interface AgentResult { plan: legacy.EditPlan; plan_version: number; trace?: AgentStep[] }
export class ApiError extends Error {
  constructor(message: string, public code?: string, public status?: number) { super(message); }
}
export function clipsFromPlan(plan: legacy.EditPlan, previous: ReviewClip[]): ReviewClip[] {
  return plan.segments.map((s, i) => {
    const original = previous.find(c => c.id === String(s.clip_id ?? s.id))
      ?? previous.find(c => c.start < s.source_end && c.end > s.source_start);
    return { ...original, id: String(s.clip_id ?? s.id ?? original?.id ?? `segment-${i}`),
      start: s.source_start, end: s.source_end, caption: String(s.title ?? original?.caption ?? 'Edited moment'),
      score: original?.score ?? 0, reaction: original?.reaction ?? 'None', keep: true };
  });
}
function agentResult(raw: Wire): AgentResult {
  const plan = editPlan(raw.plan);
  if (!plan || !Number.isInteger(raw.plan_version)) throw new Error('Invalid Director plan response');
  return {plan, plan_version: raw.plan_version as number, trace: list(raw.trace) as AgentStep[]};
}
export type ApiMode = "jobs" | "mock" | "legacy";
type Wire = Record<string, unknown>;
const object = (value: unknown): Wire => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Wire : {};
const text = (value: unknown): string | undefined => typeof value === "string" ? value : undefined;
const list = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const number = (value: unknown): number => Number.isFinite(Number(value)) ? Number(value) : 0;
function editPlan(value: unknown): legacy.EditPlan | undefined {
  const plan = object(value);
  if (!Array.isArray(plan.segments)) return undefined;
  return {...plan, segments: plan.segments.map(value => {
    const segment = object(value);
    if (typeof segment.source_start !== "number" || typeof segment.source_end !== "number")
      throw new Error("Invalid plan segment timestamps");
    return {...segment, source_start: segment.source_start, source_end: segment.source_end};
  })};
}
const seconds = (v: unknown): number =>
  typeof v === "string" && v.includes(":")
    ? v.split(":").reduce((n, p) => n * 60 + Number(p), 0)
    : Number(v ?? 0);
export function normalizeClip(value: unknown, i: number): ReviewClip {
  const c = object(value);
  return {
    ...c,
    id: String(c.id ?? c.clip_id ?? i),
    start: seconds(c.start_seconds ?? c.start),
    end: seconds(c.end_seconds ?? c.end),
    caption: text(c.caption) ?? text(c.description) ?? "Untitled moment",
    score: c.score_scale === "raw_signal" ? (0.5 + Math.atan(number(c.score)) / Math.PI) * 100
      : number(c.score) * (c.score_scale === "percent" ? 1 : 100),
    reaction: text(c.suggested_reaction_label) ?? text(c.reaction_label) ?? text(c.reaction) ?? text(c.label) ?? "None",
    keep: c.keep !== false,
    thumbnail: text(c.thumbnail_url) ?? text(c.thumbnail),
    why: signalChips(c),
  };
}
export function normalizeJob(value: unknown): Job {
  const raw = object(value);
  const j = raw.job ? object(raw.job) : raw;
  return {
    meta: object(j.meta),
    notes: list(object(j.planner_plan).notes).filter((v): v is string => typeof v === "string"),
    id: String(j.id ?? j.job_id),
    seed: typeof j.seed === 'number' ? j.seed : undefined,
    status: text(j.status) ?? "uploaded",
    duration: number(j.duration ?? object(j.meta).duration),
    progress:
      typeof j.progress === "number"
        ? Math.max(0, Math.min(100, j.progress * 100))
        : undefined,
    clips: list(j.clips).map(normalizeClip),
    candidates: list(j.candidates).map((value, i) => normalizeClip({score_scale: "raw_signal", ...object(value)}, i)),
    interest: list(j.interest_curve ?? j.interest).map(value => ({time: number(object(value).time), score: number(object(value).score)})),
    source_url: text(j.source_url),
    download_url: text(j.download_url),
    error: typeof j.error === "string" ? j.error : text(object(j.error).message),
    warnings: list(j.warnings).filter((v): v is string => typeof v === "string"),
    plan: editPlan(j.plan ?? j.edit_plan),
    share_kit: normalizeKit(j.share_kit),
    planningMode: text(object(j.planning_settings).mode) ?? text(object(j.options).mode),
    planningSettings: object(j.planning_settings),
    planningStyle: text(object(j.planning_settings).style) ?? text(object(j.options).style),
  };
}
async function request(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<Wire> {
  const res = await fetch(path, {
    method,
    ...(body instanceof FormData
      ? { body }
      : body === undefined
        ? {}
        : {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
  });
  const data = object(await res.json().catch(() => ({})));
  if (!res.ok)
    throw new ApiError(
      text(object(data.error).message) ??
        text(data.error) ??
        text(data.message) ??
        `Request failed (${res.status})`,
      text(object(data.error).code) ?? text(data.code), res.status,
    );
  return data;
}
export const demoClips: ReviewClip[] = [
  {
    id: "clutch",
    start: 8,
    end: 17,
    caption: "One shot. Round saved.",
    score: 96,
    reaction: "Clutch",
    keep: true,
    why: ["Kill-feed", "Audio spike", "Gemini hype 9.6/10"],
  },
  {
    id: "whiff",
    start: 24,
    end: 31,
    caption: "The crosshair had other plans.",
    score: 82,
    reaction: "Bruh",
    keep: true,
    why: ["Laughter", "Chat spike", "Gemini hype 8.2/10"],
  },
  {
    id: "team",
    start: 42,
    end: 55,
    caption: "A clean sweep with the squad.",
    score: 91,
    reaction: "Hype",
    keep: true,
  },
];
export class EditorApi {
  private cached?: Job;
  private planningSettings = new Map<string, Record<string, unknown>>();
  private planningStyles = new Map<string, string>();
  private planningModes = new Map<string, string>();
  capabilities: Capabilities = baseCapabilities;
  constructor(public mode: ApiMode) {}
  async discover(): Promise<Capabilities> {
    if (this.mode === "mock") return (this.capabilities = demoCapabilities);
    if (this.mode === "legacy") return (this.capabilities = { ...baseCapabilities, options: [] });
    const info = await request("/api/info");
    const c = object(info.frontend_capabilities);
    return (this.capabilities = {
      options: [...baseCapabilities.options, ...(Array.isArray(c.options) ? c.options.filter((s: unknown) => typeof s === "string") : [])],
      team_upload: c.team_upload === true, url_import: c.url_import === true,
      music_upload: c.music_upload === true, chat_upload: c.chat_upload === true,
    });
  }
  private extended(options: Options): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const key of [...Object.keys(extensionDefaults), "game"])
      if (this.capabilities.options.includes(key) && options[key as keyof Options] !== undefined)
        result[key] = options[key as keyof Options];
    const aliases: Record<string, string> = {planner_v2: "planner", privacy_blur: "privacy", share_kit: "social"};
    for (const [ui, api] of Object.entries(aliases)) {
      if (ui in result) { result[api] = result[ui]; delete result[ui]; }
    }
    if ("game" in result) result.profiles = true;
    if ("music" in result) {
      if (this.capabilities.options.includes("music_mood") && ["chill", "energetic"].includes(String(result.music))) result.music_mood = result.music;
      result.music = result.music !== "off";
    }
    return result;
  }
  async createTeam(players: { file: File; name: string }[]): Promise<Job> {
    if (players.length < 2 || players.some(p => !p.name.trim()) || new Set(players.map(p => p.name.trim().toLowerCase())).size !== players.length)
      throw new Error("Choose at least two recordings with unique player names.");
    if (this.mode === "mock") return this.create(players[0].file);
    if (!this.capabilities.team_upload) throw new Error("Team upload is unavailable on this backend.");
    const form = new FormData();
    players.forEach(p => form.append("video", p.file));
    form.append("players", JSON.stringify(players.map(p => p.name.trim())));
    return (this.cached = normalizeJob(await request("/api/jobs", "POST", form)));
  }
  async importVod(url: string, ownsContent: boolean): Promise<Job> {
    const validated = validateVod(url);
    if (!ownsContent) throw new Error("Confirm that you own or have permission to use this VOD.");
    if (this.mode === "mock") return this.create(new File([], "demo-vod.mp4"));
    if (!this.capabilities.url_import) throw new Error("VOD import is unavailable on this backend.");
    return (this.cached = normalizeJob(await request("/api/jobs/import", "POST", { url: validated, owns_content: true })));
  }
  async uploadAsset(id: string, kind: "music" | "chat", file: File): Promise<string> {
    if (this.mode === "mock") return `demo-${kind}`;
    if (!this.capabilities[`${kind}_upload`]) throw new Error(`${kind} upload is unavailable on this backend.`);
    const form = new FormData(); form.append(kind, file);
    const result = await request(`/api/jobs/${encodeURIComponent(id)}/assets/${kind}`, "POST", form);
    if (typeof result.asset_id !== "string" || !result.asset_id) throw new Error("Upload did not return an asset ID.");
    return result.asset_id;
  }
  async create(file: File): Promise<Job> {
    if (this.mode === "mock")
      return (this.cached = {
        id: "demo",
        status: "uploaded",
        duration: 60,
        clips: [],
        candidates: [],
        interest: [],
      });
    const form = new FormData();
    form.append("video", file);
    const data = await request(
      this.mode === "legacy" ? "/api/upload" : "/api/jobs",
      "POST",
      form,
    );
    return (this.cached = normalizeJob(data));
  }
  async get(id: string): Promise<Job> {
    if (this.mode === "mock") return structuredClone(this.cached!);
    if (this.mode === "legacy")
      return { ...this.cached!, ...(await legacy.fetchStatus(id)), id };
    const job = normalizeJob(await request(`/api/jobs/${encodeURIComponent(id)}`));
    if (job.planningSettings) this.planningSettings.set(id, job.planningSettings);
    if (job.planningStyle) this.planningStyles.set(id, job.planningStyle);
    if (job.planningMode) this.planningModes.set(id, job.planningMode);
    return job;
  }
  async analyze(id: string, options: Options, preset: Preset = "landscape"): Promise<void> {
    if (this.mode === "mock") {
      this.cached = {
        ...this.cached!,
        status: "analyzed",
        progress: 100,
        clips: structuredClone(demoClips),
        candidates: structuredClone(demoClips),
        interest: Array.from({ length: 31 }, (_, i) => ({
          time: i * 2,
          score: 15 + Math.abs(Math.sin(i * 0.7)) * 75,
        })),
      };
      return;
    }
    if (this.mode === "legacy") {
      const data = await legacy.analyzeVideo({
        job_id: id,
        prompt: `${options.analysis_instructions ?? ""}\nGame: ${options.game}. Profile: ${options.profile}.`,
        splits: 1,
        attitude: options.mode,
      });
      this.cached = {
        ...this.cached!,
        status: "analyzed",
        clips: data.clips.map(normalizeClip),
      };
      return;
    }
    this.planningStyles.set(id, options.style);
    this.planningModes.set(id, options.mode);
    const { game, profile, mode, style, provider, use_signals, captions, reactions, sam } = options;
    await request(`/api/jobs/${encodeURIComponent(id)}/analyze`, "POST", {
      mode, style, provider, use_signals, captions, reactions, sam,
      ...this.extended(options),
      preset, max_duration: options.max_duration ?? (preset === "landscape" ? 60 : 30),
      editing_instructions: options.editing_instructions ?? "",
      prompt: `${options.analysis_instructions ?? ""}\nGame: ${game}. Profile: ${profile}.`,
    });
  }
  async save(id: string, clips: ReviewClip[]): Promise<void> {
    if (this.mode !== "jobs") {
      this.cached = { ...this.cached!, clips: structuredClone(clips) };
      return;
    }
    await request(`/api/jobs/${encodeURIComponent(id)}/clips`, "PATCH", {
      clips: clips.map((c, order) => ({
        ...c,
        start_seconds: c.start,
        end_seconds: c.end,
        score: c.score / 100,
        score_scale: "unit",
        order,
      })),
    });
  }
  async reroll(id: string, options: Options, preset: Preset, previousSeed = 0): Promise<number> {
    const random = crypto.getRandomValues(new Uint32Array(1))[0];
    const seed = random === previousSeed ? (random + 1) >>> 0 : random;
    if (this.mode !== 'jobs') throw new Error('Reroll requires the jobs API.');
    await request(`/api/jobs/${encodeURIComponent(id)}/plan`, 'POST', {
      chaos: options.chaos ?? (options.mode === 'mean' ? .6 : .35), seed, planner: true, editor_agent: false,
      preset, mode: options.mode, style: options.style,
      max_duration: options.max_duration ?? (preset === "landscape" ? 60 : 30),
      editing_instructions: options.editing_instructions ?? "",
    });
    return seed;
  }
  async render(
    id: string,
    preset: Preset,
    options: Options,
    reviewed?: ReviewClip[],
    plan?: legacy.EditPlan,
    authoritative = false,
  ): Promise<void> {
    if (this.mode === "mock") {
      this.cached = { ...this.cached!, status: "done", progress: 100,
        share_kit: options.share_kit ? {
          titles: ["One shot. Round saved.", "The squad came to play", "Our best moments"],
          description: "Demo posting copy. A clutch, a whiff, and a team win. #gameplay",
          chapters: "00:00 Round saved\n00:09 The crosshair had other plans\n00:16 Team win",
          thumbnails: [{ url: "/demo-cover.svg", label: "Demo landscape cover" }], downloads: [],
        } : undefined,
      };
      return;
    }
    if (this.mode === "legacy") {
      const plan = await legacy.planEdit({
        job_id: id,
        max_duration: options.max_duration ?? 60,
        edit_style: options.style,
        prompt:
          (options.editing_instructions ?? "") + "\nUse these reviewed ranges in this exact order: " +
          JSON.stringify(this.cached!.clips.filter((c) => c.keep)),
      });
      // Preserve effects where possible while enforcing the reviewed ranges and ordering.
      plan.edit_plan.segments = this.cached!.clips.filter((c) => c.keep).map(
        (c, i) => ({
          ...plan.edit_plan.segments[i],
          source_start: c.start,
          source_end: c.end,
        }),
      );
      const result = await legacy.renderVideo({
        job_id: id,
        edit_plan: plan.edit_plan,
        generate_thumbnails: false,
      });
      this.cached = {
        ...this.cached!,
        status: "done",
        download_url: result.download_url,
      };
      return;
    }
    // Changed automatic cards/joins need a fresh planner budget. Director plans
    // remain authoritative; ordinary reviewed clips were saved by the review flow.
    const prior = this.planningSettings.get(id);
    const refreshExperience =
      (prior !== undefined && (prior.max_duration !== (options.max_duration ?? (preset === "landscape" ? 60 : 30)) ||
        (prior.editing_instructions ?? "") !== (options.editing_instructions ?? "") ||
        Boolean(prior.plan_refinement) !== Boolean(options.plan_refinement))) ||
      (options.chaos !== undefined && options.chaos !== (plan?.chaos ?? .35)) ||
      (options.seed !== undefined && options.seed !== (plan?.seed ?? 0)) ||
      (options.cards !== undefined && (Boolean(plan?.intro) !== options.cards || Boolean(plan?.outro) !== options.cards)) ||
      (options.transitions !== undefined && (options.transitions ? plan?.transition !== "varied" : plan?.transition === "varied"));
    await request(`/api/jobs/${encodeURIComponent(id)}/render`, "POST", {
      preset, mode: options.mode, style: options.style,
      max_duration: options.max_duration ?? (preset === "landscape" ? 60 : 30),
      editing_instructions: options.editing_instructions ?? "",
      captions: options.captions, reactions: options.reactions, sam: options.sam,
      ...this.extended(options),
      ...(reviewed && (authoritative || !refreshExperience && (!this.planningModes.has(id) || this.planningModes.get(id) === options.mode) && (!this.planningStyles.has(id) || this.planningStyles.get(id) === options.style))
        ? {
            edit_plan: {
              ...plan,
              segments: reviewed
                .filter((c) => c.keep)
                .map((c, index) => {
                  const original = (authoritative ? plan?.segments[index] : undefined) ?? plan?.segments.find(
                    (s) => s.source_start < c.end && s.source_end > c.start,
                  );
                  return {
                    ...original,
                    source_start: c.start,
                    source_end: c.end,
                    title: c.caption,
                  };
                }),
            },
          }
        : {}),
    });
  }
  async plan(id: string, options: Options, preset: Preset): Promise<void> {
    if (this.mode !== "jobs") return;
    await request(`/api/jobs/${encodeURIComponent(id)}/plan`, "POST", {
      ...this.extended(options), preset, mode: options.mode, style: options.style,
      max_duration: options.max_duration ?? (preset === "landscape" ? 60 : 30),
      editing_instructions: options.editing_instructions ?? "",
    });
  }
  async importPlan(id: string, value: unknown, maxDuration: number): Promise<Job> {
    if (this.mode !== "jobs") throw new Error("Plan import requires the jobs API.");
    return normalizeJob(await request(`/api/jobs/${encodeURIComponent(id)}/plan`, "PUT", {edit_plan: value, max_duration: maxDuration}));
  }
  async log(id: string): Promise<string> {
    if (this.mode === "mock") return "Demo workspace: no provider calls.\nAnalysis and planning simulated.";
    const response = await fetch(`/api/log/${encodeURIComponent(id)}`);
    if (!response.ok) throw new Error("Could not load job log");
    return response.text();
  }
  async agent(id: string, instruction: string): Promise<AgentResult> {
    if (this.mode !== 'jobs') throw new Error('Director requires the jobs backend.');
    return agentResult(await request(`/api/jobs/${encodeURIComponent(id)}/agent`, 'POST', {instruction}));
  }
  async undoAgent(id: string): Promise<AgentResult> {
    return agentResult(await request(`/api/jobs/${encodeURIComponent(id)}/agent/undo`, 'POST', {}));
  }
  download(id: string) {
    return this.mode === "legacy"
      ? legacy.getDownloadUrl(id)
      : `/api/jobs/${encodeURIComponent(id)}/download`;
  }
  watch(
    id: string,
    update: (job: Job) => void,
    connection: (state: string) => void,
    fail: (message: string) => void,
    agentStep?: (step: AgentStep) => void,
  ): () => void {
    let stopped = false,
      timer: ReturnType<typeof setTimeout> | undefined,
      stream: EventSource | undefined,
      busy = false;
    const refresh = async () => {
      if (busy || stopped) return;
      busy = true;
      try {
        const job = await this.get(id);
        if (!stopped) update(job);
      } catch (e) {
        if (!stopped) fail((e as Error).message);
      } finally {
        busy = false;
      }
    };
    const poll = () => {
      if (stopped) return;
      void refresh().finally(() => {
        if (!stopped) timer = setTimeout(poll, 1500);
      });
    };
    const fallback = () => {
      stream?.close();
      if (!timer && !stopped) {
        connection(this.mode === "mock" ? "Demo" : "Polling");
        poll();
      }
    };
    if (this.mode === "jobs" && typeof EventSource !== "undefined") {
      connection("Connecting");
      try {
        stream = new EventSource(`/api/jobs/${encodeURIComponent(id)}/events`);
        stream.onopen = () => {
          connection("Live");
          void refresh();
        };
        // Events can be partial stage updates: fetch the authoritative snapshot.
        stream.addEventListener('agent_step', (event) => {
          if (stopped) return;
          try {
            const step = JSON.parse((event as MessageEvent).data) as AgentStep;
            if (typeof step.step === 'number' && typeof step.tool === 'string') agentStep?.(step);
          } catch { /* Ignore malformed events; the final response remains authoritative. */ }
        });
        stream.onmessage = () => void refresh();
        for (const name of ["progress", "status", "job", "complete", "done"])
          stream.addEventListener(name, () => void refresh());
        stream.onerror = fallback;
        // A watchdog also covers servers that use custom event names or stall silently.
        const watchdog = () => {
          if (stopped) return;
          void refresh();
          timer = setTimeout(watchdog, 5000);
        };
        timer = setTimeout(watchdog, 5000);
        stream.onerror = () => {
          clearTimeout(timer);
          timer = undefined;
          fallback();
        };
      } catch {
        fallback();
      }
    } else fallback();
    return () => {
      stopped = true;
      clearTimeout(timer);
      stream?.close();
    };
  }
}
