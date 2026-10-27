// Instalación guiada del entorno local (se muestra el plan y se pide aprobación
// antes de escribir nada). No instala Python, drivers ni otro software del
// sistema: sólo crea un entorno virtual propio y descarga FFmpeg/fuentes en la
// carpeta de datos de ReelForge.
const { ipcMain } = require("electron");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const WIN = process.platform === "win32";
const FFMPEG_ZIP = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip";
const TORCH_CUDA = "https://download.pytorch.org/whl/cu128"; // RTX serie 50 (Blackwell) requiere CUDA 12.8+
const TORCH_CPU = "https://download.pytorch.org/whl/cpu";
const FONTS = {
  "Poppins-Black.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Black.ttf",
  "Poppins-ExtraBold.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-ExtraBold.ttf",
  "Anton-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
  "Bangers-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf",
  "BebasNeue-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf",
  "ArchivoBlack-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
  "NotoColorEmoji.ttf": "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji.ttf",
};

const envDir = (app) => path.join(app.getPath("userData"), "python-env");
const envPython = (dir) => (WIN ? path.join(dir, "Scripts", "python.exe") : path.join(dir, "bin", "python"));

function works(python) {
  if (!python || !fs.existsSync(python)) return false;
  // Margen amplio: el primer arranque tras reiniciar Windows (o con el antivirus escaneando) es lento.
  const r = spawnSync(python, ["-c", "import fastapi, uvicorn, pydantic, httpx"], { windowsHide: true, timeout: 180000 });
  return r.status === 0;
}

async function findEnvPython(app, backendDir) {
  const candidates = [process.env.REELFORGE_PYTHON, envPython(envDir(app))];
  if (backendDir) candidates.push(envPython(path.join(backendDir, ".venv")));
  return candidates.find((p) => works(p)) || null;
}

function findBasePython() {
  const tries = WIN
    ? [["py", ["-3.12"]], ["py", ["-3.11"]], ["py", ["-3.10"]], ["python", []]]
    : [["python3.12", []], ["python3.11", []], ["python3.10", []], ["python3", []]];
  for (const [cmd, pre] of tries) {
    const r = spawnSync(cmd, [...pre, "-c", "import sys;print(sys.executable);print('%d.%d' % sys.version_info[:2])"], { windowsHide: true, encoding: "utf8", timeout: 20000 });
    if (r.status !== 0 || !r.stdout) continue;
    const [exe, version] = r.stdout.trim().split(/\r?\n/);
    const [maj, min] = version.split(".").map(Number);
    if (maj === 3 && min >= 10 && min <= 12) return { exe, version };
  }
  return null;
}

function hasNvidia() {
  const r = spawnSync("nvidia-smi", ["--query-gpu=name,memory.total", "--format=csv,noheader"], { windowsHide: true, encoding: "utf8", timeout: 10000 });
  return r.status === 0 && r.stdout.trim() ? r.stdout.trim().split(/\r?\n/)[0] : null;
}

function ffmpegFound(dataDir) {
  if (fs.existsSync(path.join(dataDir, "ffmpeg", "bin", WIN ? "ffmpeg.exe" : "ffmpeg"))) return true;
  return spawnSync(WIN ? "where" : "which", ["ffmpeg"], { windowsHide: true }).status === 0;
}

function plan(app, dataDir) {
  const base = findBasePython();
  const gpu = hasNvidia();
  const ffmpeg = ffmpegFound(dataDir);
  return {
    python: base,
    gpu,
    ffmpeg,
    envDir: envDir(app),
    dataDir,
    canDownloadFfmpeg: WIN,
    steps: [
      `Crear un entorno Python aislado en ${envDir(app)}`,
      gpu ? `Instalar PyTorch con CUDA 12.8 para ${gpu} (~3 GB)` : "Instalar PyTorch para CPU (~250 MB)",
      "Instalar el motor de ReelForge (FastAPI, Edge TTS, Google GenAI…)",
      "Opcional: paquetes de IA local (diffusers, transformers, faster-whisper, Kokoro ~2 GB)",
      ffmpeg ? "FFmpeg ya está instalado ✓" : WIN ? `Opcional: descargar FFmpeg en ${path.join(dataDir, "ffmpeg")}` : "Instala FFmpeg con tu gestor de paquetes",
      `Opcional: descargar fuentes OFL para subtítulos en ${path.join(dataDir, "fonts")}`,
    ],
  };
}

