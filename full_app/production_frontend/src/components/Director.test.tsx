import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { Director } from './Director';
import { ApiError, EditorApi, type AgentStep, type AgentResult } from '../api';
const step: AgentStep = {step: 1, tool: 'trim_clip', args: {clip_id: 'one'}, rationale: 'Keep the action.', diff: {before: {source_end: 10}, after: {source_end: 7}}};
const result: AgentResult = {plan: {segments: [{source_start: 1, source_end: 7}]}, plan_version: 2, trace: [step]};
function setup() {
  const api = new EditorApi('jobs');
  let listener: (s: AgentStep) => void = () => {};
  const stop = vi.fn();
  const props = {api, jobId: 'one', disabled: false, subscribe: (fn: typeof listener) => {listener = fn; return stop;},
    onStep: vi.fn(), onPlan: vi.fn(), onBusy: vi.fn(), onRender: vi.fn(), onFailure: vi.fn()};
  const view = render(<Director {...props} />);
  return {...props, ...view, emit: (s: AgentStep) => act(() => listener(s)), stop};
}
it('sends with Enter, displays streamed steps once, applies final plan, and undoes with Ctrl+Z', async () => {
  const x = setup();
  let finish!: (r: AgentResult) => void;
  const send = vi.spyOn(x.api, 'agent').mockImplementation(() => new Promise(resolve => {finish = resolve;}));
  const undo = vi.spyOn(x.api, 'undoAgent').mockResolvedValue({...result, plan_version: 1});
  await userEvent.click(screen.getByRole('button', {name: 'More hype'}));
  fireEvent.keyDown(screen.getByLabelText('Editing instruction'), {key: 'Enter'});
  expect(send).toHaveBeenCalledWith('one', 'More hype');
  expect(screen.getByRole('button', {name: 'Send'})).toBeDisabled();
  x.emit(step); x.emit(step);
  expect(screen.getAllByText('Keep the action.')).toHaveLength(1);
  await act(async () => finish(result));
  expect(x.onStep).toHaveBeenCalledTimes(1);
  expect(x.onPlan).toHaveBeenCalledWith(result);
  await userEvent.click(screen.getByRole('button', {name: 'Apply & render'}));
  expect(x.onRender).toHaveBeenCalled();
  fireEvent.keyDown(window, {key: 'z', ctrlKey: true});
  await waitFor(() => expect(undo).toHaveBeenCalledWith('one'));
  await waitFor(() => expect(screen.getByRole('button', {name: 'Undo'})).toBeDisabled());
  x.unmount(); expect(x.stop).toHaveBeenCalled();
});
it.each([new ApiError('Limit', 'budget_exhausted', 429), new Error('Network unavailable')])('restores failed instruction and reports errors', async error => {
  const x = setup(); vi.spyOn(x.api, 'agent').mockRejectedValue(error);
  await userEvent.type(screen.getByLabelText('Editing instruction'), 'Cut slow parts');
  await userEvent.click(screen.getByRole('button', {name: 'Send'}));
  expect(await screen.findByRole('alert')).toHaveTextContent(error instanceof ApiError ? 'budget exhausted' : 'Network unavailable');
  expect(x.onFailure).toHaveBeenCalled();
  expect(screen.getByLabelText('Editing instruction')).toHaveValue('Cut slow parts');
  expect(x.onPlan).not.toHaveBeenCalled();
});
it('keeps Shift+Enter and text-field undo native', async () => {
  const x = setup(); const send = vi.spyOn(x.api, 'agent').mockResolvedValue(result);
  const input = screen.getByLabelText('Editing instruction');
  fireEvent.change(input, {target: {value: 'More hype'}});
  fireEvent.keyDown(input, {key: 'Enter', shiftKey: true});
  expect(send).not.toHaveBeenCalled();
});
