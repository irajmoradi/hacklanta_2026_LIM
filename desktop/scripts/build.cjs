const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const desktop = path.resolve(__dirname, '..');
const source = path.resolve(desktop, '../full_app');
const stage = path.join(desktop, 'stage');
function run(exe, args, cwd) {
  // npm's JS entry point avoids cmd.exe argument quoting on Windows.
  const result = spawnSync(exe, args, {cwd, stdio: 'inherit', shell: false});
  if (result.error) throw result.error;
  if (result.status !== 0) throw Error(`${exe} exited ${result.status}`);
}
function copyCode(from, to) {
  fs.mkdirSync(to, {recursive: true});
  for (const entry of fs.readdirSync(from, {withFileTypes: true})) {
    if (entry.isSymbolicLink() || ['tests', '__pycache__', 'workspace', 'node_modules', '.venv', 'reaction_packs', 'production_frontend', 'frontend', 'sfx'].includes(entry.name)) continue;
    const src = path.join(from, entry.name), dst = path.join(to, entry.name);
    if (entry.isDirectory()) copyCode(src, dst);
    else if (/\.(py|json)$/.test(entry.name) || (entry.name.endsWith('.txt') && (from.includes(`${path.sep}prompts`) || entry.name === 'requirements.txt'))) fs.copyFileSync(src, dst);
  }
}
function main() {
  const dry = process.argv.includes('--dry-run');
  // Dry run still materializes and builds all application resources.
  fs.rmSync(stage, {recursive: true, force: true});
  copyCode(source, path.join(stage, 'full_app'));
  if (fs.existsSync(path.join(source, 'sfx'))) fs.cpSync(path.join(source, 'sfx'), path.join(stage, 'full_app/sfx'), {recursive: true, filter: p => fs.statSync(p).isDirectory() || /\.(mp3|wav|ogg|json|txt)$/i.test(p)});
  for (const [from, to] of [['sidecar.py', 'sidecar.py'], ['requirements.txt', 'desktop-requirements.txt']]) fs.copyFileSync(path.join(desktop, from), path.join(stage, to));
  const frontend = path.join(stage, 'frontend-source');
  fs.cpSync(path.join(source, 'production_frontend'), frontend, {recursive: true, filter: p => !['node_modules', 'dist', '.env', '.git'].includes(path.basename(p)) && !path.basename(p).startsWith('.env.')});
  const npm = process.env.npm_execpath;
  if (!npm) throw Error('Run using npm run stage/build/build:dry');
  run(process.execPath, [npm, 'ci'], frontend);
  run(process.execPath, [npm, 'run', 'build'], frontend);
  fs.renameSync(path.join(frontend, 'dist'), path.join(stage, 'frontend'));
  fs.rmSync(frontend, {recursive: true, force: true});
  if (process.env.LIM_FFMPEG_DIR) {
    fs.mkdirSync(path.join(stage, 'bin'), {recursive: true});
    for (const name of ['ffmpeg', 'ffprobe']) {
      const file = name + (process.platform === 'win32' ? '.exe' : '');
      fs.copyFileSync(path.join(process.env.LIM_FFMPEG_DIR, file), path.join(stage, 'bin', file));
      fs.chmodSync(path.join(stage, 'bin', file), 0o755);
    }
  }
  if (!fs.existsSync(path.join(stage, 'frontend/index.html'))) throw Error('Frontend missing');
  if (!process.argv.includes('--stage-only')) run(process.execPath, [require.resolve('electron-builder/cli.js'), ...(dry ? ['--dir'] : [])], desktop);
}
if (require.main === module) main();
module.exports = {copyCode};
