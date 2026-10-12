import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { EditorApi, normalizeClip, type Options } from "./api";
import { demoCapabilities, extensionDefaults, normalizeKit, signalChips, validateVod } from "./features";
import { ShareKit } from "./components/ShareKit";
import App from "./App";
const options: Options = { ...extensionDefaults, game: "overwatch2", profile: "balanced", mode: "nice", style: "hype_montage", provider: "gemini", use_signals: true, captions: true, reactions: false, sam: false };
const video = (name: string) => new File(["synthetic placeholder"], name, { type: "video/mp4" });
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState({}, "", "/"); });

it("sends only advertised extensions and preserves baseline compatibility", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs");
  await api.discover();
  await api.analyze("one", options);
  const old = JSON.parse(fetcher.mock.calls[1][1].body);
  expect(old).not.toHaveProperty("privacy_blur");
  expect(old).not.toHaveProperty("music");
  expect(old.prompt).toContain("overwatch2");
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ frontend_capabilities: demoCapabilities }) });
  await api.discover();
  await api.analyze("one", { ...options, narration: true, narration_persona: "deadpan_roast", music: "chill", chat: true, twitch_vod_id: "123" });
  expect(JSON.parse(fetcher.mock.calls[3][1].body)).toMatchObject({ game: "overwatch2", privacy: false, narration_persona: "deadpan_roast", music: true, twitch_vod_id: "123" });
  await api.render("one", "vertical", { ...options, fx_intensity: 0.75, keep_my_name: "Alice" }, [], { segments: [], music: { path: "server-owned" } } as any);
  expect(JSON.parse(fetcher.mock.calls[4][1].body)).toMatchObject({ preset: "vertical", fx_intensity: 0.75, keep_my_name: "Alice", edit_plan: { music: { path: "server-owned" } } });
});

it("uploads team files in player order, imports owned VODs, and attaches assets", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ id: "squad", asset_id: "track-1" }) });
  vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs"); api.capabilities = demoCapabilities;
  await api.createTeam([{ file: video("alice.mp4"), name: " Alice " }, { file: video("bob.mp4"), name: "Bob" }]);
  expect(fetcher.mock.calls[0][0]).toBe("/api/jobs");
  const form = fetcher.mock.calls[0][1].body as FormData;
  expect(form.getAll("video").map(v => (v as File).name)).toEqual(["alice.mp4", "bob.mp4"]);
  expect(JSON.parse(form.get("players") as string)).toEqual(["Alice", "Bob"]);
  await expect(api.importVod("https://www.twitch.tv/videos/123", false)).rejects.toThrow("permission");
  expect(fetcher).toHaveBeenCalledTimes(1);
  await api.importVod("https://www.twitch.tv/videos/123", true);
  expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ url: "https://www.twitch.tv/videos/123", owns_content: true });
  const music = new File(["audio"], "original.wav", { type: "audio/wav" });
  expect(await api.uploadAsset("a/b", "music", music)).toBe("track-1");
  expect(fetcher.mock.calls[2][0]).toBe("/api/jobs/a%2Fb/assets/music");
  expect(fetcher.mock.calls[2][1].body.get("music")).toBe(music);
  await expect(api.createTeam([{ file: video("a.mp4"), name: "Alice" }, { file: video("b.mp4"), name: "alice" }])).rejects.toThrow("unique");
});

it("rejects unsupported new operations before requests and validates URL hosts", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const api = new EditorApi("jobs");
  await expect(api.createTeam([{ file: video("a.mp4"), name: "A" }, { file: video("b.mp4"), name: "B" }])).rejects.toThrow("unavailable");
  await expect(api.uploadAsset("one", "chat", new File([], "chat.json"))).rejects.toThrow("unavailable");
  for (const url of ["http://youtube.com/watch?v=1", "https://youtube.com.evil.test/v", "file:///secret", "https://user:pass@youtube.com/watch?v=1"])
    expect(() => validateVod(url)).toThrow();
  expect(fetcher).not.toHaveBeenCalled();
});

it("shows only actual signal evidence and never fabricates hype from a fused score", () => {
  expect(signalChips({ score: 99, signals: { kill_feed: 2, audio_spike: 0, laughter: 0.8, chat_emote_spike: 3 }, hype: 8.5 })).toEqual(["Kill-feed", "Laughter", "Chat spike", "Gemini hype 8.5/10"]);
  expect(signalChips({ score: 99 })).toEqual([]);
  expect(normalizeClip({ start: 1, end: 3, signals: { audio: 0.7 } }, 0).why).toEqual(["Audio spike"]);
});

