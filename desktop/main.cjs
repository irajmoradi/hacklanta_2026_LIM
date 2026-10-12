const {app, BrowserWindow, Menu, Tray, nativeImage, ipcMain, dialog} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const {randomBytes} = require('node:crypto');
const {pathToFileURL} = require('node:url');
const rt = require('./runtime.cjs');
let editor, preferences, tray, backend, capture, python, runtime, data, config, env, base;
let quitting = false, busy = false;
const settingsURL = pathToFileURL(path.join(__dirname, 'settings.html')).href;
const report = error => dialog.showErrorBox('LIM Editor', error.message);
const script = () => path.join(runtime, 'sidecar.py');
async function credential(action, value) {
  return JSON.parse(await rt.run(python, [script(), 'credential'], {timeout: 60000}, JSON.stringify({action, value})));
}
function secureWindow(options) {
  const win = new BrowserWindow({...options, webPreferences: {nodeIntegration: false, contextIsolation: true, sandbox: true, ...(options.webPreferences || {})}});
  win.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
  win.webContents.on('will-navigate', (event, url) => {if (url !== settingsURL && (!base || new URL(url).origin !== base)) event.preventDefault();});
  win.webContents.session.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  return win;
}
function showSettings() {
  if (preferences && !preferences.isDestroyed()) return preferences.show();
  preferences = secureWindow({width: 570, height: 550, title: 'LIM Settings', webPreferences: {preload: path.join(__dirname, 'preload.cjs')}});
  preferences.loadURL(settingsURL);
}
function menu() {
  if (!tray) return;
  tray.setToolTip(`LIM Editor — capture ${capture ? 'on' : 'off'}`);
  tray.setContextMenu(Menu.buildFromTemplate([
    {label: 'Open editor', enabled: !!base, click: () => editor?.show()},
    {label: 'Settings', click: showSettings},
    {label: 'Auto-capture (uploads and analyzes new recordings)', type: 'checkbox', checked: !!capture, enabled: !!base && !busy, click: () => toggleCapture().catch(report)},
    {type: 'separator'}, {label: 'Quit', click: () => app.quit()}
  ]));
}
async function toggleCapture() {
  busy = true; menu();
  try {
    if (capture) {const child = capture; capture = null; await rt.stop(child); return;}
    if (!config.watch) throw Error('Choose a recordings folder in Settings first.');
    const state = path.join(data, 'capture.json');
    fs.writeFileSync(state, JSON.stringify({watch: config.watch, api: base, state: path.join(data, 'capture-state.json'), include_existing: false}));
    const captureEnv = {...env};
    delete captureEnv.GEMINI_API_KEY; delete captureEnv.GOOGLE_API_KEY;
    const task = rt.launch(python, script(), ['capture', '--config', state], captureEnv);
    capture = task.child;
    task.child.on('exit', () => {
      if (capture === task.child) {capture = null; menu(); if (!quitting) report(Error('Auto-capture stopped. Check the recordings folder and restart it from the tray.'));}
    });
    await task.started;
  } finally {busy = false; menu();}
}
async function startBackend(key) {
  env = rt.environment(runtime, data, config, key, randomBytes(32).toString('hex'));
  for (const binary of ['ffmpeg', 'ffprobe']) {
    try {await rt.run(binary, ['-version'], {env, timeout: 10000});}
    catch {throw Error(`${binary} was not found. Install ffmpeg on PATH or set its folder in Settings, then restart.`);}
  }
  const task = rt.launch(python, script(), ['server'], env, true);
  backend = task.child;
  backend.on('exit', () => {base = null; menu(); if (!quitting) {rt.stop(capture); capture = null; report(Error('Backend stopped. Restart LIM Editor.'));}});
  base = await task.started;
  editor = secureWindow({width: 1280, height: 850, title: 'LIM Editor'});
  await editor.webContents.session.cookies.set({url: base, name: 'lim-session', value: env.LIM_TOKEN, httpOnly: true, sameSite: 'strict'});
  editor.on('close', event => {if (!quitting) {event.preventDefault(); editor.hide();}});
  await editor.loadURL(base);
  menu();
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on('second-instance', () => (editor || preferences)?.show());
  app.on('window-all-closed', () => {});
  app.on('before-quit', event => {
    if (quitting) return;
    event.preventDefault(); quitting = true;
    Promise.all([rt.stop(capture), rt.stop(backend)]).finally(() => app.quit());
  });
  app.whenReady().then(async () => {
    data = app.getPath('userData'); fs.mkdirSync(data, {recursive: true});
    runtime = app.isPackaged ? path.join(process.resourcesPath, 'runtime') : path.join(__dirname, 'stage');
    config = rt.settings();
    const file = path.join(data, 'settings.json');
    if (fs.existsSync(file)) {try {config = rt.settings(JSON.parse(fs.readFileSync(file)));} catch {report(Error('Saved settings are invalid. Defaults were loaded.'));}}
    // A tiny RGBA icon avoids platform-dependent SVG tray support.
    const pixels = Buffer.alloc(16 * 16 * 4);
    for (let i = 0; i < pixels.length; i += 4) {pixels[i] = 100; pixels[i + 1] = 190; pixels[i + 2] = 240; pixels[i + 3] = 255;}
    tray = new Tray(nativeImage.createFromBitmap(pixels, {width: 16, height: 16}));
    tray.on('double-click', () => (editor || preferences)?.show()); menu();
    function trusted(event) {
      if (!preferences || event.sender !== preferences.webContents || event.senderFrame !== preferences.webContents.mainFrame || event.senderFrame.url !== settingsURL) throw Error('Untrusted settings request');
    }
    ipcMain.handle('settings:read', event => {trusted(event); return config;});
    ipcMain.handle('settings:folder', async event => {
      trusted(event);
      const chosen = await dialog.showOpenDialog(preferences, {properties: ['openDirectory']});
      return chosen.canceled ? '' : chosen.filePaths[0];
    });
    ipcMain.handle('settings:save', async (event, value, key) => {
      trusted(event);
      const clean = rt.settings(value);
      if (typeof key !== 'string' || key.length > 4096) throw Error('Invalid API key');
      if (!python) throw Error('Python setup is still running or failed. Check Python installation and restart.');
      if (key) await credential('set', key);
      config = rt.saveSettings(file, clean);
      return 'Saved. Quit and reopen LIM Editor to apply settings.';
    });
    ipcMain.handle('settings:forget', async event => {trusted(event); await credential('set', ''); return 'Key removed. Quit and reopen to clear the running backend key.';});
    showSettings();
    try {
      python = await rt.preparePython(runtime, data);
      let key = '';
      try {key = await credential('get');} catch {report(Error('OS keychain unavailable. Unlock your native keychain (Linux: Secret Service). Keys cannot be saved until it is available.'));}
      await startBackend(key);
      preferences?.hide();
    } catch (error) {report(error); showSettings();}
  }).catch(report);
}
