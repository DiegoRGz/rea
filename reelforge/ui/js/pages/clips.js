// Clips virales desde un vídeo largo (podcast, directo, entrevista…).
import { api, fileUrl, runJob } from "../api.js";
import { go } from "../app.js";
import { styleCard } from "../captions.js";
import { importMedia, state } from "../state.js";
import { btn, clear, field, fmtTime, h, icon, ring, segmented, select, slider, toast, toggle } from "../ui.js";

export async function render(view) {
  const o = { media_id: "", count: 6, min_len: 20, max_len: 55, reframe: true, auto_edit: true, broll: "none", hook_title: true, brand: true, caption_style: state.settings.caption_style };
  const picker = h("div");
  const preview = h("div");
  const results = h("div", { class: "col" });
  const styles = h("div", { class: "grid g4" });
  const drawStyles = () => clear(styles, Object.keys(state.meta.caption_styles).map((id) => styleCard(id, o.caption_style === id, (sid) => { o.caption_style = sid; drawStyles(); })));
  drawStyles();

  const drawPicker = async () => {
    const videos = (await api.get("/api/media?kind=video")).filter((m) => (m.duration || 0) >= 30);
    clear(picker, select([["", "— Elige un vídeo largo (≥ 30 s) —"], ...videos.map((m) => [m.id, `${m.name} · ${fmtTime(m.duration, false)}${m.width > m.height ? " · horizontal" : ""}`])], o.media_id, (id) => {
      o.media_id = id;
      const m = videos.find((v) => v.id === id);
      clear(preview, m ? h("video", { src: fileUrl.media(m.id), controls: true, preload: "metadata", style: { width: "100%", maxHeight: "240px", borderRadius: "12px", background: "#000" } }) : null);
      loadResults();
    }));
  };

  const loadResults = async () => {
    if (!o.media_id) return clear(results);
    const runs = await api.get(`/api/clipper/${o.media_id}`);
    if (!runs.length) return clear(results);
    showRun(runs[0]);
  };

  const showRun = (run) => {
    clear(results,
      h("div", { class: "row" }, h("h2", {}, `${run.clips.length} clips encontrados`), h("span", { class: "badge accent" }, run.method === "ia" ? "Elegidos por IA" : "Selección automática"), h("div", { class: "spacer" }),
        btn("Exportar todos", { icon: "download", cls: "primary sm", onClick: (e) => exportAll(e.currentTarget, run.clips) })),
      h("div", { class: "grid g3 stagger" }, run.clips.map((c, i) => clipCard(c, i))));
  };

  const clipCard = (c, i) => {
    const score = Math.round(c.score);
    const cls = score >= 80 ? "ok" : score >= 60 ? "accent" : "warn";
    return h("div", { class: "card col", style: { gap: "10px" } },
      h("div", { class: "row" }, h("span", { class: `badge ${cls}` }, icon("zap", 12), `${score} viral`), c.retention ? h("span", { class: "badge" }, `Retención ${c.retention}`) : null, h("div", { class: "spacer" }), h("span", { class: "muted small" }, `#${i + 1}`)),
      h("b", {}, c.title),
      h("div", { class: "muted small" }, `${fmtTime(c.start, false)} → ${fmtTime(c.end, false)} · ${Math.round(c.end - c.start)} s${c.tracked ? " · sigue a la persona" : ""}`),
      c.reason ? h("div", { class: "small", style: { color: "var(--text-2)" } }, c.reason) : null,
      h("div", { class: "row" }, btn("Abrir en el editor", { icon: "film", cls: "sm", onClick: () => go("editor", c.project_id) })));
  };

  const exportAll = async (button, clips) => {
    button.classList.add("loading");
    try {
      for (const c of clips) await runJob(api.post(`/api/projects/${c.project_id}/export`, { preset: state.settings.export_preset || "tiktok", thumbnail: true, subtitles_file: true }));
      toast(`${clips.length} clips exportados (ver Exportados)`, "ok", 7000);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      button.classList.remove("loading");
    }
  };

  const runBtn = btn("Encontrar clips virales", { cls: "primary lg", icon: "scissors" });
  runBtn.onclick = async () => {
    if (!o.media_id) return toast("Elige primero un vídeo", "info");
    const r = ring(150);
    const msg = h("div", { class: "muted" }, "Preparando…");
    clear(results, h("div", { class: "card" }, h("div", { class: "big-progress" }, r, h("h2", {}, "Buscando los mejores momentos ✂️"), msg, h("div", { class: "muted small" }, "Transcribe todo el vídeo, la IA elige los fragmentos con más gancho y cada clip se reencuadra y edita solo."))));
    runBtn.classList.add("loading");
    try {
      const res = await runJob(api.post("/api/clipper", { ...o, lang: state.settings.language, whisper_model: state.settings.whisper_model }), (j) => { r.set(j.progress); msg.textContent = j.message; });
      showRun(res);
      toast("¡Clips listos!", "ok");
    } catch (e) {
      clear(results, h("div", { class: "notice" }, icon("alert", 16), e.message));
    } finally {
      runBtn.classList.remove("loading");
    }
  };

  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Clips ", h("span", { class: "grad-text" }, "virales")), h("p", {}, "Convierte un podcast, directo o entrevista en varios reels listos: reencuadre vertical, subtítulos y edición viral automática."))),
    h("div", { class: "grid stagger", style: { gridTemplateColumns: "minmax(0,1.2fr) minmax(0,1fr)", gap: "18px" } },
      h("div", { class: "card col", style: { gap: "14px" } },
        h("div", { class: "row" }, h("div", { style: { flex: 1 } }, picker), btn("Importar", { icon: "upload", onClick: async () => { await importMedia("visual"); drawPicker(); } })),
        preview,
        h("div", { class: "notice info" }, icon("info", 16), h("div", {}, "Usa contenido propio o con permiso. Para elegir los momentos se usa tu LLM (Ollama/Gemini); sin él, una selección automática por ganchos y ritmo."))),
      h("div", { class: "card col", style: { gap: "14px" } },
        field("Número de clips", slider(o.count, 1, 15, 1, (v) => (o.count = v))),
        h("div", { class: "grid g2" },
          field("Duración mínima", slider(o.min_len, 10, 60, 5, (v) => (o.min_len = v), (v) => `${v} s`)),
          field("Duración máxima", slider(o.max_len, 20, 120, 5, (v) => (o.max_len = v), (v) => `${v} s`))),
        h("div", { class: "toggle-row" }, h("div", {}, h("span", {}, "Reencuadre vertical inteligente"), h("div", { class: "muted small" }, "Sigue la cara de quien habla")), toggle(o.reframe, (v) => (o.reframe = v))),
        h("div", { class: "toggle-row" }, h("div", {}, h("span", {}, "Edición viral automática"), h("div", { class: "muted small" }, "Silencios, zooms, palabras clave, emojis y efectos")), toggle(o.auto_edit, (v) => (o.auto_edit = v))),
        field("B-roll", segmented([["none", "No"], ["library", "Biblioteca"], ["generate", "Generar IA"]], o.broll, (v) => (o.broll = v))),
        h("div", { class: "toggle-row" }, h("span", {}, "Título gancho al inicio"), toggle(o.hook_title, (v) => (o.hook_title = v))),
        h("div", { class: "toggle-row" }, h("span", {}, "Kit de marca (intro, outro, CTA)"), toggle(o.brand, (v) => (o.brand = v))),
        runBtn)),
    h("div", { class: "section-title" }, "Estilo de subtítulos"),
    styles,
    h("div", { style: { marginTop: "22px" } }, results),
  );
  drawPicker();
}