it("copies share text, filters unsafe links, and reports clipboard failures", async () => {
  const user = userEvent.setup();
  const clipboard = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
  const kit = normalizeKit({ titles: ["Round saved"], description: "My original gameplay", chapters: "00:00 Clutch", thumbnails: [{ url: "/api/cover.jpg", label: "Landscape" }], downloads: [{ url: "javascript:alert(1)", label: "Unsafe" }, { url: "/api/kit.zip", label: "Download ZIP" }] });
  render(<ShareKit kit={kit} demo={false} />);
  expect(screen.getByAltText("Landscape")).toHaveAttribute("src", "/api/cover.jpg");
  expect(screen.queryByRole("link", { name: "Unsafe" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Download ZIP" })).toHaveAttribute("download");
  await user.click(screen.getByRole("button", { name: "Copy description" }));
  expect(clipboard).toHaveBeenCalledWith("My original gameplay");
  expect(screen.getByRole("status")).toHaveTextContent("Description copied");
  clipboard.mockRejectedValueOnce(new Error("denied"));
  await user.click(screen.getByRole("button", { name: "Copy chapters" }));
  expect(screen.getByRole("status")).toHaveTextContent("Select and copy");
});

it("runs team settings, assets, signals and share-kit demo without network", async () => {
  window.history.replaceState({}, "", "/?mock=1");
  URL.createObjectURL = vi.fn().mockReturnValue("blob:team"); URL.revokeObjectURL = vi.fn();
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup(); render(<App />);
  await user.selectOptions(screen.getByLabelText("Footage source"), "team");
  await user.upload(screen.getByLabelText("Team recordings"), [video("Alice.mp4"), video("Bob.mp4")]);
  await user.clear(screen.getByLabelText("Player 2 name")); await user.type(screen.getByLabelText("Player 2 name"), "Blake");
  await user.selectOptions(screen.getByLabelText("Team layout"), "pip");
  await user.click(screen.getByRole("button", { name: "Upload team recordings" }));
  await screen.findByText("Source: Alice + Blake");
  await user.click(screen.getByRole("checkbox", { name: /^AI narration/ }));
  await user.selectOptions(screen.getByLabelText("Narration persona"), "nature_documentary");
  await user.type(screen.getByLabelText("Keep my name"), "Alice");
  await user.selectOptions(screen.getByLabelText("Music bed"), "upload");
  await user.upload(screen.getByLabelText(/Upload music/), new File(["audio"], "original.wav", { type: "audio/wav" }));
  await screen.findByText("Music attached");
  await user.click(screen.getByRole("checkbox", { name: /^Share kit/ }));
  fireEvent.change(screen.getByLabelText("FX intensity"), { target: { value: "0.75" } });
  await user.click(screen.getByRole("button", { name: /Find my moments/ }));
  await screen.findByText("Kill-feed");
  await user.click(screen.getByRole("button", { name: /Render reel/ }));
  await screen.findByRole("button", { name: "Copy title 1" });
  expect(screen.getByAltText("Demo landscape cover")).toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});

it("imports a demo VOD only after the ownership checkbox is selected", async () => {
  window.history.replaceState({}, "", "/?mock=1");
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup(); render(<App />);
  await user.selectOptions(screen.getByLabelText("Footage source"), "url");
  await user.type(screen.getByLabelText("VOD URL"), "https://youtu.be/owned");
  expect(screen.getByRole("button", { name: "Import VOD" })).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: "I own this VOD or have permission" }));
  await user.click(screen.getByRole("button", { name: "Import VOD" }));
  await screen.findByText("Source: Imported VOD");
  expect(fetcher).not.toHaveBeenCalled();
});


it("applies full experience while keeping privacy off and editable", async () => {
  window.history.replaceState({}, "", "/?mock=1");
  const user = userEvent.setup(); render(<App />);
  const privacy = screen.getByRole("checkbox", {name: /^Privacy blur/});
  expect(privacy).not.toBeChecked();
  await user.click(screen.getByRole("button", {name: "Full experience"}));
  expect(screen.getByRole("checkbox", {name: /^Captions/})).toBeChecked();
  expect(screen.getByRole("checkbox", {name: /^Intro and outro/})).toBeChecked();
  expect(screen.getByRole("checkbox", {name: /^Varied transitions/})).toBeChecked();
  expect(screen.getByLabelText("Music bed")).toHaveValue("energetic");
  expect(privacy).not.toBeChecked();
  await user.click(privacy);
  expect(privacy).toBeChecked();
});
