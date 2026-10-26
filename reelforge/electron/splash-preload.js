const { contextBridge, ipcRenderer } = require("electron");

const on = (channel) => (cb) => ipcRenderer.on(channel, (_e, data) => cb(data));

contextBridge.exposeInMainWorld("splash", {
  onStatus: on("splash:status"),
  onDone: on("splash:done"),
  onSetup: on("splash:setup"),
  onLog: on("splash:log"),
  onSetupError: on("splash:setup-error"),
  choose: (choice) => ipcRenderer.send("splash:choice", choice),
  openPython: () => ipcRenderer.send("splash:choice", { action: "open-python" }),
});
