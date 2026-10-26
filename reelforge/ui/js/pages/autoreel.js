// Asistente "Reel automático": idea → guion → voz → visuales → estilo → proyecto.
import { api, fileUrl, runJob } from "../api.js";
import { go } from "../app.js";
import { styleCard } from "../captions.js";
import { importMedia, state } from "../state.js";
import { btn, chips, clear, field, h, icon, ring, segmented, select, slider, toast, toggle } from "../ui.js";

const STEPS = ["Idea", "Guion", "Voz", "Visuales", "Estilo"];
const TONES = [["intrigante", "🕵️ Intrigante"], ["educativo", "📚 Educativo"], ["divertido", "😂 Divertido"], ["motivador", "🔥 Motivador"], ["polémico", "⚡ Polémico"], ["storytelling", "🎬 Storytelling"], ["datos curiosos", "🤯 Datos curiosos"]];

// El borrador sobrevive a cambios de página durante la sesión.
const draft = (window.__rfDraft ||= {
  step: 0,
  topic: "",
  tone: "intrigante",
  template: "auto",
  auto_edit: true,
  brand: true,
  seconds: 30,
  platform: "TikTok",
  lang: "es",
  extra: "",
  script: null,
  tts_engine: null,
  voice: null,
  speed: 1.05,
  visual_mode: "image",
  image_model: "sdxl-lightning",
  image_style: "cinematic",
  video_model: "wan2.1-1.3b",
  caption_style: null,
  transition: "smoothup",
  music_media_id: null,
  music_volume: 0.16,
  hook_overlay: true,
  align_with_whisper: true,
});

export async function render(view) {
  const s = state.settings;
  draft.tts_engine ||= s.tts_engine;
  draft.voice ||= s.tts_voice;
  draft.caption_style ||= s.caption_style;
  const stepper = h("div", { class: "stepper" });
  const body = h("div", { class: "stagger" });
  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Reel ", h("span", { class: "grad-text" }, "automático")), h("p", {}, "De una idea a un vídeo editable con voz, visuales, subtítulos y transiciones."))),
    stepper,
    body,
  );
  const show = (i) => {
    draft.step = i;
    clear(stepper, STEPS.map((name, idx) => h("div", { class: `step ${idx === i ? "on" : ""} ${idx < i ? "done" : ""}`, onclick: () => (idx < i || (idx <= 1 && draft.script) || (draft.script && idx > 1)) && show(idx) }, h("span", { class: "n" }, idx < i ? icon("check", 14, 2.6) : idx + 1), name)));
    body.replaceChildren();
    body.style.animation = "none";
    void body.offsetWidth;
    body.style.animation = "";
    [stepIdea, stepScript, stepVoice, stepVisuals, stepStyle][i](body, show);
  };
  show(draft.step);
}

function nav(show, back, nextLabel, onNext) {
  return h("div", { class: "row", style: { marginTop: "22px" } },
    back !== null ? btn("Atrás", { icon: "chevronL", cls: "ghost", onClick: () => show(back) }) : null,
    h("div", { class: "spacer" }),
    nextLabel ? btn(nextLabel, { cls: "primary lg", icon: "chevronR", onClick: onNext }) : null);
}

