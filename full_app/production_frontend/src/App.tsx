import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  EditorApi, clipsFromPlan, type AgentStep, type AgentResult,
  type ApiMode,
  type Job,
  type Options,
  type Preset,
  type ReviewClip,
} from "./api";
import { Director } from "./components/Director";
import { ClipEditor, Timeline } from "./components/ReviewTimeline";
import "./styles/editor.css";
import { baseCapabilities, demoCapabilities, extensionDefaults, type Capabilities } from "./features";
import { EditSettings } from "./components/EditSettings";
import { SourceInputs, type PlayerUpload } from "./components/SourceInputs";
import { ShareKit } from "./components/ShareKit";
const initialOptions: Options = {
  ...extensionDefaults,
  game: "auto",
  profile: "balanced",
  mode: "nice",
  style: "hype_montage",
  provider: "gemini",
  use_signals: true,
  captions: false,
  reactions: false,
  sam: false,
};
export default function App() {
  const query = new URLSearchParams(window.location.search);
  const mode: ApiMode =
    query.get("mock") === "1"
      ? "mock"
      : query.get("legacy") === "1"
        ? "legacy"
        : "jobs";
  const api = useMemo(() => new EditorApi(mode), [mode]);
  const [capabilities, setCapabilities] = useState<Capabilities>(mode === "mock" ? demoCapabilities : baseCapabilities);
  const [capabilityNotice, setCapabilityNotice] = useState("");
  useEffect(() => {
    let active = true;
    void api.discover().then(c => { if (active) setCapabilities(c); }).catch(() => {
      if (active) setCapabilityNotice("Could not check feature availability. Basic editing remains available.");
    });
    return () => { active = false; };
  }, [api]);
  const [options, setOptions] = useState(initialOptions);
  const [job, setJob] = useState<Job>();
  const [clips, setClips] = useState<ReviewClip[]>([]);
  const [source, setSource] = useState("");
  const [filename, setFilename] = useState("");
  const [directorBusy, setDirectorBusy] = useState(false);
  const [affectedClip, setAffectedClip] = useState<string>();
  const directorRollback = useRef<{clips: ReviewClip[]; plan: Job['plan']; dirty: boolean}>();
  const directorPlan = useRef<Job['plan']>();
  const stepListener = useRef<(step: AgentStep) => void>();
  const subscribeDirector = useCallback((listener: (step: AgentStep) => void) => {
    stepListener.current = listener;
    return () => { stepListener.current = undefined; };
  }, []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("Ready");
  const [preset, setPreset] = useState<Preset>("landscape");
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const [needsAnalysis, setNeedsAnalysis] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const rangeEnd = useRef<number>();
  const lastPlan = useRef<Job["plan"]>();
  const dirtyRef = useRef(false);
  const working =
    busy || directorBusy ||
    (!!job &&
      [
        "queued",
        "analyzing",
        "planning",
        "rendering",
        "uploading_to_gemini",
        "splitting_video",
        "importing",
        "syncing",
        "generating_thumbnails",
      ].includes(job.status));
  useEffect(
    () => () => {
      if (source) URL.revokeObjectURL(source);
    },
    [source],
  );
  useEffect(() => {
    if (!job?.id) return;
    return api.watch(
      job.id,
      (next) => {
        setJob(next);
        if (next.plan && !directorPlan.current) lastPlan.current = next.plan;
        if (!dirtyRef.current) setClips(next.clips);
      },
      setConnection,
      setError,
      step => stepListener.current?.(step),
    );
  }, [api, job?.id]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function validateFiles(files: File[]) {
    if (files.some(file => !file.type.startsWith("video/") && !/\.(mp4|mov|webm|mkv)$/i.test(file.name)))
      throw new Error("Choose a video file (MP4, MOV, WebM or MKV).");
    if (files.reduce((sum, file) => sum + file.size, 0) >= 2 * 1024 ** 3)
      throw new Error("Choose videos with a combined size smaller than 2 GB.");
  }
  function acceptJob(next: Job, label: string, file?: File) {
    dirtyRef.current = false;
    setDirty(false); setSaved(false); setClips([]); setJob(next);
    setNeedsAnalysis(false);
    directorPlan.current = undefined; setAffectedClip(undefined);
    lastPlan.current = undefined; rangeEnd.current = undefined;
    setSource(file ? URL.createObjectURL(file) : ""); setFilename(label);
    setOptions(o => ({ ...o, music_asset_id: "", chat_asset_id: "" }));
  }
  function upload(file?: File) {
    if (!file || working) return;
    void run(async () => { validateFiles([file]); acceptJob(await api.create(file), file.name, file); });
  }
  function uploadTeam(players: PlayerUpload[]) {
    if (working) return;
    void run(async () => {
      validateFiles(players.map(p => p.file));
      acceptJob(await api.createTeam(players), players.map(p => p.name).join(" + "), players[0].file);
    });
  }
  function importVod(url: string, owned: boolean) {
    if (working) return;
    void run(async () => acceptJob(await api.importVod(url, owned), "Imported VOD"));
  }
  function uploadAsset(kind: "music" | "chat", file: File) {
    if (!job || working) return;
    void run(async () => {
      if (file.size > 100 * 1024 ** 2) throw new Error("Choose an attachment smaller than 100 MB.");
      if (kind === "chat" && !/\.jsonl?$/i.test(file.name)) throw new Error("Choose a JSON or JSONL chat replay.");
      if (kind === "music" && !file.type.startsWith("audio/") && !/\.(wav|mp3|m4a|ogg|flac)$/i.test(file.name))
        throw new Error("Choose an audio track.");
      const assetId = await api.uploadAsset(job.id, kind, file);
      setOptions(o => ({ ...o, [`${kind}_asset_id`]: assetId }));
      if (kind === "chat" && clips.length) setNeedsAnalysis(true);
    });
  }
  function validateSettings() {
    if (options.music === "upload" && !options.music_asset_id) throw new Error("Attach your music track before continuing.");
    if (options.chat && !options.chat_asset_id && !options.twitch_vod_id) throw new Error("Supply a Twitch VOD ID or chat replay before continuing.");
  }
  const refresh = async () => {
    const next = await api.get(job!.id);
    setJob(next);
    if (next.plan && !directorPlan.current) lastPlan.current = next.plan;
    if (!dirtyRef.current) setClips(next.clips);
  };
  const edit = (next: ReviewClip[]) => {
    dirtyRef.current = true;
    setDirty(true);
    setSaved(false);
    setClips(next);
  };
  const save = async () => {
    await api.save(job!.id, clips);
    dirtyRef.current = false;
    setDirty(false);
    setSaved(true);
  };
  const seek = (time: number, end?: number) => {
    if (!video.current) return;
    rangeEnd.current = end;
    video.current.currentTime = time;
    if (end !== undefined)
      void video.current
        .play()
        .catch(() =>
          setError(
            "Video playback is unavailable. Try an MP4 with H.264 video.",
          ),
        );
  };
  const option = <K extends keyof Options>(key: K, value: Options[K]) => {
    setOptions((o) => ({ ...o, [key]: value,
      ...(key === 'mode' && o.chaos === (o.mode === 'mean' ? .6 : .35)
        ? {chaos: value === 'mean' ? .6 : .35} : {}) }));
    if (clips.length && ["game", "profile", "style", "provider", "use_signals", "audio_ai", "planner_v2", "window_scoring", "chat", "chat_offset", "twitch_vod_id", "fx_intensity"].includes(key)) setNeedsAnalysis(true);
  };
  const kept = clips.filter((c) => c.keep);
  const media = source || job?.source_url;
  return (
    <div className="editor-app">
      <header className="topbar">
        <a href="/" className="brand">
          LIM<span> / STUDIO</span>
        </a>
        <span className="session-label">GAMEPLAY / GREAT MOMENTS</span>
        <span className="connection">&#9679; {connection}</span>
      </header>
      <main>
        <div className="intro">
          <div>
            <p className="eyebrow">YOUR NEXT HIGHLIGHT STARTS HERE</p>
            <h1>Make every play count.</h1>
            <p>Find the moments. Shape the story. Make it yours.</p>
          </div>
          <span className="version">
            {mode === "mock"
              ? "DEMO WORKSPACE"
              : mode === "legacy"
                ? "CLASSIC BACKEND"
                : "EDITOR / 02"}
          </span>
        </div>
        {mode === "mock" && (
          <p className="notice">
            Demo mode - Fixture analysis and simulated export. Upload your own
            video for playback; no backend calls.
          </p>
        )}
        {mode === "legacy" && (
          <p className="notice">
            Classic backend - Landscape export only. Signals, captions,
            reactions, spotlight and provider selection require the jobs API.
          </p>
        )}
        {(error || job?.error) && (
          <div role="alert" className="error">
            {error || job?.error}
            <button
              onClick={() => {
                setError("");
              }}
            >
              Dismiss
            </button>
          </div>
        )}
        {!!job?.warnings?.length && (
          <div className="notice" role="status">
            {job.warnings.join(" ")}
          </div>
        )}
        <div className="workspace">
          <aside className="panel setup">
            <h2>
              <span>01</span> Set the scene
            </h2>
            <fieldset disabled={working}>
              <legend className="sr-only">Upload and analysis settings</legend>
              <SourceInputs capabilities={capabilities} upload={upload} team={uploadTeam} importVod={importVod}
                teamMode={options.team_mode ?? "best"} setTeamMode={v => option("team_mode", v)} />
              {filename && <p className="source-name" role="status">Source: {filename}</p>}
              {capabilityNotice && <p className="notice">{capabilityNotice}</p>}
              {mode === "jobs" && !capabilities.options.includes("privacy_blur") && <p className="hint">More features are available in demo mode. Disabled settings need backend support; privacy blur is not active on this server.</p>}
              <EditSettings options={options} change={option} capabilities={capabilities} legacy={mode === "legacy"}
                preset={preset} setPreset={setPreset} uploadAsset={uploadAsset} hasJob={!!job} />
              <button
                className="primary"
                disabled={!job}
                onClick={() =>
                  void run(async () => {
                    validateSettings();
                    dirtyRef.current = false;
                    setDirty(false);
                    setSaved(false);
                    directorPlan.current = undefined;
                    await api.analyze(job!.id, options);
                    setNeedsAnalysis(false);
                    await refresh();
                  })
                }
              >
                {clips.length ? "Analyze again" : "Find my moments"} &rarr;
              </button>
            </fieldset>
            <p className="hint">Review every cut before you export.</p>
            {needsAnalysis && <p className="notice">Settings changed. Analyze again to update your moments and plan before rendering.</p>}
          </aside>
          <section className="review panel">
            <div className="section-title">
              <h2>
                <span>02</span> Review the moments
              </h2>
              <span className="status" role="status">
                {busy
                  ? "Working..."
                  : job?.status?.replace(/_/g, " ") || "Awaiting footage"}
              </span>
            </div>
            {working && (
              <progress
                aria-label="Job progress"
                max="100"
                value={job?.progress}
              />
            )}
            <div className="player">
              {media ? (
                <video
                  ref={video}
                  src={media}
                  controls
                  onTimeUpdate={() => {
                    if (
                      video.current &&
                      rangeEnd.current !== undefined &&
                      video.current.currentTime >= rangeEnd.current
                    ) {
                      video.current.pause();
                      video.current.currentTime = rangeEnd.current;
                      rangeEnd.current = undefined;
                    }
                  }}
                  onError={() =>
                    setError(
                      "This browser cannot play the source video. Analysis can still proceed.",
                    )
                  }
                />
              ) : (
                <div className="empty-player">
                  <span>&#9655;</span>
                  <h3>Your best plays belong here.</h3>
                  <p>Upload gameplay to start building your reel.</p>
                </div>
              )}
            </div>
            {job && (
              <Timeline affectedClip={affectedClip} job={{ ...job, clips }} onSeek={(time) => seek(time)} />
            )}
            {job && clips.length > 0 && mode === 'jobs' && capabilities.options.includes('seed') && <div>
              <button disabled={working || needsAnalysis} onClick={() => void run(async () => {
                if (dirtyRef.current) await save();
                const seed = await api.reroll(job.id, options, preset, job.seed ?? options.seed ?? 0);
                setOptions(o => ({...o, seed, planner_v2: true}));
                directorPlan.current = undefined; lastPlan.current = undefined;
                dirtyRef.current = false; setDirty(false); await refresh();
              })}>🎲 Reroll</button>
              {job.seed !== undefined && <span>Seed: {job.seed}</span>}
            </div>}
            {job && (clips.length > 0 || job.plan || directorPlan.current) && mode === 'jobs' && <Director key={job.id} api={api} jobId={job.id} canRender={kept.length > 0}
              disabled={busy || needsAnalysis || (!directorBusy && working)} subscribe={subscribeDirector}
              onBusy={value => { setDirectorBusy(value); if (value) {
                directorRollback.current = {clips, plan: directorPlan.current, dirty: dirtyRef.current};
                dirtyRef.current = true;
              } }}
              onFailure={() => {
                const prior = directorRollback.current;
                if (prior) { setClips(prior.clips); directorPlan.current = prior.plan; dirtyRef.current = prior.dirty; }
                setAffectedClip(undefined);
              }}
              onStep={step => {
                const index = step.args?.segment_index !== undefined || step.args?.clip_index !== undefined
                  ? Number(step.args?.segment_index ?? step.args?.clip_index)
                  : clips.findIndex(c => c.id === String(step.args?.clip_id ?? step.diff?.clip_id));
                setAffectedClip(String(step.args?.clip_id ?? step.diff?.clip_id ?? clips[index]?.id ?? ''));
                const after = step.diff?.after as Job['plan'];
                if (after && Array.isArray(after.segments)) {
                  setClips(old => clipsFromPlan(after, old));
                } else if (Number.isInteger(index) && step.diff?.after && typeof step.diff.after === 'object') {
                  const patch = step.diff.after as Record<string, unknown>;
                  setClips(old => old.map((c, i) => i === index ? {...c,
                    start: typeof patch.source_start === 'number' ? patch.source_start : c.start,
                    end: typeof patch.source_end === 'number' ? patch.source_end : c.end,
                    caption: typeof patch.title === 'string' ? patch.title : c.caption} : c));
                }
              }}
              onPlan={(result: AgentResult) => {
                directorPlan.current = result.plan; lastPlan.current = result.plan;
                setClips(old => clipsFromPlan(result.plan, old));
                dirtyRef.current = true; setDirty(true); setSaved(false);
              }}
              onRender={() => void run(async () => {
                validateSettings();
                await api.render(job.id, preset, options, clips, directorPlan.current ?? job.plan, !!directorPlan.current);
                await refresh();
              })} />}
            <div className="section-title">
              <h3>
                Selected moments{" "}
                <span className="count">
                  {kept.length}/{clips.length}
                </span>
              </h3>
              <span>
                {kept.reduce((n, c) => n + c.end - c.start, 0).toFixed(1)}s
                selected
              </span>
            </div>
            {!clips.length && (
              <p className="empty-clips">
                {job
                  ? "Run analysis to discover clips for your timeline."
                  : "Your clips will appear here, ready to trim and reorder."}
              </p>
            )}
            <ClipEditor
              clips={clips}
              source={media}
              duration={job?.duration ?? 0}
              onChange={edit}
              onPreview={(c) => seek(c.start, c.end)}
              disabled={working}
            />
          </section>
        </div>
        <section className="panel export">
          <div>
            <h2>
              <span>03</span> Ready for the feed
            </h2>
            <p>
              {dirty
                ? "Unsaved edits - saved automatically before rendering"
                : saved
                  ? "Edits saved"
                  : "Choose your canvas and export your reel."}
            </p>
          </div>
          <label>
            Export preset
            <select
              value={preset}
              disabled={working || mode === "legacy"}
              onChange={(e) => setPreset(e.target.value as Preset)}
            >
              <option value="landscape">Landscape - 16:9</option>
              <option value="vertical">Vertical - 9:16</option>
              <option value="square">Square - 1:1</option>
            </select>
          </label>
          <button
            disabled={!job || !dirty || working}
            onClick={() => void run(save)}
          >
            Save edits
          </button>
          <button
            className="primary"
            disabled={!job || !kept.length || working || needsAnalysis}
            onClick={() =>
              void run(async () => {
                validateSettings();
                await save();
                await api.render(
                  job!.id,
                  preset,
                  options,
                  clips,
                  directorPlan.current ?? job?.plan ?? lastPlan.current,
                  !!directorPlan.current,
                );
                await refresh();
              })
            }
          >
            Render reel &#8599;
          </button>
        </section>
        {job?.status === "done" && (
          <section className="panel output">
            <h2>
              {mode === "mock" ? "Demo export complete" : "Your reel is ready"}
            </h2>
            {mode === "mock" ? (
              <p>
                Rendering is simulated. Switch to the jobs API to create a
                downloadable montage.
              </p>
            ) : (
              <>
                <video
                  controls
                  src={job.download_url || api.download(job.id)}
                />
                <a
                  className="primary"
                  href={job.download_url || api.download(job.id)}
                  download
                >
                  Download montage &darr;
                </a>
              </>
            )}
          </section>
        )}
        {job?.status === "done" && <ShareKit key={job.id} kit={job.share_kit} demo={mode === "mock"} />}
        <footer>
          LIM STUDIO <span>Made for the moments between respawns.</span>
          <a href={mode === "mock" ? "/" : "/?mock=1"}>
            {mode === "mock" ? "Connect backend" : "Try demo mode"}
          </a>
        </footer>
      </main>
    </div>
  );
}
