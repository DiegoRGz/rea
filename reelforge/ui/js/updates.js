// Actualizaciones desde la propia app (sin recompilar ni reinstalar).
import { api, runJob } from "./api.js";
import { bridge, btn, clear, h, icon, modal, progressBar, toast } from "./ui.js";

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("es", { dateStyle: "medium", timeStyle: "short" }) : "desconocida");

/** Comprueba en segundo plano y muestra un aviso en la barra de título si hay versión nueva. */
export async function checkInBackground() {
  try {
    const info = await api.get("/api/update/check");
    if (!info.available && !info.pending_restart) return;
    const slot = document.getElementById("update-pill");
    clear(slot, h("button", { class: "btn primary sm", style: { height: "26px", WebkitAppRegion: "no-drag" }, onclick: () => openUpdateDialog() },
      icon(info.pending_restart ? "refresh" : "download", 13), info.pending_restart ? "Reiniciar para actualizar" : "Actualización disponible"));
  } catch {
    /* sin conexión: se ignora */
  }
}

export async function openUpdateDialog() {
  const body = h("div", { class: "col", style: { gap: "14px" } }, h("div", { class: "row muted" }, h("div", { class: "spinner" }), "Comprobando…"));
  const action = btn("Actualizar ahora", { cls: "primary", icon: "download" });
  action.disabled = true;
  const m = modal({ title: "Actualizaciones", body, actions: [action], width: 520 });
  let info;
  try {
    info = await api.get("/api/update/check");
  } catch (e) {
    clear(body, h("div", { class: "notice" }, icon("alert", 16), e.message));
    return;
  }
  const restart = () => (bridge.restart ? bridge.restart() : toast("Reinicia el motor para usar la versión nueva", "info"));
  clear(body,
    h("div", { class: "kv" },
      h("span", {}, "Tu versión"), h("span", {}, info.current.sha ? `${info.current.sha.slice(0, 7)} · ${fmtDate(info.current.date)}` : "instalación inicial"),
      h("span", {}, "Última versión"), h("span", {}, `${info.latest.sha.slice(0, 7)} · ${fmtDate(info.latest.date)}`)),
    h("div", { class: "card", style: { padding: "12px", background: "var(--bg-2)" } }, h("div", { class: "label" }, "Último cambio"), h("div", { class: "small" }, info.latest.message)),
    info.available
      ? h("div", { class: "notice info" }, icon("info", 16), h("div", {}, "Se descarga la versión nueva (~25 MB) y sólo las dependencias que falten. Tus proyectos, modelos y ajustes no se tocan. Si la versión nueva fallara al arrancar, la app vuelve sola a la anterior."))
      : info.pending_restart
        ? h("div", { class: "notice info" }, icon("refresh", 16), "La actualización ya está descargada: reinicia para usarla.")
        : h("div", { class: "notice info" }, icon("check", 16), "Ya tienes la última versión."),
  );
  if (info.pending_restart && !info.available) {
    action.replaceChildren(icon("refresh", 16), h("span", {}, "Reiniciar ahora"));
    action.disabled = false;
    action.onclick = restart;
    return;
  }
  if (!info.available) return action.remove();
  action.disabled = false;
  action.onclick = async () => {
    const bar = progressBar(0);
    const msg = h("div", { class: "muted small" }, "Iniciando…");
    body.append(bar, msg);
    action.classList.add("loading");
    try {
      await runJob(api.post("/api/update/apply"), (j) => { bar.set(j.progress); msg.textContent = j.message; });
      action.classList.remove("loading");
      msg.textContent = "¡Actualización instalada!";
      action.replaceChildren(icon("refresh", 16), h("span", {}, "Reiniciar ahora"));
      action.onclick = restart;
    } catch (e) {
      action.classList.remove("loading");
      msg.textContent = e.message;
      toast(e.message, "err", 9000);
    }
  };
  return m;
}
