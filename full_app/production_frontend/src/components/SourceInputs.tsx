import { useState } from "react";
import type { Capabilities } from "../features";
export interface PlayerUpload { file: File; name: string }
export function SourceInputs({ capabilities, upload, team, importVod, teamMode, setTeamMode }: {
  capabilities: Capabilities; upload: (file?: File) => void;
  team: (players: PlayerUpload[]) => void; importVod: (url: string, owned: boolean) => void;
  teamMode: string; setTeamMode: (mode: string) => void;
}) {
  const [kind, setKind] = useState("file");
  const [players, setPlayers] = useState<PlayerUpload[]>([]);
  const [url, setUrl] = useState("");
  const [owned, setOwned] = useState(false);
  return <div className="source-inputs">
    <label>Footage source<select value={kind} onChange={e => setKind(e.target.value)}>
      <option value="file">Single recording</option>
      <option value="team" disabled={!capabilities.team_upload}>Team recordings{!capabilities.team_upload ? " — unavailable" : ""}</option>
      <option value="url" disabled={!capabilities.url_import}>VOD URL{!capabilities.url_import ? " — unavailable" : ""}</option>
    </select></label>
    {kind === "file" && <label className="dropzone" onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); upload(e.dataTransfer.files[0]); }}>
      <span className="upload-icon">↥</span><strong>Drop your gameplay here</strong><small>or choose a video - up to 2 GB</small>
      <input aria-label="Upload gameplay" type="file" accept="video/*,.mkv" onChange={e => { upload(e.target.files?.[0]); e.target.value = ""; }} />
    </label>}
    {kind === "team" && <>
      <label>Team recordings<input type="file" multiple accept="video/*,.mkv" onChange={e => {
        setPlayers(Array.from(e.target.files ?? []).map(file => ({ file, name: file.name.replace(/\.[^.]+$/, "") })));
        e.target.value = "";
      }} /></label>
      <small>Choose recordings of the same match. Up to 2 GB combined.</small>
      {players.map((p, i) => <label key={i}>Player {i + 1}<small>{p.file.name}</small>
        <input aria-label={`Player ${i + 1} name`} maxLength={80} value={p.name} onChange={e => setPlayers(players.map((v, n) => n === i ? { ...v, name: e.target.value } : v))} />
      </label>)}
      <label>Team layout<select value={teamMode} onChange={e => setTeamMode(e.target.value)}>
        <option value="best">Best POV</option><option value="split">Side by side</option><option value="pip">Picture in picture</option>
      </select></label>
      <button disabled={players.length < 2} onClick={() => team(players)}>Upload team recordings</button>
    </>}
    {kind === "url" && <>
      <label>VOD URL<input type="url" value={url} placeholder="https://www.twitch.tv/videos/…" onChange={e => setUrl(e.target.value)} /></label>
      <p className="hint">Own VODs only: import a Twitch or YouTube recording you own or have permission to edit.</p>
      <label><input type="checkbox" checked={owned} onChange={e => setOwned(e.target.checked)} />I own this VOD or have permission</label>
      <button disabled={!url.trim() || !owned} onClick={() => importVod(url.trim(), owned)}>Import VOD</button>
    </>}
  </div>;
}
