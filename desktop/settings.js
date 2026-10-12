const el = id => document.getElementById(id);
const api = window.desktopSettings;
async function action(fn) {try {await fn();} catch (e) {el('status').textContent = e.message;}}
action(async () => {const config = await api.read(); for (const key of ['watch', 'ffmpeg']) el(key).value = config[key]; el('vertex').checked = config.vertex;});
for (const [button, field] of [['chooseWatch', 'watch'], ['chooseFfmpeg', 'ffmpeg']]) el(button).onclick = () => action(async () => {const folder = await api.folder(); if (folder) el(field).value = folder;});
el('settings').onsubmit = event => {event.preventDefault(); action(async () => {
  el('status').textContent = await api.save({watch: el('watch').value, ffmpeg: el('ffmpeg').value, vertex: el('vertex').checked}, el('key').value);
  el('key').value = '';
});};
el('forget').onclick = () => action(async () => {el('status').textContent = await api.forget(); el('key').value = '';});
