const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("mintBridge", {
  onToggleMute: (cb) => ipcRenderer.on("toggle-mute", () => cb()),
  onVisibility: (cb) => ipcRenderer.on("visibility", (_e, visible) => cb(visible)),
  hide: () => ipcRenderer.send("hide"),
  quit: () => ipcRenderer.send("quit"),
});