function stepIdea(body, show) {
  const topic = h("textarea", { class: "textarea", placeholder: "Ej.: 5 hábitos de las personas exitosas que nadie te cuenta", value: draft.topic, style: { minHeight: "110px", fontSize: "15px" } });
  topic.addEventListener("input", () => (draft.topic = topic.value));
  const extra = h("input", { class: "input", placeholder: "Opcional: público objetivo, datos a incluir, estilo de humor…", value: draft.extra, oninput: (e) => (draft.extra = e.target.value) });
  const llmInfo = h("span", { class: "badge" }, "Comprobando IA de texto…");
  api.get("/api/llm/status").then((st) => {
    const ok = st.provider === "ollama" ? st.ollama.running : st.provider === "gemini" ? st.gemini : false;
    clear(llmInfo, h("span", { class: "dot" }), st.provider === "none" ? "Plantillas (sin LLM)" : `${st.provider === "ollama" ? `Ollama · ${st.model}` : "Gemini"} ${ok ? "listo" : "no disponible: se usará plantilla"}`);
    llmInfo.className = `badge ${ok ? "ok" : "warn"}`;
  });
  const write = btn("Escribir guion con IA", { cls: "primary lg", icon: "sparkles" });
  write.onclick = async () => {
    if (!draft.topic.trim()) return toast("Escribe primero de qué va tu reel", "info");
    write.classList.add("loading");
    try {
      draft.script = await runJob(api.post("/api/script", { topic: draft.topic, tone: draft.tone, seconds: draft.seconds, platform: draft.platform, lang: draft.lang, extra: draft.extra, template: draft.template }));
      const tpl = state.meta.templates[draft.template];
      if (tpl?.caption_style) draft.caption_style = tpl.caption_style;
      if (tpl?.transition) draft.transition = tpl.transition;
      if (draft.script.warnings?.length) toast(`Se usó una plantilla: ${draft.script.warnings[0]}`, "info", 7000);
      show(1);
    } catch (e) {
      toast(e.message, "err");
    } finally {
      write.classList.remove("loading");
    }
  };
  body.append(
    h("div", { class: "card col", style: { gap: "18px" } },
      field("¿De qué trata tu reel?", topic),
      field("Formato viral", chips(Object.entries(state.meta.templates).map(([id, t]) => [id, `${t.emoji} ${t.name}`]), draft.template, (v) => (draft.template = v))),
      field("Tono", chips(TONES, draft.tone, (v) => (draft.tone = v))),
      h("div", { class: "grid g3" },
        field("Duración", segmented([[15, "15 s"], [30, "30 s"], [45, "45 s"], [60, "60 s"]], draft.seconds, (v) => (draft.seconds = v))),
        field("Plataforma", segmented([["TikTok", "TikTok"], ["Instagram Reels", "Reels"], ["YouTube Shorts", "Shorts"]], draft.platform, (v) => (draft.platform = v))),
        field("Idioma", select([["es", "Español"], ["en", "Inglés"], ["pt", "Portugués"], ["fr", "Francés"], ["it", "Italiano"]], draft.lang, (v) => (draft.lang = v))),
      ),
      field("Indicaciones extra", extra),
      h("div", { class: "row" }, llmInfo, h("div", { class: "spacer" }), btn("Lo escribo yo", { cls: "ghost", onClick: () => { draft.script = { title: draft.topic || "Mi reel", hook: "", scenes: [{ narration: "", visual: "" }, { narration: "", visual: "" }, { narration: "", visual: "" }], caption: "", hashtags: [] }; show(1); } }), write),
    ),
  );
}

function stepScript(body, show) {
  const sc = draft.script;
  const list = h("div", { class: "col" });
  const draw = () => clear(list, sc.scenes.map((scene, i) => {
    const narr = h("textarea", { class: "textarea", placeholder: "Narración de la escena", value: scene.narration, oninput: (e) => { scene.narration = e.target.value; count(); } });
    const vis = h("textarea", { class: "textarea", placeholder: "Prompt visual (en inglés funciona mejor)", value: scene.visual, oninput: (e) => (scene.visual = e.target.value) });
    return h("div", { class: "scene" },
      h("div", { class: "num" }, i + 1),
      h("div", { class: "col", style: { gap: "4px" } }, h("span", { class: "label" }, i === 0 ? "🎣 Gancho / narración" : "Narración"), narr),
      h("div", { class: "col", style: { gap: "4px" } }, h("span", { class: "label" }, "🎨 Visual"), vis),
      h("div", { class: "col", style: { gap: "4px" } },
        btn("", { icon: "chevronL", cls: "ghost icon sm", title: "Subir", onClick: () => { if (i > 0) { [sc.scenes[i - 1], sc.scenes[i]] = [sc.scenes[i], sc.scenes[i - 1]]; draw(); } } }),
        btn("", { icon: "trash", cls: "ghost icon sm danger", title: "Eliminar", onClick: () => { sc.scenes.splice(i, 1); draw(); count(); } })));
  }));
  const counter = h("span", { class: "badge accent" });
  const count = () => {
    const words = sc.scenes.reduce((a, s) => a + s.narration.split(/\s+/).filter(Boolean).length, 0);
    counter.textContent = `${words} palabras · ~${Math.round(words / 2.6)} s`;
  };
  draw();
  count();
  const tags = h("div", { class: "small", style: { userSelect: "text" } }, `${sc.caption || ""} ${(sc.hashtags || []).join(" ")}`);
  body.append(
    h("div", { class: "card col", style: { gap: "14px" } },
      h("div", { class: "grid g2" },
        field("Título", h("input", { class: "input", value: sc.title, oninput: (e) => (sc.title = e.target.value) })),
        field("Texto del gancho en pantalla (opcional)", h("input", { class: "input", value: sc.hook, oninput: (e) => (sc.hook = e.target.value) }))),
      h("div", { class: "row" }, h("h3", {}, "Escenas"), counter, h("div", { class: "spacer" }), sc.provider ? h("span", { class: "muted small" }, `Generado con ${sc.provider}`) : null),
      list,
      btn("Añadir escena", { icon: "plus", cls: "sm", onClick: () => { sc.scenes.push({ narration: "", visual: "" }); draw(); } }),
      sc.caption || sc.hashtags?.length ? h("div", { class: "card", style: { padding: "12px", background: "var(--bg-2)" } }, h("div", { class: "row" }, h("span", { class: "label" }, "Descripción y hashtags"), h("div", { class: "spacer" }), btn("Copiar", { icon: "copy", cls: "ghost sm", onClick: () => { navigator.clipboard.writeText(tags.textContent.trim()); toast("Copiado", "ok"); } })), tags) : null,
    ),
    nav(show, 0, "Elegir voz", () => {
      if (!sc.scenes.some((s) => s.narration.trim())) return toast("Escribe la narración de al menos una escena", "info");
      show(2);
    }),
  );
}

