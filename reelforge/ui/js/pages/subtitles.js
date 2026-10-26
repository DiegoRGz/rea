// Transcripción y subtítulos automáticos para cualquier audio o vídeo.
import { api, fileUrl, runJob } from "../api.js";
import { go } from "../app.js";
import { styleCard } from "../captions.js";
import { importMedia, state } from "../state.js";
import { btn, clear, field, fmtTime, h, icon, select, toast } from "../ui.js";

function download(name, text) {
  const a = h("a", { href: URL.createObjectURL(new Blob([text], { type: "text/plain" })), download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

function srt(words, vtt = false) {
  const groups = [];
  let cur = [];
  for (const w of words) {
    if (cur.length && (cur.length >= 8 || cur.join(" ").length > 40 || w.s - cur.at(-1).e > 0.8 || /[.!?]$/.test(cur.at(-1).w))) {
      groups.push(cur);
      cur = [];
    }
    cur.push(w);
  }
  if (cur.length) groups.push(cur);
  const ts = (t) => {
    const ms = Math.round(t * 1000);
    const p = (n, l = 2) => String(n).padStart(l, "0");
    return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)}${vtt ? "." : ","}${p(ms % 1000, 3)}`;
  };
  const out = groups.map((g, i) => `${vtt ? "" : `${i + 1}\n`}${ts(g[0].s)} --> ${ts(g.at(-1).e)}\n${g.map((w) => w.w).join(" ")}\n`);
  return (vtt ? "WEBVTT\n\n" : "") + out.join("\n");
}

export async function render(view) {
  const st = { media: null, model: state.settings.whisper_model, lang: state.settings.language, style: state.settings.caption_style, result: null };
  const picker = h("div");
  const preview = h("div");
  const result = h("div", { class: "col" });
  const drawPicker = async () => {
    const items = (await api.get("/api/media")).filter((m) => m.kind === "audio" || (m.kind === "video" && m.has_audio));
    clear(picker, select([["", "— Elige un audio o vídeo —"], ...items.map((m) => [m.id, `${m.kind === "video" ? "🎬" : "🎙️"} ${m.name} (${fmtTime(m.duration, false)})`])], st.media?.id || "", (id) => {
      st.media = items.find((m) => m.id === id) || null;
      clear(preview, st.media ? (st.media.kind === "video" ? h("video", { src: fileUrl.media(st.media.id), controls: true, style: { width: "100%", maxHeight: "260px", borderRadius: "12px", background: "#000" } }) : h("audio", { src: fileUrl.media(st.media.id), controls: true, style: { width: "100%" } })) : null);
      if (st.media?.meta?.words?.length) showResult({ words: st.media.meta.words, text: st.media.meta.transcript || st.media.meta.text || "" });
    }));
  };
  const run = btn("Transcribir", { cls: "primary lg", icon: "sparkles" });
  run.onclick = async () => {
    if (!st.media) return toast("Elige primero un archivo", "info");
    run.classList.add("loading");
    try {
      showResult(await runJob(api.post("/api/transcribe", { media_id: st.media.id, model: st.model, language: st.lang || null })));
      toast("Transcripción lista", "ok");
    } catch (e) {
      toast(e.message, "err", 9000);
    } finally {
      run.classList.remove("loading");
    }
  };
  const showResult = (res) => {
    st.result = res;
    const base = (st.media?.name || "subtitulos").replace(/[^\w\- ]+/g, "_");
    const styles = h("div", { class: "grid g4" });
    const drawStyles = () => clear(styles, Object.keys(state.meta.caption_styles).map((id) => styleCard(id, st.style === id, (sid) => { st.style = sid; drawStyles(); })));
    drawStyles();
    clear(result,
      h("div", { class: "card col", style: { gap: "12px" } },
        h("div", { class: "row" }, h("h3", {}, "Transcripción"), h("span", { class: "badge accent" }, `${res.words.length} palabras`), res.device ? h("span", { class: "badge" }, res.device.toUpperCase()) : null, h("div", { class: "spacer" }),
          btn("SRT", { icon: "download", cls: "sm ghost", onClick: () => download(`${base}.srt`, srt(res.words)) }),
          btn("VTT", { icon: "download", cls: "sm ghost", onClick: () => download(`${base}.vtt`, srt(res.words, true)) }),
          btn("TXT", { icon: "download", cls: "sm ghost", onClick: () => download(`${base}.txt`, res.text) }),
          btn("Copiar", { icon: "copy", cls: "sm ghost", onClick: () => { navigator.clipboard.writeText(res.text); toast("Copiado", "ok"); } })),
        h("p", { style: { margin: 0, userSelect: "text", lineHeight: 1.7 } }, res.text),
        h("div", { class: "words" }, res.words.slice(0, 300).map((w) => h("span", { class: "word" }, w.w, h("small", {}, w.s.toFixed(2)))))),
      h("div", { class: "card col", style: { gap: "12px" } },
        h("h3", {}, "Crear vídeo con subtítulos animados"),
        styles,
        h("div", { class: "row" }, h("span", { class: "muted small" }, "Crea un proyecto con este medio y los subtítulos sincronizados, listo para exportar."), h("div", { class: "spacer" }), btn("Abrir en el editor", { cls: "primary", icon: "film", onClick: () => createProject(st) }))),
    );
  };
  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Subtítulos ", h("span", { class: "grad-text" }, "automáticos")), h("p", {}, "Transcribe con Whisper y crea subtítulos animados tipo TikTok palabra a palabra."))),
    h("div", { class: "grid stagger", style: { gridTemplateColumns: "minmax(0,1fr) 340px", gap: "18px" } },
      h("div", { class: "card col", style: { gap: "14px" } }, h("div", { class: "row" }, h("div", { style: { flex: 1 } }, picker), btn("Importar", { icon: "upload", onClick: async () => { await importMedia("all"); drawPicker(); } })), preview),
      h("div", { class: "card col", style: { gap: "14px" } },
        field("Modelo Whisper", select(state.meta.whisper.map((m) => [m, m === "large-v3-turbo" ? "large-v3-turbo (recomendado)" : m]), st.model, (v) => (st.model = v))),
        field("Idioma", select([["es", "Español"], ["en", "Inglés"], ["pt", "Portugués"], ["fr", "Francés"], ["it", "Italiano"], ["", "Detectar automáticamente"]], st.lang, (v) => (st.lang = v))),
        run)),
    h("div", { style: { marginTop: "18px" } }, result),
  );
  drawPicker();
}

async function createProject(st) {
  const m = st.media;
  const project = await api.post("/api/projects", { name: `Subtítulos · ${m.name}`, aspect: m.kind === "video" && m.width > m.height ? "16:9" : "9:16" });
  const style = state.meta.caption_styles[st.style];
  if (m.kind === "video") {
    project.clips.push({ id: Math.random().toString(16).slice(2, 12), media_id: m.id, kind: "video", src_in: 0, src_out: m.duration, duration: m.duration, speed: 1, volume: 1, motion: "none", fit: "cover", filter: "none", transition: { type: "none", duration: 0.5 } });
  } else {
    project.audio.push({ id: Math.random().toString(16).slice(2, 12), media_id: m.id, role: "voice", start: 0, src_in: 0, src_out: null, volume: 1, fade_in: 0, fade_out: 0, loop: false });
  }
  project.captions = { ...project.captions, enabled: true, style: st.style, words: st.result.words, max_words: style.max_words, uppercase: style.uppercase };
  await api.put(`/api/projects/${project.id}`, project);
  go("editor", project.id);
}
