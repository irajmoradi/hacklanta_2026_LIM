const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {spawn} = require('node:child_process');

function settings(value = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value) ||
      Object.keys(value).some(k => !['watch', 'ffmpeg', 'vertex'].includes(k))) throw Error('Invalid settings');
  const result = {watch: '', ffmpeg: '', vertex: false, ...value};
  if (typeof result.watch !== 'string' || typeof result.ffmpeg !== 'string' || typeof result.vertex !== 'boolean') throw Error('Invalid settings');
  for (const k of ['watch', 'ffmpeg']) if (result[k] && (!path.isAbsolute(result[k]) || !fs.statSync(result[k]).isDirectory())) throw Error(`${k} must be an existing absolute directory`);
  return result;
}
function saveSettings(file, value) {
  const clean = settings(value);
  fs.writeFileSync(file + '.tmp', JSON.stringify(clean), {mode: 0o600});
  fs.renameSync(file + '.tmp', file);
  return clean;
}
function run(exe, args, options = {}, input = '') {
  return new Promise((resolve, reject) => {
    const child = spawn(exe, args, {...options, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']});
    let output = '';
    child.stdout.on('data', b => {output += b;});
    child.stderr.resume(); // Never persist provider/keychain output.
    child.on('error', reject);
    child.on('exit', code => code === 0 ? resolve(output) : reject(Error(`${path.basename(exe)} exited ${code}`)));
    child.stdin.on('error', () => {});
    child.stdin.end(input);
  });
}
async function preparePython(runtime, data) {
  const venv = path.join(data, 'python');
  const python = path.join(venv, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  const requirements = [path.join(runtime, 'full_app/requirements.txt'), path.join(runtime, 'full_app/capture/requirements.txt'), path.join(runtime, 'desktop-requirements.txt')];
  const digest = crypto.createHash('sha256').update(requirements.map(f => fs.readFileSync(f)).join('\n')).digest('hex');
  const marker = path.join(venv, '.requirements');
  if (!fs.existsSync(python)) await run(process.env.LIM_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-m', 'venv', venv]);
  if (!fs.existsSync(marker) || fs.readFileSync(marker, 'utf8') !== digest) {
    await run(python, ['-m', 'pip', 'install', ...requirements.flatMap(f => ['-r', f])]);
    fs.writeFileSync(marker, digest);
  }
  return python;
}
function environment(runtime, data, config, key, token) {
  const env = {...process.env, LIM_BACKEND: path.join(runtime, 'full_app'), LIM_FRONTEND: path.join(runtime, 'frontend'), JOB_WORKSPACE: path.join(data, 'workspace'), LIM_TOKEN: token, PYTHONUNBUFFERED: '1'};
  delete env.GEMINI_API_KEY; delete env.GOOGLE_API_KEY; delete env.PYTHONPATH; delete env.PYTHONHOME;
  env.GOOGLE_GENAI_USE_VERTEXAI = String(config.vertex);
  if (key) env[config.vertex ? 'GOOGLE_API_KEY' : 'GEMINI_API_KEY'] = key;
  env.PATH = [config.ffmpeg, path.join(runtime, 'bin'), env.PATH].filter(Boolean).join(path.delimiter);
  return env;
}
async function stop(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === 'win32') {
    await run('taskkill', ['/pid', String(child.pid), '/T', '/F']).catch(() => {});
  } else {
    try { process.kill(-child.pid, 'SIGTERM'); } catch {}
    await new Promise(resolve => {
      const timer = setTimeout(resolve, 2000);
      child.once('exit', () => {clearTimeout(timer); resolve();});
    });
    try { process.kill(-child.pid, 'SIGKILL'); } catch {}
  }
}
function launch(python, script, args, env, ready = false) {
  const child = spawn(python, [script, ...args], {env, windowsHide: true, detached: process.platform !== 'win32', stdio: ['pipe', 'pipe', 'pipe']});
  child.stderr.resume();
  const started = new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => {stop(child); reject(Error('Backend startup timed out'));}, 60000);
    function fail() {clearTimeout(timer); reject(Error('Sidecar failed to start'));}
    child.once('error', fail);
    child.once('exit', fail);
    child.once('spawn', () => {if (!ready) {clearTimeout(timer); resolve();}});
    child.stdout.on('data', b => {
      if (!ready) return;
      output += b;
      if (output.includes('\n')) {
        try {
          const {port} = JSON.parse(output.split('\n')[0]);
          if (!Number.isInteger(port) || port < 1 || port > 65535) throw Error();
          clearTimeout(timer); resolve(`http://127.0.0.1:${port}`);
        } catch {stop(child); fail();}
        ready = false;
      }
    });
  });
  return {child, started};
}
module.exports = {settings, saveSettings, run, preparePython, environment, stop, launch};
