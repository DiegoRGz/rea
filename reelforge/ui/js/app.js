// Arranque de la interfaz: navegación, barra de trabajos y estado de la GPU.
import { api, cancelJob, onJobs, startPolling } from "./api.js";
import { injectFonts } from "./captions.js";
import { refreshMeta, state } from "./state.js";
import { bridge, clear, h, icon, toast } from "./ui.js";

const NAV = [
  { id: "home", label: "Inicio", icon: "home", load: () => import("./pages/home.js") },
  { id: "auto", label: "Auto Reel", icon: "sparkles", load: () => import("./pages/autoreel.js") },
  { id: "editor", label: "Editor", icon: "film", load: () => import("./pages/editor.js") },
  { id: "clips", label: "Clips", icon: "scissors", load: () => import("./pages/clips.js") },
  { id: "batch", label: "Lote", icon: "layers", load: () => import("./pages/batch.js") },
  { id: "voice", label: "Voz IA", icon: "mic", load: () => import("./pages/voice.js") },
  { id: "captions", label: "Subtítulos", icon: "captions", load: () => import("./pages/subtitles.js") },
  { id: "generate", label: "Generar", icon: "wand", load: () => import("./pages/generate.js") },
  { id: "flow", label: "Google", icon: "cloud", load: () => import("./pages/flow.js") },
  { id: "exports", label: "Exportados", icon: "download", load: () => import("./pages/exports.js") },
  { id: "models", label: "Modelos", icon: "box", load: () => import("./pages/models.js"), bottom: true },
  { id: "settings", label: "Ajustes", icon: "settings", load: () => import("./pages/settings.js"), bottom: true },
];

const main = document.getElementById("main");
const sidebar = document.getElementById("sidebar");
let current = null;

function buildSidebar() {
  const indicator = h("div", { class: "nav-indicator" });
  sidebar.append(indicator);
  for (const item of NAV.filter((n) => !n.bottom)) sidebar.append(navButton(item));
  sidebar.append(h("div", { class: "grow" }));
  for (const item of NAV.filter((n) => n.bottom)) sidebar.append(navButton(item));
}

function navButton(item) {
  return h("button", { class: "nav-item", dataset: { id: item.id }, title: item.label, onclick: () => go(item.id) }, icon(item.icon, 20), item.label);
}

function markNav(id) {
  const indicator = sidebar.querySelector(".nav-indicator");
  sidebar.querySelectorAll(".nav-item").forEach((b) => {
    const on = b.dataset.id === id;
    b.classList.toggle("active", on);
    if (!on) return;
    // Primera colocación sin animación; después se desliza sin rebote.
    if (!indicator.dataset.ready) indicator.style.transition = "none";
    indicator.style.top = `${b.offsetTop}px`;
    indicator.style.height = `${b.offsetHeight}px`;
    indicator.style.transform = "none";
    if (!indicator.dataset.ready) {
      void indicator.offsetHeight;
      indicator.style.transition = "";
      indicator.dataset.ready = "1";
    }
  });
}

export function go(id, arg) {
  location.hash = arg ? `#/${id}/${arg}` : `#/${id}`;
}

async function route() {
  const [, id = "home", arg] = location.hash.split("/");
  const item = NAV.find((n) => n.id === id) || NAV[0];
  markNav(item.id);
  if (current?.destroy) current.destroy();
  const view = h("div", { class: "view" });
  clear(main, view);
  try {
    const mod = await item.load();
    current = await mod.render(view, arg ? decodeURIComponent(arg) : undefined);
  } catch (e) {
    console.error(e);
    view.append(h("div", { class: "empty" }, `No se pudo abrir la página: ${e.message}`));
  }
}

