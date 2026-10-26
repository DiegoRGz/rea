// Proceso principal de ReelForge Studio: pantalla de carga, instalación guiada
// del entorno Python, arranque del motor local y ventanas de la aplicación.
const { app, BrowserWindow, dialog, ipcMain, session, shell } = require("electron");
const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const setup = require("./setup");

const ROOT = app.isPackaged ? process.resourcesPath : path.join(__dirname, "..");
const BACKEND = path.join(ROOT, "backend");
const UI = path.join(ROOT, "ui");
const DATA = process.env.REELFORGE_DATA || path.join(app.getPath("documents"), "ReelForge");
const LOGS = path.join(DATA, "logs");
const FLOW_URL = "https://labs.google/fx/tools/flow";
const TOKEN = crypto.randomBytes(18).toString("base64url");

let splash = null;
let mainWin = null;
let flowWin = null;
let engine = null;
let engineUrl = null;
let quitting = false;

if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => {
  const w = mainWin || splash;
  if (w) {
    if (w.isMinimized()) w.restore();
    w.focus();
  }
});

function status(text, progress) {
  splash?.webContents.send("splash:status", { text, progress });
}

function createSplash() {
  splash = new BrowserWindow({
    width: 640,
    height: 420,
    frame: false,
    transparent: true,
    resizable: false,
    center: true,
    show: false,
    backgroundColor: "#00000000",
    webPreferences: { preload: path.join(__dirname, "splash-preload.js"), contextIsolation: true, sandbox: true },
  });
  splash.loadFile(path.join(__dirname, "splash.html"));
  splash.once("ready-to-show", () => splash.show());
  splash.on("closed", () => (splash = null));
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

async function startEngine(python) {
  fs.mkdirSync(LOGS, { recursive: true });
  const port = await freePort();
  const log = fs.createWriteStream(path.join(LOGS, "engine.log"), { flags: "w" });
  const { spawn } = require("node:child_process");
  engine = spawn(python, ["-m", "reelforge", "--port", String(port)], {
    cwd: BACKEND,
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONPATH: BACKEND,
      PYTHONUNBUFFERED: "1",
      PYTHONUTF8: "1",
      REELFORGE_TOKEN: TOKEN,
      REELFORGE_UI: UI,
      REELFORGE_DATA: DATA,
    },
  });
  const tail = [];
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`El motor no respondió a tiempo.\n${tail.join("")}`)), 180000);
    const onData = (chunk) => {
      const text = chunk.toString();
      log.write(text);
      tail.push(text);
      if (tail.length > 40) tail.shift();
      const m = text.match(/REELFORGE_READY (\S+)/);
      if (m) {
        clearTimeout(timer);
        engineUrl = m[1];
        resolve(engineUrl);
      }
    };
    engine.stdout.on("data", onData);
    engine.stderr.on("data", onData);
    engine.on("exit", (code) => {
      clearTimeout(timer);
      log.end();
      if (!quitting) {
        if (!engineUrl) reject(new Error(`El motor se cerró (código ${code}).\n${tail.join("")}`));
        else engineCrashed(code, tail.join(""));
      }
    });
  });
}

function engineCrashed(code, details) {
  engineUrl = null;
  const choice = dialog.showMessageBoxSync(mainWin, {
    type: "error",
    title: "ReelForge Studio",
    message: `El motor de IA se detuvo (código ${code}).`,
    detail: `${details.slice(-1500)}\n\nRegistro: ${path.join(LOGS, "engine.log")}`,
    buttons: ["Reiniciar motor", "Salir"],
    defaultId: 0,
  });
  if (choice === 1) return app.quit();
  setup.findEnvPython(app, BACKEND).then(async (py) => {
    const url = await startEngine(py);
    mainWin?.loadURL(url);
  });
}

function stopEngine() {
  if (!engine || engine.exitCode !== null) return;
  if (process.platform === "win32") {
    require("node:child_process").spawnSync("taskkill", ["/pid", String(engine.pid), "/T", "/F"], { windowsHide: true });
  } else engine.kill("SIGTERM");
}

function isLocal(url) {
  try {
    const u = new URL(url);
    return u.hostname === "127.0.0.1" && engineUrl && u.port === new URL(engineUrl).port;
  } catch {
    return false;
  }
}

