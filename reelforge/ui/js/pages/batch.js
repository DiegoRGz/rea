// Producción en lote: muchos temas → muchos reels terminados.
import { api, fileUrl, runJob } from "../api.js";
import { go } from "../app.js";
import { state } from "../state.js";
import { bridge, btn, chips, clear, field, h, icon, ring, segmented, select, slider, timeAgo, toast, toggle } from "../ui.js";

export async function render(view) {
  const s = state.settings;
  const o = { template: "auto", tone: "intrigante", seconds: 30, platform: "TikTok", lang: s.language, tts_engine: s.tts_engine, voice: s.tts_voice, speed: 1.08, visual_mode: "image", image_model: s.image_model, image_style: "cinematic", music_media_id: null, auto_edit: true, export: true, export_preset: s.export_preset || "tiktok" };
  const topics = h("textarea", { class: "textarea", style: { minHeight: "220px", fontSize: "14.5px" }, placeholder: "Un tema por línea, por ejemplo:\n5 hábitos de las personas millonarias\nEl error que todos cometen al dormir\nCómo usar la IA para estudiar el doble de rápido" });
  const count = h("span", { class: "badge accent" }, "0 reels");
  topics.addEventListener("input", () => (count.textContent = `${topics.value.split("\n").filter((x) => x.trim()).length} reels`));
  const tpls = Object.entries(state.meta.templates).map(([id, t]) => [id, `${t.emoji} ${t.name}`]);
  const voices = h("div");
  const drawVoices = () => clear(voices, select((state.meta.tts.voices[o.tts_engine] || []).map((v) => [v.id, v.name]), o.voice, (v) => (o.voice = v)));
  drawVoices();
  const music = h("div");
  api.get("/api/media?kind=audio").then((list) => clear(music, select([["", "Sin música"], ...list.filter((a) => a.source !== "tts" && a.source !== "sfx").map((a) => [a.id, a.name])], "", (v) => (o.music_media_id = v || null))));
  const history = h("div", { class: "col" });

  const loadHistory = async () => {
    const list = await api.get("/api/batches");
    clear(history, list.length ? list.map(batchCard) : h("div", { class: "empty" }, "Aquí verás tus lotes anteriores."));
  };

  const batchCard = (b) => {
    const done = b.items.filter((i) => i.status === "done").length;
    return h("div", { class: "card col", style: { gap: "10px" } },
      h("div", { class: "row" }, h("b", {}, `${state.meta.templates[b.template]?.emoji || "✨"} Lote de ${b.items.length} reels`), h("span", { class: `badge ${done === b.items.length ? "ok" : "warn"}` }, `${done}/${b.items.length} listos`), h("div", { class: "spacer" }), h("span", { class: "muted small" }, timeAgo(b.created))),
      h("div", { class: "col", style: { gap: "6px" } }, b.items.map((it) => h("div", { class: "row small", style: { gap: "8px" } },
        h("span", { style: { color: it.status === "done" ? "var(--ok)" : it.status === "error" ? "var(--err)" : "var(--muted)" } }, icon(it.status === "done" ? "check" : it.status === "error" ? "alert" : "clock", 14)),
        h("span", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }, title: it.error || "" }, it.title || it.topic),
        it.project_id ? btn("Editar", { cls: "ghost sm", onClick: () => go("editor", it.project_id) }) : null,
        it.export && bridge.showItemInFolder ? btn("", { icon: "folder", cls: "ghost icon sm", title: "Mostrar", onClick: () => bridge.showItemInFolder(it.export) }) : null,
        it.export ? h("a", { class: "btn ghost icon sm", title: "Descargar", href: fileUrl.export(it.export.replace(/\\/g, "/").split("/").pop()), download: "" }, icon("download", 14)) : null))));
  };

  const run = btn("Fabricar todos", { cls: "primary lg", icon: "rocket" });
  run.onclick = async () => {
    const list = topics.value.split("\n").map((x) => x.trim()).filter(Boolean);
    if (!list.length) return toast("Escribe al menos un tema", "info");
    const r = ring(120);
    const msg = h("div", { class: "muted small" });
    const box = h("div", { class: "card" }, h("div", { class: "big-progress", style: { padding: "26px" } }, r, h("h2", {}, `Fabricando ${list.length} reels 🏭`), msg, h("div", { class: "muted small" }, "Puedes cerrar esta página: el lote sigue trabajando (barra inferior derecha).")));
    history.prepend(box);
    run.classList.add("loading");
    try {
      await runJob(api.post("/api/batch", { ...o, topics: list }), (j) => { r.set(j.progress); msg.textContent = j.message; });
      toast("¡Lote terminado!", "ok", 7000);
    } catch (e) {
      toast(e.message, "err", 9000);
    } finally {
      run.classList.remove("loading");
      loadHistory();
    }
  };

  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Producción ", h("span", { class: "grad-text" }, "en lote")), h("p", {}, "Escribe una lista de temas y deja que la app guionice, narre, ilustre, edite y exporte cada reel mientras haces otra cosa."))),
    h("div", { class: "grid stagger", style: { gridTemplateColumns: "minmax(0,1.3fr) minmax(0,1fr)", gap: "18px" } },
      h("div", { class: "card col", style: { gap: "14px" } }, h("div", { class: "row" }, h("h3", {}, "Temas"), count), topics, field("Formato viral", chips(tpls, o.template, (v) => (o.template = v))), h("div", { class: "row" }, h("div", { class: "spacer" }), run)),
      h("div", { class: "card col", style: { gap: "14px" } },
        h("div", { class: "grid g2" },
          field("Duración", segmented([[15, "15 s"], [30, "30 s"], [45, "45 s"], [60, "60 s"]], o.seconds, (v) => (o.seconds = v))),
          field("Plataforma", select([["TikTok", "TikTok"], ["Instagram Reels", "Reels"], ["YouTube Shorts", "Shorts"]], o.platform, (v) => (o.platform = v)))),
        h("div", { class: "grid g2" },
          field("Motor de voz", select(state.meta.tts.engines.map((e) => [e.id, e.name]), o.tts_engine, (v) => { o.tts_engine = v; o.voice = (state.meta.tts.voices[v] || [])[0]?.id; drawVoices(); })),
          field("Voz", voices)),
        field("Visuales", select([["image", "Imágenes IA (local)"], ["hybrid", "Híbrido: vídeo IA en el gancho"], ["google-image", "Google Imagen"], ["google-video", "Google vídeo (Omni/Veo)"], ["video", "Vídeo IA local (muy lento)"]], o.visual_mode, (v) => (o.visual_mode = v))),
        field("Modelo de imagen", select(Object.entries(state.meta.image.models).map(([k, v]) => [k, v.name]), o.image_model, (v) => (o.image_model = v))),
        field("Música", music),
        h("div", { class: "toggle-row" }, h("span", {}, "Edición viral automática"), toggle(o.auto_edit, (v) => (o.auto_edit = v))),
        h("div", { class: "toggle-row" }, h("span", {}, "Exportar al terminar"), toggle(o.export, (v) => (o.export = v))),
        field("Preajuste de exportación", select(Object.entries(state.meta.export_presets).map(([k, v]) => [k, v.name]), o.export_preset, (v) => (o.export_preset = v))),
        field("Velocidad de voz", slider(o.speed, 0.8, 1.4, 0.02, (v) => (o.speed = v), (v) => `${v.toFixed(2)}×`)))),
    h("div", { class: "section-title" }, "Lotes"),
    history,
  );
  loadHistory();
}