function jobDock() {
  const dock = document.getElementById("jobdock");
  const hiddenDone = new Set();
  const cards = new Map(); // id -> {el, parts}: se actualizan en el sitio para no re-animarse
  const active = (j) => j.status === "running" || j.status === "queued";

  const build = (j) => {
    const status = h("span", { class: "job-status" });
    const close = h("button", { class: "btn ghost icon sm" }, icon("x", 14));
    close.onclick = () => (active(j) ? cancelJob(j.id) : (hiddenDone.add(j.id), remove(j.id)));
    const fill = h("i");
    const msg = h("div", { class: "job-msg" });
    const el = h("div", { class: "job" },
      h("div", { class: "job-head" }, status, h("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, j.title), close),
      h("div", { class: "progress" }, fill),
      msg);
    return { el, status, close, fill, msg, state: null, job: j };
  };

  const update = (c, j) => {
    c.job = j;
    if (c.state !== j.status) {
      c.state = j.status;
      clear(c.status, active(j) ? h("div", { class: "spinner" }) : h("span", { style: { color: j.status === "done" ? "var(--ok)" : "var(--err)" } }, icon(j.status === "done" ? "check" : "alert", 15)));
      c.close.title = active(j) ? "Cancelar" : "Cerrar";
    }
    c.fill.style.width = `${(j.status === "done" ? 1 : j.progress) * 100}%`;
    const text = j.error || `${Math.round(j.progress * 100)}% · ${j.message}`;
    if (c.msg.textContent !== text) {
      c.msg.textContent = text;
      c.msg.title = text;
    }
  };

  const remove = (id) => {
    const c = cards.get(id);
    if (!c) return;
    cards.delete(id);
    c.el.classList.add("out");
    setTimeout(() => c.el.remove(), 300);
  };

  onJobs((jobs) => {
    const now = Date.now() / 1000;
    const visible = jobs.filter((j) => active(j) || (j.finished && now - j.finished < (j.status === "error" ? 20 : 5) && !hiddenDone.has(j.id))).slice(0, 4);
    const ids = new Set(visible.map((j) => j.id));
    for (const id of [...cards.keys()]) if (!ids.has(id)) remove(id);
    for (const j of visible) {
      let c = cards.get(j.id);
      if (!c) {
        c = build(j);
        cards.set(j.id, c);
        dock.append(c.el);
      }
      update(c, j);
    }
  });
}

async function gpuPill() {
  const pill = document.getElementById("gpu-pill");
  const update = async () => {
    try {
      state.system = await api.get("/api/system");
      const g = state.system.gpu;
      const t = state.system.torch;
      const label = g ? `${g.name.replace("NVIDIA GeForce ", "")} · ${(g.vram_used_mb / 1024).toFixed(1)}/${(g.vram_total_mb / 1024).toFixed(0)} GB` : t.cuda ? t.device : "Sin GPU CUDA";
      clear(pill, h("span", { class: `badge ${g || t.cuda ? "ok" : "warn"}` }, h("span", { class: "dot" }), label));
    } catch {
      /* el motor puede estar ocupado */
    }
  };
  await update();
  setInterval(update, 5000);
}

function windowControls() {
  const root = document.getElementById("win-controls");
  if (!bridge.window) return;
  root.append(
    h("button", { title: "Minimizar", onclick: () => bridge.window.minimize() }, icon("minus", 14)),
    h("button", { title: "Maximizar", onclick: () => bridge.window.maximize() }, icon("square", 12)),
    h("button", { class: "close", title: "Cerrar", onclick: () => bridge.window.close() }, icon("x", 15)),
  );
}

async function boot() {
  buildSidebar();
  windowControls();
  try {
    await refreshMeta();
  } catch (e) {
    clear(main, h("div", { class: "view" }, h("div", { class: "empty" }, `No se pudo conectar con el motor: ${e.message}`)));
    return;
  }
  injectFonts();
  startPolling();
  jobDock();
  gpuPill();
  bridge.onFlowDownload?.((info) => toast(`Importado desde Google Flow: ${info.name}`, "ok"));
  setTimeout(() => import("./updates.js").then((m) => m.checkInBackground()), 4000);
  window.addEventListener("hashchange", route);
  route();
}

boot();
