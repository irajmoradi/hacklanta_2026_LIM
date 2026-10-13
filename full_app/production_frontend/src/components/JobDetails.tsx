import { useEffect, useState } from 'react';
import type { EditorApi, Job } from '../api';

export function JobDetails({api, job, disabled, maxDuration, onImport, onRefresh}: {
  api: EditorApi; job: Job; disabled: boolean; maxDuration: number;
  onImport: (job: Job) => void; onRefresh: () => void;
}) {
  const [draft, setDraft] = useState('');
  const [modified, setModified] = useState(false);
  const [log, setLog] = useState('');
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const serialized = JSON.stringify(job.plan ?? {}, null, 2);
  useEffect(() => { if (!modified) setDraft(serialized); }, [serialized, modified]);
  useEffect(() => {
    if (!open) return;
    let active = true;
    const update = () => void api.log(job.id).then(value => { if (active) setLog(value); })
      .catch(e => { if (active) setError(e.message); });
    update();
    const timer = setInterval(update, 3000);
    return () => { active = false; clearInterval(timer); };
  }, [api, job.id, open]);
  async function apply() {
    setSaving(true); setError('');
    try {
      if (!Number.isFinite(maxDuration) || maxDuration < 10 || maxDuration > 600) throw new Error('Max duration must be between 10 and 600 seconds.');
      const next = await api.importPlan(job.id, JSON.parse(draft), maxDuration);
      onImport(next); setModified(false);
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }
  return <section className="panel job-details" aria-label="Job details">
    <details onToggle={e => setOpen(e.currentTarget.open)}>
      <summary>Job log</summary>
      <pre role="log" aria-label="Job log output">{log || 'Loading job log…'}</pre>
    </details>
    <details>
      <summary>Raw plan JSON</summary>
      <p className="hint">Import validates the entire render plan and duration on the server before replacing the draft. Rendering is a separate step.</p>
      {job.notes?.map(note => <p className="notice" key={note}>{note}</p>)}
      <label>Plan JSON<textarea spellCheck={false} value={draft} disabled={disabled || saving}
        onChange={e => { setDraft(e.target.value); setModified(true); }} /></label>
      <label>Import JSON file<input type="file" accept=".json,application/json" disabled={disabled || saving}
        onChange={async e => {
          const file = e.target.files?.[0]; e.target.value = '';
          if (!file) return;
          if (file.size > 2 * 1024 ** 2) { setError('Plan file must be smaller than 2 MB.'); return; }
          setDraft(await file.text()); setModified(true);
        }} /></label>
      <div className="director-actions">
        <button disabled={disabled || saving || api.mode !== 'jobs'} onClick={() => void apply()}>Validate &amp; apply JSON</button>
        <button disabled={disabled || saving || !job.clips.length || api.mode !== 'jobs'} onClick={onRefresh}>Refresh plan</button>
        <button disabled={!job.plan} onClick={() => {
          const url = URL.createObjectURL(new Blob([serialized], {type: 'application/json'}));
          const link = document.createElement('a'); link.href = url; link.download = `plan-${job.id}.json`; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }}>Export plan JSON</button>
        <button disabled={!modified} onClick={() => setModified(false)}>Reset JSON draft</button>
      </div>
      {modified && <p role="status">JSON draft has unapplied changes.</p>}
    </details>
    {error && <p role="alert" className="error">{error}</p>}
  </section>;
}
