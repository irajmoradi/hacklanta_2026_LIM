import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

test('parity settings, metadata, job log and validated JSON views', async ({page}, info) => {
  const sample = info.outputPath('synthetic.mp4');
  mkdirSync(dirname(sample), {recursive: true});
  execFileSync('ffmpeg', ['-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=10',
    '-t', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', sample]);
  const plan = {render_version: 2, fps: 30, segments: [{source_start: 0, source_end: 2, title: 'Round saved'}]};
  const job = {id: 'parity', status: 'planned', meta: {duration: 3, width: 320, height: 180, fps: 10,
    video_codec: 'h264', audio_codec: 'none'}, edit_plan: plan, clips: [{id: '0', start_seconds: 0, end_seconds: 2,
      caption: 'Round saved', score: .9}], planner_plan: {notes: ['70/30 mix limited by available labels.']}};
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/events')) return route.abort();
    if (path.startsWith('/api/log/')) return route.fulfill({contentType: 'text/plain', body: 'Upload complete\nAnalysis complete\nPlan validated\nNo live calls (fixture)'});
    if (path === '/api/info') return route.fulfill({json: {frontend_capabilities: {options: ['game', 'planner_v2', 'plan_refinement', 'gemini_image', 'share_kit', 'full_experience']}}});
    if (route.request().method() === 'PUT') {
      expect(route.request().postDataJSON()).toEqual({edit_plan: plan, max_duration: 60});
    }
    return route.fulfill({json: job});
  });
  await page.goto('/');
  await page.getByLabel('Upload gameplay').setInputFiles(sample);
  await expect(page.getByLabel('Source metadata')).toContainText('320 × 180');
  await page.getByLabel('Analysis instructions').fill('Find objective saves and clutch plays.');
  await page.getByLabel('Editing instructions', {exact: true}).fill('Start quietly, build to the final save.');
  await page.locator('.edit-settings').screenshot({path: info.outputPath('settings.png')});
  await page.getByText('Job log', {exact: true}).click();
  await expect(page.getByRole('log', {name: 'Job log output'})).toContainText('Plan validated');
  await page.locator('.job-details').screenshot({path: info.outputPath('job-log.png')});
  await page.getByText('Raw plan JSON', {exact: true}).click();
  await expect(page.getByRole('textbox', {name: 'Plan JSON', exact: true})).toHaveValue(JSON.stringify(plan, null, 2));
  await page.getByRole('button', {name: 'Validate & apply JSON'}).click();
  await page.locator('.job-details').screenshot({path: info.outputPath('plan-json.png')});
});
