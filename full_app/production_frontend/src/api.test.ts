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
      preset: "vertical", style: "clean_edit",
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
  await api.analyze("abc", options);
  await api.render("abc", "square", {...options, captions: true}, [demoClips[0]],
    {render_version: 2, fps: 24, transition: "flash", music: {path: "licensed.wav"}, segments: []});
  expect(JSON.parse(fetcher.mock.calls[1][1].body).edit_plan).toMatchObject({render_version: 2, fps: 24,
    transition: "flash", music: {path: "licensed.wav"}, segments: [{title: demoClips[0].caption}]});
});
it("normalizes unit scores and actual fusion reaction fields", () => {
  expect(normalizeJob({id: "a", clips: [{score: .8, suggested_reaction_label: "clutch"}]}).clips[0])
    .toMatchObject({score: 80, reaction: "clutch"});
});
