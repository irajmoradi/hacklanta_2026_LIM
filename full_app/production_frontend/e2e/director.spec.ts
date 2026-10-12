import { test, expect } from '@playwright/test';
test('Director streams a trim, renders its plan, and respects reduced motion', async ({page}, info) => {
  const original = {segments: [{clip_id: 'clutch', source_start: 8, source_end: 17, title: 'Round saved'}]};
  const plan = {segments: [{...original.segments[0], source_end: 13, speed: 1.2}]};
  let analyzed = false;
  let finish!: () => void;
  let renderBody: any;
  await page.addInitScript(() => {
    class MockEvents extends EventTarget {
      close() {}
      constructor(_url: string) { super(); (window as any).directorEvents = this; }
    }
    (window as any).EventSource = MockEvents;
  });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = {};
    if (path.endsWith('/agent')) {
      await new Promise<void>(resolve => {finish = resolve;});
      body = {plan, plan_version: 2, trace: []};
    } else if (path.endsWith('/render')) { renderBody = route.request().postDataJSON(); }
    else if (path.endsWith('/analyze')) analyzed = true;
    else if (path !== '/api/info') body = {id: 'one', duration: 60, status: analyzed ? 'analyzed' : 'uploaded', plan: original,
      clips: analyzed ? [{id: 'clutch', start: 8, end: 17, caption: 'Round saved', score: .9}] : []};
    await route.fulfill({json: body});
  });
  await page.goto('/');
  await page.getByLabel('Upload gameplay').setInputFiles({name: 'fixture.mp4', mimeType: 'video/mp4', buffer: Buffer.from('mock upload')});
  await page.getByRole('button', {name: /Find my moments/}).click();
  await page.getByRole('button', {name: 'More hype', exact: true}).click();
  await page.getByLabel('Editing instruction').press('Enter');
  await expect(page.getByText('Director is editing…')).toBeVisible();
  await page.evaluate(() => (window as any).directorEvents.dispatchEvent(new MessageEvent('agent_step', {data: JSON.stringify({
    step: 1, tool: 'trim_clip', args: {clip_id: 'clutch', segment_index: 0}, rationale: 'Cut the waiting; keep the winning shot.',
    diff: {before: {source_end: 17}, after: {source_end: 13}}
  })})));
  await expect(page.getByText('Cut the waiting; keep the winning shot.')).toBeVisible();
  await expect(page.locator('.clip-track:not(.montage-track) .agent-affected')).toHaveCount(1);
  await expect(page.getByLabel('Trim end 1')).toHaveValue('13');
  await page.getByRole('region', {name: 'Director', exact: true}).screenshot({path: info.outputPath('director-mid-trace.png')});
  await page.emulateMedia({reducedMotion: 'reduce'});
  expect(await page.locator('.clip-track button').first().evaluate(el => getComputedStyle(el).transitionDuration)).toBe('0s');
  finish();
  await expect(page.getByText('Plan v2')).toBeVisible();
  await page.getByRole('button', {name: 'Apply & render'}).click();
  await expect.poll(() => renderBody?.edit_plan?.segments[0]?.speed).toBe(1.2);
  expect(renderBody.edit_plan.segments[0].source_end).toBe(13);
});
