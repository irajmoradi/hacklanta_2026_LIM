export * from "./legacyApi";
import * as legacy from "./legacyApi";
export type Preset = "landscape" | "vertical" | "square";
export interface Options {
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
}
export interface Job {
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
}
export type ApiMode = "jobs" | "mock" | "legacy";
type Wire = Record<string, any>;
const seconds = (v: unknown): number =>
  typeof v === "string" && v.includes(":")
    ? v.split(":").reduce((n, p) => n * 60 + Number(p), 0)
    : Number(v ?? 0);
export function normalizeClip(c: Wire, i: number): ReviewClip {
  return {
    ...c,
    id: String(c.id ?? c.clip_id ?? i),
    start: seconds(c.start_seconds ?? c.start),
    end: seconds(c.end_seconds ?? c.end),
    caption: c.caption ?? c.description ?? "Untitled moment",
    score: Number(c.score ?? 0),
    reaction: c.reaction_label ?? c.reaction ?? "None",
    keep: c.keep !== false,
    thumbnail: c.thumbnail_url ?? c.thumbnail,
  };
}
export function normalizeJob(raw: Wire): Job {
  const j = raw.job ?? raw;
  return {
    id: String(j.id ?? j.job_id),
    status: j.status ?? "uploaded",
    duration: Number(j.duration ?? j.meta?.duration ?? 0),
    progress: typeof j.progress === "number" ? j.progress : undefined,
    clips: (j.clips ?? []).map(normalizeClip),
    candidates: (j.candidates ?? []).map(normalizeClip),
    interest: j.interest_curve ?? j.interest ?? [],
    source_url: j.source_url,
    download_url: j.download_url,
    error: typeof j.error === "string" ? j.error : j.error?.message,
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
  const data = await res.json().catch(() => ({}));
  if (!res.ok)
    throw new Error(
      data.error?.message ??
        data.error ??
        data.message ??
        `Request failed (${res.status})`,
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
  },
  {
    id: "whiff",
    start: 24,
    end: 31,
    caption: "The crosshair had other plans.",
    score: 82,
    reaction: "Bruh",
    keep: true,
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
  constructor(public mode: ApiMode) {}
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
    return normalizeJob(await request(`/api/jobs/${encodeURIComponent(id)}`));
  }
  async analyze(id: string, options: Options): Promise<void> {
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
        prompt: `Game: ${options.game}. Profile: ${options.profile}.`,
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
    await request(
      `/api/jobs/${encodeURIComponent(id)}/analyze`,
      "POST",
      options,
    );
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
        order,
      })),
    });
  }
  async render(id: string, preset: Preset, options: Options): Promise<void> {
    if (this.mode === "mock") {
      this.cached = { ...this.cached!, status: "done", progress: 100 };
      return;
    }
    if (this.mode === "legacy") {
      const plan = await legacy.planEdit({
        job_id: id,
        max_duration: 180,
        edit_style: options.style,
        prompt:
          "Use these reviewed ranges in this exact order: " +
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
    await request(`/api/jobs/${encodeURIComponent(id)}/render`, "POST", {
      preset,
    });
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
