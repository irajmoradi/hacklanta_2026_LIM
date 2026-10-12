const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const rt = require('../runtime.cjs');
const {copyCode} = require('../scripts/build.cjs');
test('settings reject secrets, invalid types and relative folders', () => {
  assert.deepEqual(rt.settings(), {watch: '', ffmpeg: '', vertex: false});
  for (const value of [null, [], {api_key: 'secret'}, {vertex: 'true'}, {watch: '.'}]) assert.throws(() => rt.settings(value));
});
test('settings persist only validated fields', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lim-test-'));
  try {
    const file = path.join(dir, 'settings.json');
    rt.saveSettings(file, {watch: dir, vertex: true});
    assert.equal(JSON.parse(fs.readFileSync(file)).watch, dir);
    assert.equal(fs.existsSync(file + '.tmp'), false);
  } finally {fs.rmSync(dir, {recursive: true});}
});
test('environment selects provider, isolates workspace and sets ffmpeg search path', () => {
  const before = process.env.GEMINI_API_KEY;
  process.env.GEMINI_API_KEY = 'inherited';
  try {
    const env = rt.environment('/runtime', '/data', {vertex: true, ffmpeg: '/ffmpeg'}, 'test-key', 'token');
    assert.equal(env.GEMINI_API_KEY, undefined);
    assert.equal(env.GOOGLE_API_KEY, 'test-key');
    assert.equal(env.GOOGLE_GENAI_USE_VERTEXAI, 'true');
    assert.equal(env.JOB_WORKSPACE, path.join('/data', 'workspace'));
    assert.equal(env.PATH.split(path.delimiter)[0], '/ffmpeg');
  } finally {if (before === undefined) delete process.env.GEMINI_API_KEY; else process.env.GEMINI_API_KEY = before;}
});
test('staging excludes environment, recordings and workspaces', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lim-stage-'));
  try {
    const src = path.join(dir, 'src'), dst = path.join(dir, 'dst');
    fs.mkdirSync(path.join(src, 'workspace'), {recursive: true});
    for (const name of ['app.py', '.env', 'recording.mp4', 'workspace/private.json']) fs.writeFileSync(path.join(src, name), 'test');
    copyCode(src, dst);
    assert.deepEqual(fs.readdirSync(dst), ['app.py']);
  } finally {fs.rmSync(dir, {recursive: true});}
});
test('launcher handles readiness, spaces and termination', async () => {
  const task = rt.launch(process.execPath, '-e', ['console.log(JSON.stringify({port: 12345}));setInterval(()=>{},1000)'], process.env, true);
  assert.equal(await task.started, 'http://127.0.0.1:12345');
  await rt.stop(task.child);
  assert.notEqual(task.child.signalCode, null);
});
test('launcher rejects spawn failure and malformed readiness', async () => {
  const missing = rt.launch('/missing/python', 'script', [], process.env, true);
  await assert.rejects(missing.started);
  const invalid = rt.launch(process.execPath, '-e', ['console.log("bad")'], process.env, true);
  await assert.rejects(invalid.started);
  await rt.stop(invalid.child);
});
test('command errors do not expose subprocess output', async () => {
  await assert.rejects(rt.run(process.execPath, ['-e', 'console.error("SECRET");process.exit(2)']), error => !error.message.includes('SECRET'));
});
