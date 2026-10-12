import { useEffect, useRef, useState } from 'react';
import { ApiError, type AgentResult, type AgentStep, type EditorApi } from '../api';
const chips = ['Shorter (30 s)', 'More hype', 'Roast my deaths', 'Cut slow parts', 'Add reactions'];
export function Director({api, jobId, disabled, subscribe, onStep, onPlan, onBusy, onRender, onFailure, canRender = true}: {
  api: EditorApi; jobId: string; disabled: boolean;
  subscribe: (listener: (step: AgentStep) => void) => () => void;
  onStep: (step: AgentStep) => void; onPlan: (result: AgentResult) => void;
  canRender?: boolean;
  onFailure: () => void;
  onBusy: (busy: boolean) => void; onRender: () => void;
}) {
  const [instruction, setInstruction] = useState('');
  const [messages, setMessages] = useState<{role: string; text: string}[]>([]);
  const [steps, setSteps] = useState<AgentStep[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [undoCount, setUndoCount] = useState(0);
  const [version, setVersion] = useState<number>();
  const active = useRef(false);
  const mounted = useRef(true);
  const seen = useRef(new Set<number>());
  const callbacks = useRef({onStep, onPlan, onBusy});
  callbacks.current = {onStep, onPlan, onBusy};
  const receive = (step: AgentStep) => {
    if (!active.current || seen.current.has(step.step)) return;
    seen.current.add(step.step);
    setSteps(old => [...old, step]);
    callbacks.current.onStep(step);
  };
  useEffect(() => {
    mounted.current = true;
    const stop = subscribe(receive);
    return () => { mounted.current = false; active.current = false; stop(); };
  }, [subscribe]);
  async function act(undo = false) {
    if (active.current || disabled || (!undo && !instruction.trim())) return;
    active.current = true; setBusy(true); onBusy(true); setError('');
    seen.current.clear(); setSteps([]);
    const prompt = instruction.trim();
    if (!undo) { setMessages(old => [...old, {role: 'You', text: prompt}]); setInstruction(''); }
    try {
      const result = undo ? await api.undoAgent(jobId) : await api.agent(jobId, prompt);
      if (!mounted.current) return;
      result.trace?.forEach(receive);
      onPlan(result); setVersion(result.plan_version);
      setUndoCount(n => undo ? Math.max(0, n - 1) : n + 1);
      setMessages(old => [...old, {role: 'Director', text: undo ? 'Previous edit restored.' : 'Edit ready. Review the timeline, then apply and render.'}]);
    } catch (e) {
      if (!mounted.current) return;
      onFailure();
      const exhausted = e instanceof ApiError && (e.code === 'budget_exhausted' || e.status === 429);
      setError(exhausted ? 'Director budget exhausted. You can undo or render the current edit.' : (e as Error).message);
      if (!undo) setInstruction(prompt);
    } finally {
      active.current = false;
      if (mounted.current) { setBusy(false); callbacks.current.onBusy(false); }
    }
  }
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z' && !event.shiftKey
        && !(target instanceof Element && target.closest('input, textarea, [contenteditable="true"]')) && undoCount && !busy && !disabled) {
        event.preventDefault(); void act(true);
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  });
  return <section className="director" aria-label="Director">
    <div className="section-title"><h3>Director</h3><small>{version === undefined ? 'CHAT TO EDIT' : `Plan v${version}`}</small></div>
    <p className="hint">Tell your editor what the reel needs.</p>
    <div className="director-thread" role="log" aria-label="Director conversation">{messages.map((m, i) => <p key={i}><strong>{m.role}</strong> {m.text}</p>)}</div>
    <div className="director-chips">{chips.map(chip => <button key={chip} disabled={busy || disabled} onClick={() => setInstruction(chip)}>{chip}</button>)}</div>
    <label>Editing instruction<textarea value={instruction} disabled={busy || disabled} onChange={e => setInstruction(e.target.value)}
      placeholder="Keep the clutch, cut the waiting…" onKeyDown={e => {
        if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); void act(); }
      }} /></label>
    <div className="director-actions"><button disabled={busy || disabled || !instruction.trim()} onClick={() => void act()}>Send</button>
      <button disabled={busy || disabled || !undoCount} onClick={() => void act(true)}>Undo</button>
      <button className="primary" disabled={busy || disabled || !canRender} onClick={onRender}>Apply &amp; render</button></div>
    {busy && <p role="status">Director is editing…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <ol className="director-trace" aria-label="Edit trace" aria-live="polite">{steps.map(step => <li key={step.step}>
      <strong><span aria-hidden="true">{ /trim|cut/.test(step.tool) ? '✂' : /reaction|effect/.test(step.tool) ? '✦' : '↔' }</span> {step.tool}</strong>
      <p>{step.rationale}</p>{step.diff && ('before' in step.diff || 'after' in step.diff)
        ? <div className="director-diff"><div><small>Before</small><pre>{JSON.stringify(step.diff.before ?? 'Unavailable')}</pre></div>
          <div><small>After</small><pre>{JSON.stringify(step.diff.after ?? 'Unavailable')}</pre></div></div>
        : <pre>{JSON.stringify(step.diff ?? {})}</pre>}
    </li>)}</ol>
  </section>;
}
