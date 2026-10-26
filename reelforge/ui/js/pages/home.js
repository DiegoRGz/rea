import { api, fileUrl } from "../api.js";
import { go } from "../app.js";
import { state, importMedia } from "../state.js";
import { btn, clear, confirmDialog, fmtTime, h, icon, modal, segmented, field, timeAgo, toast } from "../ui.js";

export function newProjectDialog() {
  let aspect = "9:16";
  const name = h("input", { class: "input", value: "Nuevo reel" });
  const create = btn("Crear proyecto", { cls: "primary", icon: "plus" });
  const m = modal({
    title: "Nuevo proyecto",
    width: 460,
    body: h(
      "div",
      { class: "col", style: { gap: "16px" } },
      field("Nombre", name),
      field("Formato", segmented([["9:16", "9:16 Reel"], ["4:5", "4:5"], ["1:1", "1:1"], ["16:9", "16:9"]], aspect, (v) => (aspect = v))),
    ),
    actions: [create],
  });
  create.onclick = async () => {
    const p = await api.post("/api/projects", { name: name.value || "Nuevo reel", aspect });
    m.close();
    go("editor", p.id);
  };
  setTimeout(() => name.select(), 50);
}

export async function render(view) {
  const health = state.health;
  const hero = h(
    "section",
    { class: "hero" },
    h("div", { class: "blob b1" }),
    h("div", { class: "blob b2" }),
    h("div", { class: "blob b3" }),
    h(
      "div",
      { class: "hero-phone" },
      h("div", { class: "cap" }, "ESTO ES ", h("b", {}, "VIRAL")),
      h("div", { class: "bar" }, h("i")),
    ),
    h("div", { style: { position: "relative" } },
      h("span", { class: "badge accent" }, icon("cpu", 12), "IA 100% local · RTX + CUDA"),
      h("h1", { style: { marginTop: "14px" } }, "Crea reels ", h("span", { class: "grad-text" }, "virales"), " en minutos."),
      h("p", {}, "Guion, voz, imágenes, vídeo, subtítulos animados y montaje con transiciones. Todo en tu PC, sin suscripciones."),
      h("div", { class: "row" },
        btn("Reel automático", { cls: "primary lg", icon: "sparkles", onClick: () => go("auto") }),
        btn("Proyecto en blanco", { cls: "lg", icon: "plus", onClick: newProjectDialog }),
      ),
    ),
  );

  const quick = h(
    "div",
    { class: "grid g4 stagger", style: { marginTop: "18px" } },
    quickCard("layers", "Producción en lote", "Una lista de temas → muchos reels exportados.", () => go("batch")),
    quickCard("mic", "Voz y narración", "Voces naturales en español con Kokoro o Edge.", () => go("voice")),
    quickCard("captions", "Subtítulos automáticos", "Transcribe y añade subtítulos animados a tu vídeo.", () => go("captions")),
    quickCard("scissors", "Vídeo largo → clips", "Podcast o directo convertido en varios reels virales.", () => go("clips")),
  );

  const warnings = h("div", { class: "col", style: { marginTop: "16px" } });
  if (!health.ffmpeg.ffmpeg) warnings.append(notice("No se encontró FFmpeg. Ejecuta la configuración inicial o indica su ruta en Ajustes."));
  else if (!health.ffmpeg.libass) warnings.append(notice("Tu FFmpeg no incluye libass: los subtítulos no se podrán grabar en el vídeo."));
  if (!health.modules.torch) warnings.append(notice("PyTorch no está instalado: la IA local no estará disponible hasta completar la instalación (Modelos → Paquete de IA).", "info"));

  const projectsGrid = h("div", { class: "auto-grid stagger" });
  const sys = h("div", { class: "col" });
  view.append(
    hero,
    warnings,
    quick,
    h("div", { class: "grid", style: { gridTemplateColumns: "minmax(0,1fr) 320px", marginTop: "8px", gap: "22px" } },
      h("div", {}, h("div", { class: "section-title" }, "Proyectos recientes"), projectsGrid),
      h("div", {}, h("div", { class: "section-title" }, "Tu equipo"), sys),
    ),
  );

  const loadProjects = async () => {
    const list = await api.get("/api/projects");
    if (!list.length) {
      clear(projectsGrid, h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, "Aún no tienes proyectos. Empieza con un Reel automático ✨"));
      return;
    }
    clear(projectsGrid, list.map((p) => projectCard(p, loadProjects)));
  };
  loadProjects();
  systemCard(sys);
}

