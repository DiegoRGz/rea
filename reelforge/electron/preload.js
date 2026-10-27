// Puente seguro entre la interfaz (servida por el motor local) y Electron.
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("reelforge", {
  isElectron: true,
  pickFiles: (filters) => ipcRenderer.invoke("pick-files", filters),
  showItemInFolder: (p) => ipcRenderer.invoke("show-item", p),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  openFlow: () => ipcRenderer.invoke("open-flow"),
  restart: () => ipcRenderer.invoke("app-restart"),
  window: {
    minimize: () => ipcRenderer.send("win", "min"),
    maximize: () => ipcRenderer.send("win", "max"),
    close: () => ipcRenderer.send("win", "close"),
  },
  onFlowDownload: (cb) => {
    const listener = (_e, info) => cb(info);
    ipcRenderer.on("flow-download", listener);
    return () => ipcRenderer.removeListener("flow-download", listener);
  },
});
