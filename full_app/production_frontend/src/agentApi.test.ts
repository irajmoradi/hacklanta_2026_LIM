import { afterEach, expect, it, vi } from 'vitest';
import { ApiError, EditorApi } from './api';
afterEach(() => vi.unstubAllGlobals());
it('uses the agent contract and preserves budget error codes', async () => {
  const response = {plan: {segments: [{source_start: 0, source_end: 5}]}, plan_version: 3, trace: []};
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => response});
  vi.stubGlobal('fetch', fetcher);
  const api = new EditorApi('jobs');
  expect(await api.agent('a/b', 'More hype')).toEqual(response);
  expect(fetcher).toHaveBeenLastCalledWith('/api/jobs/a%2Fb/agent', expect.objectContaining({method: 'POST', body: '{"instruction":"More hype"}'}));
  await api.undoAgent('a/b');
  expect(fetcher.mock.calls[1][0]).toBe('/api/jobs/a%2Fb/agent/undo');
  fetcher.mockResolvedValue({ok: false, status: 429, json: async () => ({error: {code: 'budget_exhausted', message: 'Limit'}})});
  await expect(api.agent('one', 'Trim')).rejects.toMatchObject({code: 'budget_exhausted', status: 429});
});
it('dispatches named SSE steps and closes the existing stream on cleanup', () => {
  let stream: EventTarget;
  const close = vi.fn();
  vi.stubGlobal('EventSource', class extends EventTarget {close = close; constructor() {super(); stream = this;} });
  const received = vi.fn();
  const stop = new EditorApi('jobs').watch('one', vi.fn(), vi.fn(), vi.fn(), received);
  stream!.dispatchEvent(new MessageEvent('agent_step', {data: JSON.stringify({step: 1, tool: 'trim', args: {}, rationale: 'Trim', diff: {}})}));
  expect(received).toHaveBeenCalledTimes(1);
  stream!.dispatchEvent(new MessageEvent('agent_step', {data: 'invalid'}));
  stop(); expect(close).toHaveBeenCalled();
  stream!.dispatchEvent(new MessageEvent('agent_step', {data: '{"step":2,"tool":"trim"}'}));
  expect(received).toHaveBeenCalledTimes(1);
});