function stepVoice(body, show) {
  const cat = state.meta.tts;
  const voices = h("div", { class: "grid g3" });
  const drawVoices = () => {
    const list = (cat.voices[draft.tts_engine] || []).filter((v) => draft.tts_engine === "xtts" || v.lang === draft.lang || draft.lang === "es" && v.lang === "es");
    const all = list.length ? list : cat.voices[draft.tts_engine] || [];
    if (!all.some((v) => v.id === draft.voice)) draft.voice = all[0]?.id;
    clear(voices, all.length ? all.map((v) => h("div", { class: `voice-card ${draft.voice === v.id ? "on" : ""}`, onclick: () => { draft.voice = v.id; drawVoices(); } }, h("div", { class: "av" }, v.name[0]), h("div", {}, h("b", { class: "small" }, v.name), h("div", { class: "muted small" }, v.lang)))) : h("div", { class: "empty", style: { gridColumn: "1/-1" } }, draft.tts_engine === "xtts" ? "Guarda una muestra de voz en Voz IA → Clonar voz." : "Sin voces"));
  };
  const engines = cat.engines.map((e) => [e.id, `${e.name}${e.installed ? "" : " (no instalado)"}`]);
  const audio = h("div");
  const test = btn("Escuchar prueba", { icon: "play", cls: "sm" });
  test.onclick = async () => {
    test.classList.add("loading");
    try {
      const text = draft.script.scenes.find((s) => s.narration.trim())?.narration || "Hola, esta es mi voz.";
      const item = await runJob(api.post("/api/tts", { text, engine: draft.tts_engine, voice: draft.voice, speed: draft.speed, lang: draft.lang, name: "Prueba de voz" }));
      clear(audio, h("audio", { controls: true, autoplay: true, src: fileUrl.media(item.id), style: { width: "100%" } }));
    } catch (e) {
      toast(e.message, "err", 7000);
    } finally {
      test.classList.remove("loading");
    }
  };
  drawVoices();
  body.append(
    h("div", { class: "card col", style: { gap: "16px" } },
      field("Motor de voz", select(engines, draft.tts_engine, (v) => { draft.tts_engine = v; drawVoices(); })),
      voices,
      field("Velocidad", slider(draft.speed, 0.7, 1.4, 0.05, (v) => (draft.speed = v), (v) => `${v.toFixed(2)}×`)),
      h("div", { class: "row" }, test, h("span", { class: "muted small" }, "Los reels virales suelen narrarse a 1.05–1.15×.")),
      audio,
    ),
    nav(show, 1, "Elegir visuales", () => show(3)),
  );
}

