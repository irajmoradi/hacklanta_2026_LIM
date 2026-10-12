import { afterEach, describe, expect, it, vi } from "vitest";
import { EditorApi, demoClips, normalizeJob, type Options } from "./api";
const options: Options = {
  game: "auto",
  profile: "balanced",
  mode: "nice",
  style: "clean_edit",
  provider: "gemini",
  use_signals: true,
  captions: false,
  reactions: false,
  sam: false,
};
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});
it('rerolls locally with a distinct seed and forwards chaos without requesting analysis', async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({})});
  vi.stubGlobal('fetch', fetcher);
  vi.stubGlobal('crypto', {getRandomValues: (values: Uint32Array) => {values[0] = 42; return values;}});
  const api = new EditorApi('jobs');
  expect(await api.reroll('one', {...options, chaos: .8}, 'vertical', 42)).toBe(43);
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe('/api/jobs/one/plan');
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toMatchObject({seed: 43, chaos: .8, planner: true});
  expect(normalizeJob({id: 'one', seed: 43}).seed).toBe(43);
});
describe("jobs API", () => {
  it("normalizes legacy timestamps and wrapped jobs", () => {
    const j = normalizeJob({
      job: {
        job_id: "one",
        meta: { duration: 80 },
        clips: [{ start: "01:02", end_seconds: 70, description: "Play" }],
      },
    });
    expect(j.id).toBe("one");
    expect(j.duration).toBe(80);
    expect(j.clips[0]).toMatchObject({
      start: 62,
      end: 70,
      caption: "Play",
      keep: true,
    });
  });
  it("sends options, reviewed ordering and preset to jobs endpoints", async () => {
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "abc", meta: { duration: 60 } }),
    });
    vi.stubGlobal("fetch", fetcher);
    const api = new EditorApi("jobs");
    await api.create(new File(["x"], "video.mp4"));
    expect(fetcher.mock.calls[0][0]).toBe("/api/jobs");
    expect(fetcher.mock.calls[0][1].body.get("video").name).toBe("video.mp4");
    await api.analyze("abc", options);
    const { game, profile, ...flags } = options;
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({
      ...flags,
      prompt: `Game: ${game}. Profile: ${profile}.`,
    });
    await api.save("abc", [demoClips[2], { ...demoClips[0], keep: false }]);
    expect(fetcher.mock.calls[2][1].method).toBe("PATCH");
    expect(JSON.parse(fetcher.mock.calls[2][1].body).clips[1]).toMatchObject({
      keep: false,
      order: 1,
      start_seconds: 8,
    });
    await api.render("abc", "vertical", options);
    expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual({
      preset: "vertical", mode: "nice", style: "clean_edit",
      captions: false, reactions: false, sam: false,
    });
    await api.render(
      "abc",
      "square",
      options,
      [demoClips[2], { ...demoClips[0], keep: false }, demoClips[1]],
      { segments: [{ source_start: 24, source_end: 31, speed: 0.5 }] },
    );
    expect(
      JSON.parse(fetcher.mock.calls[4][1].body).edit_plan.segments,
    ).toEqual([
      { source_start: 42, source_end: 55, title: demoClips[2].caption },
      {
        source_start: 24,
        source_end: 31,
        title: demoClips[1].caption,
        speed: 0.5,
      },
    ]);
    expect(
      normalizeJob({
        id: "abc",
        progress: 0.5,
        warnings: ["Signals unavailable"],
      }),
    ).toMatchObject({ progress: 50, warnings: ["Signals unavailable"] });
  });
  it("surfaces structured server errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ error: { message: "Provider unavailable" } }),
      }),
    );
    await expect(new EditorApi("jobs").get("id")).rejects.toThrow(
      "Provider unavailable",
    );
  });
  it("falls back from SSE to polling and stops after cleanup", async () => {
    vi.useFakeTimers();
    let stream: any;
    class Events {
      onerror?: () => void;
      onopen?: () => void;
      onmessage?: () => void;
      close = vi.fn();
      addEventListener = vi.fn();
      constructor() {
        stream = this;
      }
    }
    vi.stubGlobal("EventSource", Events);
    const fetcher = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "id", status: "analyzed", clips: demoClips }),
    });
    vi.stubGlobal("fetch", fetcher);
    const update = vi.fn(),
      connection = vi.fn();
    const stop = new EditorApi("jobs").watch("id", update, connection, vi.fn());
    stream.onopen();
    await vi.advanceTimersByTimeAsync(0);
    expect(connection).toHaveBeenCalledWith("Live");
    expect(update).toHaveBeenCalled();
    stream.onerror();
    await vi.advanceTimersByTimeAsync(1600);
    expect(connection).toHaveBeenCalledWith("Polling");
    expect(fetcher.mock.calls.length).toBeGreaterThan(1);
    stop();
    const count = fetcher.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(fetcher).toHaveBeenCalledTimes(count);
    expect(stream.close).toHaveBeenCalled();
  });
  it("runs the fixture lifecycle without any network or paid calls", async () => {
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);
    const api = new EditorApi("mock");
    const j = await api.create(new File(["x"], "demo.mp4"));
    await api.analyze(j.id, options);
    expect((await api.get(j.id)).clips).toHaveLength(3);
    await api.save(j.id, [{ ...demoClips[0], start: 10 }]);
    await api.render(j.id, "square", options);
    expect(await api.get(j.id)).toMatchObject({
      status: "done",
      clips: [{ start: 10 }],
    });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
it("legacy adapter plans and renders only the reviewed ranges in reviewed order", async () => {
  const requests: { path: string; body: any }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const body =
        typeof init?.body === "string" ? JSON.parse(init.body) : init?.body;
      requests.push({ path, body });
      const data =
        path === "/api/upload"
          ? { job_id: "old", meta: { duration: 60 } }
          : path === "/api/analyze"
            ? { clips: demoClips }
            : path === "/api/plan"
              ? {
                  edit_plan: {
                    segments: [{ source_start: 0, source_end: 60, speed: 1 }],
                  },
                }
              : path === "/api/render"
                ? { download_url: "/api/download/old" }
                : { status: "done" };
      return { ok: true, json: async () => data };
    }),
  );
  const api = new EditorApi("legacy");
  await api.create(new File(["x"], "legacy.mp4"));
  await api.analyze("old", options);
  await api.save("old", [
    demoClips[2],
    { ...demoClips[0], keep: false },
    { ...demoClips[1], start: 25 },
  ]);
  await api.render("old", "landscape", options);
  const render = requests.find((r) => r.path === "/api/render")!;
  expect(render.body.generate_thumbnails).toBe(false);
  expect(render.body.edit_plan.segments).toEqual([
    { source_start: 42, source_end: 55, speed: 1 },
    { source_start: 25, source_end: 31 },
  ]);
  expect((await api.get("old")).download_url).toBe("/api/download/old");
});

