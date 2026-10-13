import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import App from './App';
import { EditorApi, normalizeJob, type Options } from './api';
import { JobDetails } from './components/JobDetails';
import { demoCapabilities } from './features';

afterEach(() => { window.history.replaceState({}, '', '/'); vi.unstubAllGlobals(); });
const options: Options = {game: 'deadlock', profile: 'balanced', mode: 'nice', style: 'hype_montage',
  provider: 'gemini', use_signals: true, captions: false, reactions: false, sam: false};

it('changes automatic styles with mode until a style is explicitly selected; preserves explicit durations', async () => {
  window.history.replaceState({}, '', '/?mock=1');
  render(<App />);
  await userEvent.selectOptions(screen.getByLabelText('Mode'), 'mean');
  expect(screen.getByLabelText('Style')).toHaveValue('meme_edit');
  await userEvent.selectOptions(screen.getByLabelText('Mode'), 'nice');
  expect(screen.getByLabelText('Style')).toHaveValue('hype_montage');
  await userEvent.selectOptions(screen.getByLabelText('Style'), 'cinematic');
  await userEvent.selectOptions(screen.getByLabelText('Mode'), 'mean');
  expect(screen.getByLabelText('Style')).toHaveValue('cinematic');
  expect(screen.getByLabelText('Max duration (seconds)')).toHaveValue(60);
  await userEvent.selectOptions(screen.getByLabelText('Canvas preset'), 'vertical');
  expect(screen.getByLabelText('Max duration (seconds)')).toHaveValue(30);
  fireEvent.change(screen.getByLabelText('Max duration (seconds)'), {target: {value: '45'}});
  await userEvent.selectOptions(screen.getByLabelText('Canvas preset'), 'landscape');
  expect(screen.getByLabelText('Max duration (seconds)')).toHaveValue(45);
  await userEvent.type(screen.getByLabelText('Analysis instructions'), 'Find saves');
  await userEvent.type(screen.getByLabelText('Editing instructions'), 'Quiet opening');
  expect(screen.getByLabelText('Analysis instructions')).toHaveValue('Find saves');
  expect(screen.getByLabelText('Editing instructions')).toHaveValue('Quiet opening');
  await userEvent.click(screen.getByRole('button', {name: /Full experience/}));
  expect(screen.getByLabelText(/AI thumbnails/)).toBeChecked();
  expect(screen.getByLabelText(/Share kit/)).toBeChecked();
});

it('appends analysis context, sends separate editing instructions and duration on all planning routes', async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({})});
  vi.stubGlobal('fetch', fetcher);
  const api = new EditorApi('jobs'); api.capabilities = demoCapabilities;
  const settings = {...options, analysis_instructions: 'Look for saves', editing_instructions: 'Quiet opening',
    max_duration: 42, gemini_image: true, share_kit: true, plan_refinement: true};
  await api.analyze('job', settings, 'vertical');
  await api.plan('job', settings, 'vertical');
  await api.render('job', 'vertical', settings);
  expect(JSON.parse(fetcher.mock.calls[0][1].body).prompt).toBe('Look for saves\nGame: deadlock. Profile: balanced.');
  for (const [, request] of fetcher.mock.calls) {
    expect(JSON.parse(request.body)).toMatchObject({editing_instructions: 'Quiet opening', max_duration: 42,
      preset: 'vertical', gemini_image: true, social: true, plan_refinement: true});
  }
});

it('displays job logs as text and only applies plans accepted by the server', async () => {
  const job = normalizeJob({id: 'job', edit_plan: {render_version: 2, segments: [{source_start: 0, source_end: 2}]}});
  const api = new EditorApi('jobs');
  vi.spyOn(api, 'log').mockResolvedValue('<script>not HTML</script>\nPlan complete');
  const apply = vi.spyOn(api, 'importPlan').mockRejectedValueOnce(new Error('Plan exceeds max_duration')).mockResolvedValue(job);
  const onImport = vi.fn();
  render(<JobDetails api={api} job={job} disabled={false} maxDuration={30} onImport={onImport} onRefresh={vi.fn()} />);
  await userEvent.click(screen.getByText('Job log', {selector: 'summary'}));
  await waitFor(() => expect(screen.getByRole('log')).toHaveTextContent('<script>not HTML</script>'));
  await userEvent.click(screen.getByText('Raw plan JSON'));
  fireEvent.change(screen.getByLabelText('Plan JSON'), {target: {value: JSON.stringify(job.plan)}});
  await userEvent.click(screen.getByRole('button', {name: 'Validate & apply JSON'}));
  expect(await screen.findByRole('alert')).toHaveTextContent('Plan exceeds max_duration');
  expect(onImport).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', {name: 'Validate & apply JSON'}));
  await waitFor(() => expect(onImport).toHaveBeenCalledWith(job));
  expect(apply).toHaveBeenLastCalledWith('job', job.plan, 30);
});

it('validates import over PUT and does not turn duration or instruction edits into stale custom plans', async () => {
  const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => ({id: 'job',
    planning_settings: {max_duration: 60, editing_instructions: '', mode: 'nice', style: 'hype_montage'}})});
  vi.stubGlobal('fetch', fetcher);
  const api = new EditorApi('jobs');
  const plan = {render_version: 2, segments: [{source_start: 0, source_end: 2}]};
  await api.importPlan('job', plan, 30);
  expect(fetcher.mock.calls[0][1].method).toBe('PUT');
  expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({edit_plan: plan, max_duration: 30});
  await api.get('job');
  await api.render('job', 'landscape', {...options, max_duration: 30, editing_instructions: 'Quiet'}, [], plan);
  expect(JSON.parse(fetcher.mock.lastCall![1].body)).not.toHaveProperty('edit_plan');
});
