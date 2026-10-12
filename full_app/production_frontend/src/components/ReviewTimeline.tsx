import { useRef } from "react";
import type { ReviewClip, Job } from "../api";
export function Timeline({
  job,
  onSeek, affectedClip,
}: {
  job: Job;
  affectedClip?: string;
  onSeek: (time: number) => void;
}) {
  const duration = Math.max(1, job.duration);
  const kept = job.clips.filter(c => c.keep);
  const montageDuration = Math.max(0.1, kept.reduce((sum, c) => sum + c.end - c.start, 0));
  let montageOffset = 0;
  const points = job.interest
    .map(
      (p) =>
        `${Math.max(0, Math.min(100, (p.time / duration) * 100))},${100 - Math.max(0, Math.min(100, p.score))}`,
    )
    .join(" ");
  return (
    <section className="timeline" aria-label="Review timeline">
      <div className="section-title">
        <h3>Interest timeline</h3>
        <span>Source - {duration.toFixed(1)}s</span>
      </div>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        role="img"
        aria-label={
          points
            ? "Interest score over source time"
            : "Interest scores unavailable"
        }
      >
        <polyline
          points={points}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      {!points && <small>No interest signal supplied</small>}
      <div className="markers" aria-label="Candidate markers">
        {job.candidates.map((c) => (
          <button
            key={c.id}
            style={{ left: `${Math.min(98, (c.start / duration) * 100)}%` }}
            onClick={() => onSeek(c.start)}
            aria-label={`Candidate: ${c.caption}`}
            title={c.caption}
          >
            &#9670;
          </button>
        ))}
      </div>
      <div className="clip-track">
        {job.clips.map((c) => (
          <button
            key={c.id}
            className={`${c.keep ? "" : "dropped"} ${affectedClip === c.id ? "agent-affected" : ""}`}
            style={{
              left: `${(c.start / duration) * 100}%`,
              width: `${Math.max(0.5, ((c.end - c.start) / duration) * 100)}%`,
            }}
            onClick={() => onSeek(c.start)}
            aria-label={`Seek to ${c.caption}`}
            title={c.caption}
          />
        ))}
      </div>
      <small>Edit order ? {montageDuration.toFixed(1)}s</small>
      <div className="clip-track montage-track" aria-label="Montage order">
        {kept.map((c, index) => {
          const left = montageOffset / montageDuration * 100;
          montageOffset += c.end - c.start;
          return <button key={c.id} className={affectedClip === c.id ? 'agent-affected' : ''}
            style={{left: `${left}%`, width: `${(c.end - c.start) / montageDuration * 100}%`}}
            aria-label={`Edit ${index + 1}: ${c.caption}`} onClick={() => onSeek(c.start)}>{index + 1}</button>;
        })}
      </div>
      <label className="seek">
        Seek source
        <input
          type="range"
          min="0"
          max={duration}
          step="0.1"
          defaultValue="0"
          onChange={(e) => onSeek(Number(e.target.value))}
        />
      </label>
      <div className="section-title">
        <small>0:00</small>
        <small>
          {Math.floor(duration / 60)}:
          {String(Math.floor(duration % 60)).padStart(2, "0")}
        </small>
      </div>
    </section>
  );
}
export function ClipEditor({
  clips,
  duration,
  source,
  onChange,
  onPreview,
  disabled = false,
}: {
  clips: ReviewClip[];
  duration: number;
  source?: string;
  onChange: (clips: ReviewClip[]) => void;
  onPreview: (clip: ReviewClip) => void;
  disabled?: boolean;
}) {
  const dragged = useRef<string>();
  const change = (id: string, patch: Partial<ReviewClip>) =>
    onChange(clips.map((c) => (c.id === id ? { ...c, ...patch } : c)));
  const move = (id: string, target: number) => {
    const next = [...clips];
    const index = next.findIndex((c) => c.id === id);
    if (index < 0 || target < 0 || target >= next.length) return;
    next.splice(target, 0, next.splice(index, 1)[0]);
    onChange(next);
  };
  return (
    <fieldset disabled={disabled} className="clip-list">
      <legend className="sr-only">Clip edits</legend>
      {clips.map((c, i) => (
        <article
          key={c.id}
          className={`clip-card ${c.keep ? "" : "dropped"}`}
          draggable={!disabled}
          onDragStart={(e) => {
            dragged.current = c.id;
            e.dataTransfer.setData("text/plain", c.id);
          }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            if (!disabled && dragged.current) move(dragged.current, i);
            dragged.current = undefined;
          }}
        >
          <div className="clip-heading">
            <span className="clip-number">
              {String(i + 1).padStart(2, "0")}
            </span>
            <strong>{c.caption}</strong>
            <label>
              <input
                type="checkbox"
                checked={c.keep}
                onChange={(e) => change(c.id, { keep: e.target.checked })}
                aria-label={`Keep ${c.caption}`}
              />{" "}
              Keep
            </label>
          </div>
          <div className="clip-content">
            <div className="thumb">
              {c.thumbnail ? (
                <img src={c.thumbnail} alt={`Thumbnail: ${c.caption}`} />
              ) : source ? (
                <video
                  src={`${source}#t=${c.start}`}
                  muted
                  preload="metadata"
                  aria-label={`Thumbnail: ${c.caption}`}
                />
              ) : (
                <span>Preview unavailable</span>
              )}
            </div>
            <div className="clip-details">
              <div className="badges">
                <span>Score {c.score}</span>
                <span>{c.reaction}</span>
                <span>{(c.end - c.start).toFixed(1)}s</span>
              </div>
              <div className="why-clips" aria-label={`Why this clip ${i + 1}`}>
                <small>Why this clip</small>
                <div className="badges">{c.why?.length ? c.why.map(reason => <span key={reason}>{reason}</span>) : <small>No signal details supplied</small>}</div>
              </div>
              <label>
                Caption
                <input
                  value={c.caption}
                  onChange={(e) => change(c.id, { caption: e.target.value })}
                  aria-label={`Caption ${i + 1}`}
                />
              </label>
            </div>
          </div>
          <div className="trims">
            <label>
              In - {c.start.toFixed(1)}s
              <input
                aria-label={`Trim start ${i + 1}`}
                type="range"
                min="0"
                max={Math.max(0, c.end - 0.1)}
                step="0.1"
                value={c.start}
                onChange={(e) =>
                  change(c.id, {
                    start: Math.max(
                      0,
                      Math.min(Number(e.target.value), c.end - 0.1),
                    ),
                  })
                }
              />
            </label>
            <label>
              Out - {c.end.toFixed(1)}s
              <input
                aria-label={`Trim end ${i + 1}`}
                type="range"
                min={c.start + 0.1}
                max={Math.max(duration, c.end)}
                step="0.1"
                value={c.end}
                onChange={(e) =>
                  change(c.id, {
                    end: Math.min(
                      Math.max(duration, c.end),
                      Math.max(c.start + 0.1, Number(e.target.value)),
                    ),
                  })
                }
              />
            </label>
          </div>
          <div className="clip-actions">
            <button type="button" onClick={() => onPreview(c)}>
              Preview range
            </button>
            <button
              type="button"
              disabled={disabled || i === 0}
              aria-label={`Move clip ${i + 1} up`}
              onClick={() => move(c.id, i - 1)}
            >
              &uarr;
            </button>
            <button
              type="button"
              disabled={disabled || i === clips.length - 1}
              aria-label={`Move clip ${i + 1} down`}
              onClick={() => move(c.id, i + 1)}
            >
              &darr;
            </button>
            <small>Drag to reorder</small>
          </div>
        </article>
      ))}
    </fieldset>
  );
}
