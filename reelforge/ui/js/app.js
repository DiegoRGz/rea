// Arranque de la interfaz: navegación, barra de trabajos y estado de la GPU.
import { api, cancelJob, onJobs, startPolling } from "./api.js";
import { injectFonts } from "./captions.js";
import { refreshMeta, state } from "./state.js";
import { bridge, clear, h, icon, toast } from "./ui.js";

const NAV = [
  { id: "home", label: "Inicio", icon: "home", load: () => import("./pages/home.js") },
  { id: "auto", label: "Auto Reel", icon: "sparkles", load: () => import("./pages/autoreel.js") },
  { id: "editor", label: "Editor", icon: "film", load: () => import("./pages/editor.js") },
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
    if (on) indicator.style.transform = `translateY(${b.offsetTop - 12}px)`;
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
  onJobs((jobs) => {
    const now = Date.now() / 1000;
    const visible = jobs.filter((j) => j.status === "running" || j.status === "queued" || (j.finished && now - j.finished < 5 && !hiddenDone.has(j.id)));
    clear(
      dock,
      visible.slice(0, 4).map((j) => {
        const bar = h("div", { class: "progress" }, h("i", { style: { width: `${(j.status === "done" ? 1 : j.progress) * 100}%` } }));
        const head = h(
          "div",
          { class: "job-head" },
          j.status === "running" || j.status === "queued" ? h("div", { class: "spinner" }) : h("span", { style: { color: j.status === "done" ? "var(--ok)" : "var(--err)" } }, icon(j.status === "done" ? "check" : "alert", 15)),
          h("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, j.title),
          j.status === "running" || j.status === "queued"
            ? h("button", { class: "btn ghost icon sm", title: "Cancelar", onclick: () => cancelJob(j.id) }, icon("x", 14))
            : h("button", { class: "btn ghost icon sm", onclick: () => hiddenDone.add(j.id) }, icon("x", 14)),
        );
        return h("div", { class: "job" }, head, bar, h("div", { class: "job-msg", title: j.error || j.message }, j.error || `${Math.round(j.progress * 100)}% · ${j.message}`));
      }),
    );
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
  window.addEventListener("hashchange", route);
  route();
}

boot();