it("replans changed styles and sends current render flags", async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({})});
  vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs");
  await api.analyze("abc", options);
  await api.render("abc", "square", {...options, style: "meme_edit", captions: true, reactions: true, sam: true}, demoClips,
    {segments: [{source_start: 8, source_end: 17, video_effects: ["vignette"]}]});
  const body = JSON.parse(fetcher.mock.calls[1][1].body);
  expect(body).toMatchObject({style: "meme_edit", captions: true, reactions: true, sam: true});
  expect(body.edit_plan).toBeUndefined();
});
it("preserves explicit v2 settings and maps editable text to titles", async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({})});
  vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs");
  await api.render("abc", "square", {...options, captions: true}, [demoClips[0]],
    {render_version: 2, fps: 24, transition: "flash", music: {path: "licensed.wav"}, segments: []});
  expect(JSON.parse(fetcher.mock.calls[0][1].body).edit_plan).toMatchObject({render_version: 2, fps: 24,
    transition: "flash", music: {path: "licensed.wav"}, segments: [{title: demoClips[0].caption}]});
});
it("normalizes unit scores and actual fusion reaction fields", () => {
  expect(normalizeJob({id: "a", clips: [{score: .8, suggested_reaction_label: "clutch"}]}).clips[0])
    .toMatchObject({score: 80, reaction: "clutch"});
});

it("saves unit scores so review round trips cannot multiply scores", async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({})});
  vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs");
  const wire = {id: "a", clips: [{id: "1", start_seconds: 0, end_seconds: 1, score: .8, score_scale: "unit"}]};
  const job = normalizeJob(wire);
  await api.save("a", job.clips);
  const saved = JSON.parse(fetcher.mock.calls[0][1].body);
  expect(saved.clips[0]).toMatchObject({score: .8, score_scale: "unit"});
  expect(normalizeJob({id: "a", clips: saved.clips}).clips[0].score).toBe(80);
  const candidates = normalizeJob({id: "a", candidates: [{score: 2}, {score: 8}]}).candidates;
  expect(candidates[1].score).toBeGreaterThan(candidates[0].score);
  expect(candidates[1].score).toBeLessThan(100);
});


it("translates discovered backend controls and normalizes real review payloads", async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({frontend_capabilities: {
    options: ["planner_v2", "privacy_blur", "share_kit", "game", "music"], team_upload: true,
  }})});
  vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs");
  await api.discover();
  await api.analyze("one", {...options, planner_v2: true, privacy_blur: true, share_kit: true, music: "off"});
  const body = JSON.parse(fetcher.mock.calls[1][1].body);
  expect(body).toMatchObject({planner: true, privacy: true, social: true, profiles: true, game: "auto", music: false});
  expect(body).not.toHaveProperty("planner_v2");
  const job = normalizeJob({id: "one", interest_curve: [{time: 0, score: 0}, {time: 1, score: 100}],
    share_kit: {titles: ["Play"], description: "Gameplay", chapters: "00:00 Play", thumbnails: [{url: "/api/cover", label: "cover"}], downloads: [{url: "/api/video", label: "video"}]}});
  expect(job.interest[1].score).toBe(100);
  expect(job.share_kit?.downloads).toHaveLength(1);
});


it("does not send a stale reviewed plan when mode changes", async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({id: "one"})});
  vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs");
  await api.analyze("one", options);
  await api.render("one", "landscape", {...options, mode: "mean"}, demoClips, {segments: []});
  const body = JSON.parse(fetcher.mock.calls[1][1].body);
  expect(body.mode).toBe("mean");
  expect(body).not.toHaveProperty("edit_plan");
});


it("replans when full experience is selected after analysis but preserves director plans", async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({})});
  vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs");
  api.capabilities.options = ["full_experience", "cards", "transitions", "planner_v2"];
  const full = {...options, full_experience: true, cards: true, transitions: true, planner_v2: true};
  const oldPlan = {render_version: 2, transition: "cut", segments: []};
  await api.render("one", "vertical", full, demoClips, oldPlan);
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).not.toHaveProperty("edit_plan");
  await api.render("one", "vertical", full, demoClips, oldPlan, true);
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toHaveProperty("edit_plan");
});