function stepVisuals(body, show) {
  const modes = [
    ["image", "image", "Imágenes IA (local)", "SDXL en tu GPU. Rápido: ~5-15 s por escena. Con zoom/paneo animado."],
    ["video", "video", "Vídeo IA (local)", "Wan 2.1 en tu GPU. Muy lento en 8 GB (varios minutos por escena)."],
    ["google-image", "cloud", "Google Imagen", "Requiere clave de API de Google AI Studio."],
    ["google-video", "cloud", "Google vídeo", "Gemini Omni Flash o Veo (según Ajustes). Requiere clave y tiene coste."],
    ["library", "folder", "Mis archivos", "Asigna tus propias fotos o clips a cada escena."],
  ];
  const opts = h("div");
  const perScene = h("div", { class: "col" });
  const drawOpts = () => {
    const im = state.meta.image;
    if (draft.visual_mode === "image") clear(opts, h("div", { class: "grid g2" }, field("Modelo", select(Object.entries(im.models).map(([k, v]) => [k, v.name]), draft.image_model, (v) => (draft.image_model = v))), field("Estilo visual", select(im.styles.map((s) => [s, { none: "Ninguno", cinematic: "Cinemático", photo: "Foto realista", anime: "Anime", "3d": "3D Pixar", comic: "Cómic", neon: "Neón", minimal: "Minimalista" }[s] || s]), draft.image_style, (v) => (draft.image_style = v)))));
    else if (draft.visual_mode === "video") clear(opts, field("Modelo", select(Object.entries(state.meta.video.models).filter(([, v]) => v.mode === "t2v").map(([k, v]) => [k, v.name]), draft.video_model, (v) => (draft.video_model = v))));
    else clear(opts);
  };
  const drawScenes = async () => {
    const media = await api.get("/api/media");
    const visual = media.filter((m) => m.kind !== "audio");
    clear(perScene, draft.script.scenes.map((sc, i) => {
      const m = visual.find((x) => x.id === sc.media_id);
      return h("div", { class: "row card", style: { padding: "10px" } },
        h("div", { class: "num badge accent" }, i + 1),
        h("div", { style: { width: "42px", height: "56px", borderRadius: "8px", background: m?.thumb ? `url(${fileUrl.thumb(m.id)}) center/cover` : "var(--bg-2)", flex: "none", border: "1px solid var(--line)" } }),
        h("div", { class: "small", style: { flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, sc.narration || "(sin narración)"),
        select([["", draft.visual_mode === "library" ? "— Elegir archivo —" : "Generar automáticamente"], ...visual.map((v) => [v.id, v.name])], sc.media_id || "", (v) => { sc.media_id = v || null; drawScenes(); }));
    }));
  };
  const cards = h("div", { class: "grid", style: { gridTemplateColumns: "repeat(5, minmax(0,1fr))" } });
  const drawCards = () => clear(cards, modes.map(([id, ic, name, desc]) => h("div", { class: `option-card ${draft.visual_mode === id ? "on" : ""}`, onclick: () => { draft.visual_mode = id; drawCards(); drawOpts(); drawScenes(); } }, h("span", { class: "oc-icon" }, icon(ic, 20)), h("b", {}, name), h("p", {}, desc))));
  drawCards();
  drawOpts();
  drawScenes();
  body.append(
    h("div", { class: "card col", style: { gap: "16px" } }, cards, opts,
      h("div", { class: "row" }, h("h3", {}, "Medios por escena"), h("div", { class: "spacer" }), btn("Importar archivos", { icon: "upload", cls: "sm", onClick: async () => { await importMedia("visual"); drawScenes(); } })),
      h("div", { class: "muted small" }, "Puedes fijar un archivo concreto a cualquier escena; el resto se genera según el modo elegido."),
      perScene),
    nav(show, 2, "Estilo final", () => {
      if (draft.visual_mode === "library" && draft.script.scenes.some((s) => s.narration.trim() && !s.media_id)) return toast("Asigna un archivo a cada escena", "info");
      show(4);
    }),
  );
}

function stepStyle(body, show) {
  const styles = h("div", { class: "grid g4" });
  const drawStyles = () => clear(styles, Object.keys(state.meta.caption_styles).map((id) => styleCard(id, draft.caption_style === id, (sid) => { draft.caption_style = sid; drawStyles(); })));
  drawStyles();
  const music = h("div");
  const drawMusic = async () => {
    const audios = (await api.get("/api/media?kind=audio")).filter((m) => m.source !== "tts");
    clear(music, h("div", { class: "row" }, select([["", "Sin música"], ...audios.map((a) => [a.id, a.name])], draft.music_media_id || "", (v) => (draft.music_media_id = v || null)), btn("Importar", { icon: "upload", cls: "sm", onClick: async () => { await importMedia("audio"); drawMusic(); } }), btn("Generar", { icon: "music", cls: "sm ghost", onClick: () => go("generate", "music") })));
  };
  drawMusic();
  const create = btn("Crear mi reel", { cls: "primary lg", icon: "rocket" });
  create.onclick = () => build(body, show);
  body.append(
    h("div", { class: "card col", style: { gap: "16px" } },
      h("h3", {}, "Subtítulos"), styles,
      h("div", { class: "grid g2" },
        field("Transición entre escenas", select(Object.entries(state.meta.transitions), draft.transition, (v) => (draft.transition = v))),
        field("Música de fondo", music)),
      field("Volumen de la música", slider(draft.music_volume, 0, 0.6, 0.01, (v) => (draft.music_volume = v), (v) => `${Math.round(v * 100)}%`)),
      h("div", { class: "toggle-row" }, h("span", {}, "Mostrar el gancho como título al inicio"), toggle(draft.hook_overlay, (v) => (draft.hook_overlay = v))),
      h("div", { class: "toggle-row" }, h("span", {}, "Sincronizar subtítulos con Whisper (más preciso)"), toggle(draft.align_with_whisper, (v) => (draft.align_with_whisper = v))),
      h("div", { class: "toggle-row" }, h("div", {}, h("span", {}, "Edición viral automática"), h("div", { class: "muted small" }, "Palabras clave en color, emojis, zooms de impacto, efectos de sonido y cortes al ritmo")), toggle(draft.auto_edit, (v) => (draft.auto_edit = v))),
      h("div", { class: "toggle-row" }, h("div", {}, h("span", {}, "Kit de marca"), h("div", { class: "muted small" }, "Intro, outro y llamada a la acción (Ajustes → Kit de marca)")), toggle(draft.brand, (v) => (draft.brand = v))),
    ),
    h("div", { class: "row", style: { marginTop: "22px" } }, btn("Atrás", { icon: "chevronL", cls: "ghost", onClick: () => show(3) }), h("div", { class: "spacer" }), create),
  );
}

async function build(body, show) {
  const r = ring(170);
  const msg = h("div", { class: "muted" }, "Preparando…");
  const cancelNote = h("div", { class: "muted small" }, "Puedes seguir usando la app: el progreso aparece abajo a la derecha.");
  clear(body, h("div", { class: "card" }, h("div", { class: "big-progress" }, r, h("h2", {}, "Creando tu reel ✨"), msg, cancelNote)));
  const sc = draft.script;
  const payload = {
    title: sc.title || draft.topic || "Reel automático",
    hook: sc.hook || "",
    scenes: sc.scenes.filter((s) => s.narration.trim()),
    tts_engine: draft.tts_engine,
    voice: draft.voice,
    speed: draft.speed,
    lang: draft.lang,
    visual_mode: draft.visual_mode,
    image_model: draft.image_model,
    image_style: draft.image_style,
    video_model: draft.video_model,
    caption_style: draft.caption_style,
    transition: draft.transition,
    music_media_id: draft.music_media_id,
    music_volume: draft.music_volume,
    hook_overlay: draft.hook_overlay,
    align_with_whisper: draft.align_with_whisper,
    whisper_model: state.settings.whisper_model,
    auto_edit: draft.auto_edit,
    brand: draft.brand,
    extra: { caption: sc.caption || "", hashtags: sc.hashtags || [] },
  };
  try {
    const res = await runJob(api.post("/api/autoreel", payload), (j) => { r.set(j.progress); msg.textContent = j.message; });
    toast("¡Reel creado! Ábrelo y ajústalo a tu gusto.", "ok");
    draft.step = 0;
    draft.script = null;
    go("editor", res.project_id);
  } catch (e) {
    clear(body, h("div", { class: "card" }, h("div", { class: "big-progress" },
      h("div", { style: { color: "var(--err)" } }, icon("alert", 46)), h("h2", {}, "No se pudo crear el reel"),
      h("pre", { class: "small muted", style: { whiteSpace: "pre-wrap", userSelect: "text", maxWidth: "720px" } }, e.message),
      btn("Volver al estilo", { icon: "chevronL", onClick: () => show(4) }))));
  }
}
