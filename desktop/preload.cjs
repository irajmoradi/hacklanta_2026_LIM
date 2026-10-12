const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('desktopSettings', {
  read: () => ipcRenderer.invoke('settings:read'),
  folder: () => ipcRenderer.invoke('settings:folder'),
  save: (value, key) => ipcRenderer.invoke('settings:save', value, key),
  forget: () => ipcRenderer.invoke('settings:forget')
});