function quickCard(ic, title, text, onClick) {
  return h("div", { class: "card hover quick", onclick: onClick }, h("div", { class: "q-icon" }, icon(ic, 21)), h("h3", {}, title), h("p", {}, text));
}

function notice(text, kind = "") {
  return h("div", { class: `notice ${kind}` }, icon(kind === "info" ? "info" : "alert", 17), h("div", {}, text));
}

function projectCard(p, reload) {
  const thumbId = p.thumb ? p.thumb.replace(/\\/g, "/").split("/").slice(-2)[0] : null;
  const card = h(
    "div",
    { class: "card hover project-card", onclick: () => go("editor", p.id) },
    h("div", { class: "thumb", style: thumbId ? { backgroundImage: `url(${fileUrl.thumb(thumbId)})` } : {} }),
    h("div", { class: "info" }, h("b", {}, p.name), h("span", { class: "muted small" }, `${fmtTime(p.duration, false)} · ${p.clips} clips · ${timeAgo(p.updated)}`)),
  );
  const actions = h(
    "div",
    { class: "actions" },
    btn("", { icon: "copy", cls: "icon sm", title: "Duplicar", onClick: async (e) => { e.stopPropagation(); await api.post(`/api/projects/${p.id}/duplicate`); reload(); } }),
    btn("", {
      icon: "trash",
      cls: "icon sm danger",
      title: "Eliminar",
      onClick: async (e) => {
        e.stopPropagation();
        if (await confirmDialog("Eliminar proyecto", `¿Eliminar «${p.name}»? Los medios de la biblioteca se conservan.`, "Eliminar", true)) {
          await api.del(`/api/projects/${p.id}`);
          toast("Proyecto eliminado", "ok");
          reload();
        }
      },
    }),
  );
  card.append(actions);
  return card;
}

async function systemCard(root) {
  const s = state.system || (await api.get("/api/system"));
  const g = s.gpu;
  const t = s.torch;
  const vram = g ? g.vram_used_mb / g.vram_total_mb : 0;
  clear(
    root,
    h("div", { class: "card col" },
      h("div", { class: "row" }, h("div", { class: "q-icon", style: { width: "36px", height: "36px", borderRadius: "10px", display: "grid", placeItems: "center", background: "rgba(124,92,255,.15)", color: "#c4b5fd" } }, icon("cpu", 18)),
        h("div", {}, h("b", {}, g ? g.name : t.device || "GPU no detectada"), h("div", { class: "muted small" }, g ? `Driver ${g.driver} · ${g.temp} °C` : "Instala los drivers NVIDIA recientes"))),
      g ? h("div", { class: "col", style: { gap: "6px" } }, h("div", { class: "row small" }, h("span", { class: "muted" }, "VRAM"), h("span", { class: "spacer" }), `${(g.vram_used_mb / 1024).toFixed(1)} / ${(g.vram_total_mb / 1024).toFixed(1)} GB`), h("div", { class: "meter" }, h("i", { style: { width: `${vram * 100}%` } }))) : null,
      h("div", { class: "kv" },
        h("span", {}, "RAM"), h("span", {}, s.ram_gb ? `${s.ram_gb} GB` : "—"),
        h("span", {}, "CPU"), h("span", {}, `${s.cpu_count} hilos`),
        h("span", {}, "PyTorch"), h("span", {}, t.torch ? `${t.torch} ${t.cuda ? "· CUDA ✓" : "· sin CUDA"}` : "no instalado"),
        h("span", {}, "FFmpeg"), h("span", {}, state.health.ffmpeg.ffmpeg ? `✓ ${state.health.ffmpeg.nvenc ? "· NVENC" : ""}` : "no encontrado"),
        h("span", {}, "Perfil"), h("span", {}, `VRAM ${s.recommend.tier}`),
      ),
      btn("Gestionar modelos", { icon: "box", cls: "sm", onClick: () => go("models") }),
    ),
  );
}
