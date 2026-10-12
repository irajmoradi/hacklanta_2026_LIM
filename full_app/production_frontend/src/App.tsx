import { useEffect, useMemo, useRef, useState } from "react";
import {
  EditorApi,
  type ApiMode,
  type Job,
  type Options,
  type Preset,
  type ReviewClip,
} from "./api";
import { ClipEditor, Timeline } from "./components/ReviewTimeline";
import "./styles/editor.css";
const initialOptions: Options = {
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
  const [options, setOptions] = useState(initialOptions);
  const [job, setJob] = useState<Job>();
  const [clips, setClips] = useState<ReviewClip[]>([]);
  const [source, setSource] = useState("");
  const [filename, setFilename] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("Ready");
  const [preset, setPreset] = useState<Preset>("landscape");
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const rangeEnd = useRef<number>();
  const dirtyRef = useRef(false);
  const working =
    busy ||
    (!!job &&
      [
        "queued",
        "analyzing",
        "planning",
        "rendering",
        "uploading_to_gemini",
        "splitting_video",
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
        if (!dirtyRef.current) setClips(next.clips);
      },
      setConnection,
      setError,
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
  function upload(file?: File) {
    if (!file || working) return;
    if (
      !file.type.startsWith("video/") &&
      !/\.(mp4|mov|webm|mkv)$/i.test(file.name)
    ) {
      setError("Choose a video file (MP4, MOV, WebM or MKV).");
      return;
    }
    if (file.size > 2 * 1024 ** 3) {
      setError("Choose a video smaller than 2 GB.");
      return;
    }
    void run(async () => {
      const next = await api.create(file);
      dirtyRef.current = false;
      setDirty(false);
      setSaved(false);
      setClips([]);
      setJob(next);
      setSource(URL.createObjectURL(file));
      setFilename(file.name);
    });
  }
  const refresh = async () => {
    const next = await api.get(job!.id);
    setJob(next);
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
  const option = <K extends keyof Options>(key: K, value: Options[K]) =>
    setOptions((o) => ({ ...o, [key]: value }));
  const kept = clips.filter((c) => c.keep);
  const media = source || job?.source_url;
  return (
    <div className="editor-app">
      <header className="topbar">
        <a href="/" className="brand">
          LIM<span> / STUDIO</span>
        </a>
        <span className="session-label">GAMEPLAY ? GREAT MOMENTS</span>
        <span className="connection">? {connection}</span>
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
            Demo mode � Fixture analysis and simulated export. Upload your own
            video for playback; no backend calls.
          </p>
        )}
        {mode === "legacy" && (
          <p className="notice">
            Classic backend � Landscape export only. Signals, captions,
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
        <div className="workspace">
          <aside className="panel setup">
            <h2>
              <span>01</span> Set the scene
            </h2>
            <fieldset disabled={working}>
              <legend className="sr-only">Upload and analysis settings</legend>
              <label
                className="dropzone"
                onDragOver={(e) => e.preventDefault()}
                onDrop={(e) => {
                  e.preventDefault();
                  upload(e.dataTransfer.files[0]);
                }}
              >
                <span className="upload-icon">?</span>
                <strong>{filename || "Drop your gameplay here"}</strong>
                <small>or choose a video � up to 2 GB</small>
                <input
                  aria-label="Upload gameplay"
                  type="file"
                  accept="video/*,.mkv"
                  onChange={(e) => upload(e.target.files?.[0])}
                />
              </label>
              <label>
                Game
                <select
                  value={options.game}
                  onChange={(e) => option("game", e.target.value)}
                >
                  <option value="auto">Auto-detect</option>
                  <option value="valorant">Valorant</option>
                  <option value="cs2">Counter-Strike 2</option>
                  <option value="fortnite">Fortnite</option>
                  <option value="other">Other game</option>
                </select>
              </label>
              <label>
                Profile
                <select
                  value={options.profile}
                  onChange={(e) => option("profile", e.target.value)}
                >
                  <option value="balanced">Balanced moments</option>
                  <option value="competitive">Competitive plays</option>
                  <option value="comedy">Comedy & chaos</option>
                </select>
              </label>
              <label>
                Mode
                <select
                  value={options.mode}
                  onChange={(e) =>
                    option("mode", e.target.value as Options["mode"])
                  }
                >
                  <option value="nice">Nice � Hype reel</option>
                  <option value="mean">Mean � Roast reel</option>
                </select>
              </label>
              <label>
                Style
                <select
                  value={options.style}
                  onChange={(e) => option("style", e.target.value)}
                >
                  <option value="hype_montage">Hype montage</option>
                  <option value="clean_edit">Clean edit</option>
                  <option value="meme_edit">Meme edit</option>
                  <option value="cinematic">Cinematic</option>
                </select>
              </label>
              <label>
                Provider
                <select
                  disabled={mode === "legacy"}
                  value={options.provider}
                  onChange={(e) => option("provider", e.target.value)}
                >
                  <option value="gemini">Gemini</option>
                  <option value="local">Local VLM</option>
                </select>
              </label>
              <div className="toggles">
                {(
                  [
                    ["use_signals", "Gameplay signals"],
                    ["captions", "Captions"],
                    ["reactions", "Meme reactions"],
                    ["sam", "SAM spotlight"],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      disabled={mode === "legacy"}
                      checked={options[key]}
                      onChange={(e) => option(key, e.target.checked)}
                    />
                    {label}
                  </label>
                ))}
              </div>
              <button
                className="primary"
                disabled={!job}
                onClick={() =>
                  void run(async () => {
                    dirtyRef.current = false;
                    setDirty(false);
                    setSaved(false);
                    await api.analyze(job!.id, options);
                    await refresh();
                  })
                }
              >
                {clips.length ? "Analyze again" : "Find my moments"} ?
              </button>
            </fieldset>
            <p className="hint">Review every cut before you export.</p>
          </aside>
          <section className="review panel">
            <div className="section-title">
              <h2>
                <span>02</span> Review the moments
              </h2>
              <span className="status" role="status">
                {busy
                  ? "Working�"
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
                  <span>?</span>
                  <h3>Your best plays belong here.</h3>
                  <p>Upload gameplay to start building your reel.</p>
                </div>
              )}
            </div>
            {job && (
              <Timeline job={{ ...job, clips }} onSeek={(time) => seek(time)} />
            )}
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
                ? "Unsaved edits � saved automatically before rendering"
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
              <option value="landscape">Landscape � 16:9</option>
              <option value="vertical">Vertical � 9:16</option>
              <option value="square">Square � 1:1</option>
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
            disabled={!job || !kept.length || working}
            onClick={() =>
              void run(async () => {
                await save();
                await api.render(job!.id, preset, options);
                await refresh();
              })
            }
          >
            Render reel ?
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
                  Download montage ?
                </a>
              </>
            )}
          </section>
        )}
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