function createMain(url) {
  mainWin = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 1180,
    minHeight: 720,
    frame: false,
    show: false,
    backgroundColor: "#09090d",
    title: "ReelForge Studio",
    webPreferences: { preload: path.join(__dirname, "preload.js"), contextIsolation: true, sandbox: true },
  });
  mainWin.webContents.setWindowOpenHandler(({ url: target }) => {
    if (/^https?:\/\//.test(target) && !isLocal(target)) shell.openExternal(target);
    return { action: "deny" };
  });
  mainWin.webContents.on("will-navigate", (e, target) => {
    if (!isLocal(target)) {
      e.preventDefault();
      if (/^https?:\/\//.test(target)) shell.openExternal(target);
    }
  });
  mainWin.loadURL(url);
  mainWin.once("ready-to-show", () => {
    status("¡Listo!", 1);
    splash?.webContents.send("splash:done");
    setTimeout(() => {
      mainWin.maximize();
      mainWin.show();
      splash?.close();
    }, 650);
  });
  mainWin.on("closed", () => {
    mainWin = null;
    flowWin?.close();
  });
}

function createFlowWindow() {
  if (flowWin) {
    flowWin.focus();
    return;
  }
  const ses = session.fromPartition("persist:googleflow");
  // Google rechaza el inicio de sesión desde agentes que se identifican como Electron.
  ses.setUserAgent(ses.getUserAgent().replace(/\sElectron\/\S+/, "").replace(/\sreelforge-studio\/\S+/i, ""));
  if (!ses.__reelforgeDownloads) {
    ses.__reelforgeDownloads = true;
    ses.on("will-download", (_e, item) => {
      const dir = path.join(DATA, "flow-downloads");
      fs.mkdirSync(dir, { recursive: true });
      const dest = path.join(dir, `${Date.now()}-${item.getFilename()}`);
      item.setSavePath(dest);
      item.once("done", async (_ev, state) => {
        if (state !== "completed" || !engineUrl) return;
        try {
          const base = new URL(engineUrl).origin;
          const res = await fetch(`${base}/api/media/import`, {
            method: "POST",
            headers: { "content-type": "application/json", "x-reelforge-token": TOKEN },
            body: JSON.stringify({ paths: [dest], source: "flow" }),
          });
          if (res.ok) mainWin?.webContents.send("flow-download", { name: item.getFilename() });
        } catch (err) {
          console.error("No se pudo importar la descarga de Flow", err);
        }
      });
    });
  }
  flowWin = new BrowserWindow({
    width: 1320,
    height: 880,
    title: "Google Flow — ReelForge Studio",
    backgroundColor: "#000000",
    autoHideMenuBar: true,
    webPreferences: { session: ses, contextIsolation: true, sandbox: true },
  });
  flowWin.webContents.setWindowOpenHandler(({ url }) => {
    // Las ventanas de inicio de sesión de Google se abren dentro de la misma sesión.
    if (/^https:\/\/([a-z0-9-]+\.)*(google|googleusercontent|gstatic)\.com\//.test(url) || url.startsWith("https://labs.google/")) {
      return { action: "allow", overrideBrowserWindowOptions: { webPreferences: { session: ses } } };
    }
    shell.openExternal(url);
    return { action: "deny" };
  });
  flowWin.loadURL(FLOW_URL);
  flowWin.on("closed", () => (flowWin = null));
}

// ----------------------------------------------------------------- IPC
ipcMain.handle("pick-files", async (_e, filters) => {
  const res = await dialog.showOpenDialog(mainWin, { properties: ["openFile", "multiSelections"], filters: filters || [] });
  return res.canceled ? [] : res.filePaths;
});
ipcMain.handle("show-item", (_e, p) => typeof p === "string" && shell.showItemInFolder(p));
ipcMain.handle("open-external", (_e, url) => typeof url === "string" && /^https?:\/\//.test(url) && shell.openExternal(url));
ipcMain.handle("open-flow", () => createFlowWindow());
ipcMain.on("win", (e, action) => {
  const w = BrowserWindow.fromWebContents(e.sender);
  if (!w) return;
  if (action === "min") w.minimize();
  else if (action === "max") (w.isMaximized() ? w.unmaximize() : w.maximize());
  else if (action === "close") w.close();
});

// -------------------------------------------------------------- arranque
async function boot() {
  createSplash();
  const minSplash = new Promise((r) => setTimeout(r, 2600));
  try {
    status("Comprobando el entorno…", 0.08);
    let python = await setup.findEnvPython(app, BACKEND);
    if (!python) {
      python = await setup.runInteractive({ app, splash, dataDir: DATA, backendDir: BACKEND, status });
      if (!python) return app.quit();
    }
    status("Iniciando el motor de IA…", 0.45);
    const url = await startEngine(python);
    status("Detectando GPU y cargando la interfaz…", 0.8);
    await minSplash;
    createMain(url);
  } catch (err) {
    dialog.showErrorBox("ReelForge Studio", `${err.message}\n\nRegistro: ${path.join(LOGS, "engine.log")}`);
    app.quit();
  }
}

app.whenReady().then(boot);
app.on("before-quit", () => {
  quitting = true;
  stopEngine();
});
app.on("window-all-closed", () => {
  quitting = true;
  stopEngine();
  app.quit();
});