function run(cmd, args, onLine) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { windowsHide: true, env: { ...process.env, PYTHONUTF8: "1", PIP_DISABLE_PIP_VERSION_CHECK: "1" } });
    const feed = (chunk) => chunk.toString().split(/\r|\n/).filter((l) => l.trim()).forEach(onLine);
    child.stdout.on("data", feed);
    child.stderr.on("data", feed);
    child.on("error", reject);
    child.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${path.basename(cmd)} terminó con código ${code}`))));
  });
}

async function download(url, dest, onProgress) {
  const res = await fetch(url, { redirect: "follow" });
  if (!res.ok) throw new Error(`Descarga fallida (${res.status}): ${url}`);
  const total = Number(res.headers.get("content-length")) || 0;
  const out = fs.createWriteStream(dest);
  let got = 0;
  const reader = res.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    got += value.length;
    if (!out.write(Buffer.from(value))) await new Promise((r) => out.once("drain", r));
    if (total) onProgress?.(got / total);
  }
  await new Promise((r) => out.end(r));
}

async function installFfmpeg(dataDir, log, progress) {
  const target = path.join(dataDir, "ffmpeg");
  const tmp = path.join(dataDir, "ffmpeg-download");
  fs.mkdirSync(tmp, { recursive: true });
  const zip = path.join(tmp, "ffmpeg.zip");
  log(`Descargando ${FFMPEG_ZIP}`);
  await download(FFMPEG_ZIP, zip, progress);
  log("Descomprimiendo FFmpeg…");
  await run("powershell", ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", `Expand-Archive -LiteralPath '${zip}' -DestinationPath '${tmp}' -Force`], log);
  const folder = fs.readdirSync(tmp).find((n) => n.startsWith("ffmpeg-") && fs.statSync(path.join(tmp, n)).isDirectory());
  if (!folder) throw new Error("El ZIP de FFmpeg no tiene el formato esperado");
  fs.rmSync(target, { recursive: true, force: true });
  fs.renameSync(path.join(tmp, folder), target);
  fs.rmSync(tmp, { recursive: true, force: true });
  log(`FFmpeg instalado en ${target}`);
}

async function installFonts(dataDir, log) {
  const dir = path.join(dataDir, "fonts");
  fs.mkdirSync(dir, { recursive: true });
  for (const [name, url] of Object.entries(FONTS)) {
    const dest = path.join(dir, name);
    if (fs.existsSync(dest)) continue;
    log(`Fuente ${name}`);
    await download(url, dest);
  }
}

/** Muestra el plan en la pantalla de carga, espera aprobación y lo ejecuta. */
async function runInteractive({ app, splash, dataDir, backendDir, status }) {
  splash.setSize(680, 620);
  splash.center();
  for (;;) {
    const p = plan(app, dataDir);
    splash.webContents.send("splash:setup", p);
    const choice = await new Promise((resolve) => ipcMain.once("splash:choice", (_e, c) => resolve(c)));
    if (!choice || choice.action === "quit") return null;
    if (choice.action === "retry") continue;
    if (choice.action === "open-python") {
      require("electron").shell.openExternal("https://www.python.org/downloads/windows/");
      continue;
    }
    if (!p.python) continue;
    const log = (line) => splash.webContents.send("splash:log", line);
    const step = (i, n, text) => status(text, 0.08 + (0.34 * i) / n);
    const total = 4 + (choice.ai ? 1 : 0) + (choice.ffmpeg ? 1 : 0) + (choice.fonts ? 1 : 0);
    let i = 0;
    try {
      const dir = envDir(app);
      const py = envPython(dir);
      step(i++, total, "Creando entorno Python…");
      if (!fs.existsSync(py)) await run(p.python.exe, ["-m", "venv", dir], log);
      step(i++, total, "Actualizando pip…");
      await run(py, ["-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"], log);
      step(i++, total, p.gpu ? "Instalando PyTorch con CUDA (puede tardar)…" : "Instalando PyTorch…");
      await run(py, ["-m", "pip", "install", "torch", "--index-url", p.gpu ? TORCH_CUDA : TORCH_CPU], log);
      step(i++, total, "Instalando el motor de ReelForge…");
      await run(py, ["-m", "pip", "install", "-r", path.join(backendDir, "requirements.txt")], log);
      if (choice.ai) {
        step(i++, total, "Instalando paquetes de IA local…");
        await run(py, ["-m", "pip", "install", "-r", path.join(backendDir, "requirements-ai.txt")], log);
      }
      if (choice.ffmpeg) {
        step(i++, total, "Descargando FFmpeg…");
        await installFfmpeg(dataDir, log, (f) => status(`Descargando FFmpeg… ${Math.round(f * 100)}%`, 0.08 + (0.34 * (i - 1 + f)) / total));
      }
      if (choice.fonts) {
        step(i++, total, "Descargando fuentes…");
        await installFonts(dataDir, log).catch((e) => log(`Aviso: ${e.message}`));
      }
      if (works(py)) return py;
      throw new Error("El entorno no quedó operativo");
    } catch (err) {
      log(`ERROR: ${err.message}`);
      splash.webContents.send("splash:setup-error", err.message);
      const again = await new Promise((resolve) => ipcMain.once("splash:choice", (_e, c) => resolve(c)));
      if (!again || again.action === "quit") return null;
    }
  }
}

module.exports = { findEnvPython, runInteractive };
