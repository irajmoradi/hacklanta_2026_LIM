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
    const fetcher = vi
      .fn()
      .mockResolvedValue({
        ok: true,
        json: async () => ({ id: "abc", meta: { duration: 60 } }),
      });
    vi.stubGlobal("fetch", fetcher);
    const api = new EditorApi("jobs");
    await api.create(new File(["x"], "video.mp4"));
    expect(fetcher.mock.calls[0][0]).toBe("/api/jobs");
    expect(fetcher.mock.calls[0][1].body.get("video").name).toBe("video.mp4");
    await api.analyze("abc", options);
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual(options);
    await api.save("abc", [demoClips[2], { ...demoClips[0], keep: false }]);
    expect(fetcher.mock.calls[2][1].method).toBe("PATCH");
    expect(JSON.parse(fetcher.mock.calls[2][1].body).clips[1]).toMatchObject({
      keep: false,
      order: 1,
      start_seconds: 8,
    });
    await api.render("abc", "vertical", options);
    expect(JSON.parse(fetcher.mock.calls[3][1].body)).toEqual({
      preset: "vertical",
    });
  });
  it("surfaces structured server errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
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
    const fetcher = vi
      .fn()
      .mockResolvedValue({
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
