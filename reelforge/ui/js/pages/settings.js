// Ajustes persistentes.
import { api, fileUrl } from "../api.js";
import { importMedia, refreshMeta, state } from "../state.js";
import { bridge, btn, clear, field, h, icon, select, slider, toast, toggle } from "../ui.js";

export async function render(view) {
  const s = { ...(await api.get("/api/settings")) };
  const meta = state.meta;
  const input = (key, opts = {}) => h("input", { class: "input", type: opts.type || "text", value: s[key] ?? "", placeholder: opts.placeholder || "", oninput: (e) => (s[key] = e.target.value) });
  const VIDEO_MODELS = [
    ["gemini-omni-1.1-flash", "Gemini Omni 1.1 Flash (recomendado)"],
    ["veo-3.1-generate-preview", "Veo 3.1"],
    ["veo-3.0-generate-001", "Veo 3"],
    ["veo-3.0-fast-generate-001", "Veo 3 Fast"],
  ];
  const videoModel = () => {
    const custom = h("input", { class: "input", value: s.google_video_model, placeholder: "id del modelo", oninput: (e) => (s.google_video_model = e.target.value) });
    const known = VIDEO_MODELS.some(([id]) => id === s.google_video_model);
    if (known) custom.classList.add("hidden");
    const sel = select([...VIDEO_MODELS, ["__custom", "Otro (escribir id)…"]], known ? s.google_video_model : "__custom", (v) => {
      custom.classList.toggle("hidden", v !== "__custom");
      if (v !== "__custom") s.google_video_model = v;
      else custom.focus();
    });
    return h("div", { class: "col", style: { gap: "8px" } }, sel, custom);
  };
  const ttsVoices = () => (meta.tts.voices[s.tts_engine] || []).map((v) => [v.id, v.name]);
  const voiceSel = h("div");
  const drawVoice = () => voiceSel.replaceChildren(select(ttsVoices(), s.tts_voice, (v) => (s.tts_voice = v)));
  drawVoice();
  const save = btn("Guardar cambios", { cls: "primary", icon: "check" });
  save.onclick = async () => {
    save.classList.add("loading");
    try {
      await api.post("/api/settings", s);
      await refreshMeta();
      toast("Ajustes guardados", "ok");
    } catch (e) {
      toast(e.message, "err");
    } finally {
      save.classList.remove("loading");
    }
  };
  const section = (title, ic, ...children) => h("div", { class: "card col", style: { gap: "14px" } }, h("div", { class: "card-title" }, icon(ic, 18), h("h3", {}, title)), ...children);
  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Ajustes"), h("p", {}, `Datos en ${state.health.data_dir}`)), save),
    h("div", { class: "grid g2 stagger" },
      section("Rendimiento", "zap",
        h("div", { class: "toggle-row" }, h("div", {}, h("b", {}, "Modo VRAM baja"), h("div", { class: "muted small" }, "Descarga partes del modelo a la RAM. Recomendado con 8 GB.")), toggle(s.low_vram, (v) => (s.low_vram = v))),
        h("div", { class: "row" }, btn("Liberar VRAM ahora", { icon: "refresh", cls: "sm", onClick: async () => { await api.post("/api/gpu/release"); toast("VRAM liberada", "ok"); } }))),
      section("Valores por defecto", "sparkles",
        h("div", { class: "grid g2" },
          field("Idioma", select([["es", "Español"], ["en", "Inglés"], ["pt", "Portugués"], ["fr", "Francés"], ["it", "Italiano"]], s.language, (v) => (s.language = v))),
          field("Whisper", select(meta.whisper.map((m) => [m, m]), s.whisper_model, (v) => (s.whisper_model = v))),
          field("Motor de voz", select(meta.tts.engines.map((e) => [e.id, e.name]), s.tts_engine, (v) => { s.tts_engine = v; s.tts_voice = ttsVoices()[0]?.[0]; drawVoice(); })),
          field("Voz", voiceSel),
          field("Modelo de imagen", select(Object.entries(meta.image.models).map(([k, v]) => [k, v.name]), s.image_model, (v) => (s.image_model = v))),
          field("Estilo de subtítulos", select(Object.entries(meta.caption_styles).map(([k, v]) => [k, v.name]), s.caption_style, (v) => (s.caption_style = v))),
          field("Exportación", select(Object.entries(meta.export_presets).map(([k, v]) => [k, v.name]), s.export_preset, (v) => (s.export_preset = v))))),
      section("IA de texto (guiones)", "text2",
        field("Proveedor", select([["ollama", "Ollama (local)"], ["gemini", "Google Gemini (nube)"], ["none", "Sin LLM (plantillas)"]], s.llm_provider, (v) => (s.llm_provider = v))),
        h("div", { class: "grid g2" }, field("URL de Ollama", input("ollama_url")), field("Modelo de Ollama", input("ollama_model", { placeholder: "qwen3:8b" }))),
        field("Modelo de Gemini", input("gemini_text_model"))),
      section("Google (Imagen, Veo, Gemini)", "key",
        field("Clave de API de Google AI Studio", input("gemini_api_key", { type: "password", placeholder: "AIza…" }), "Se guarda sólo en tu PC (settings.json)."),
        h("div", { class: "grid g2" }, field("Modelo de imagen", input("google_image_model")), field("Modelo de vídeo", videoModel())),
        btn("Obtener una clave", { icon: "external", cls: "sm ghost", onClick: () => bridge.openExternal("https://aistudio.google.com/apikey") })),
      brandSection(s, section, input),
      section("Hugging Face", "box",
        field("Token de acceso (opcional)", input("hf_token", { type: "password", placeholder: "hf_…" }), "Necesario sólo para modelos con licencia que hay que aceptar (gated). Se guarda sólo en tu PC."),
        btn("Crear un token", { icon: "external", cls: "sm ghost", onClick: () => bridge.openExternal("https://huggingface.co/settings/tokens") })),
      section("Rutas", "folder",
        field("Carpeta de FFmpeg (opcional)", input("ffmpeg_path", { placeholder: "C:\\ffmpeg\\bin" }), state.health.ffmpeg.ffmpeg ? `En uso: ${state.health.ffmpeg.ffmpeg}` : "FFmpeg no encontrado"),
        field("Caché de modelos Hugging Face (opcional)", input("hf_home", { placeholder: "Por defecto: carpeta de datos/models" }), "Requiere reiniciar la app.")),
      section("Actualizaciones", "refresh",
        h("div", { class: "muted small" }, "La app se actualiza desde aquí: no hace falta volver a compilar ni a instalar."),
        btn("Buscar actualizaciones", { icon: "refresh", cls: "primary sm", onClick: () => import("../updates.js").then((m) => m.openUpdateDialog()) })),
      section("Acerca de", "info",
        h("div", { class: "kv" }, h("span", {}, "Versión"), h("span", {}, state.health.version), h("span", {}, "Motor"), h("span", {}, "FastAPI + PyTorch + FFmpeg"), h("span", {}, "Interfaz"), h("span", {}, bridge.isElectron ? "Electron" : "Navegador")),
        h("div", { class: "muted small" }, "Revisa las licencias de cada modelo antes de usarlo con fines comerciales (MusicGen y XTTS son no comerciales).")),
    ),
  );
}

function brandSection(s, section, input) {
  const media = h("div", { class: "col", style: { gap: "14px" } });
  const draw = async () => {
    const all = await api.get("/api/media");
    const images = all.filter((m) => m.kind === "image");
    const visual = all.filter((m) => m.kind !== "audio");
    const logo = images.find((m) => m.id === s.brand_logo_media_id);
    clear(media,
      field("Logo (PNG con transparencia recomendado)", h("div", { class: "row" },
        logo ? h("div", { style: { width: "42px", height: "42px", borderRadius: "8px", flex: "none", background: `url(${fileUrl.media(logo.id)}) center/contain no-repeat, var(--bg-2)` } }) : null,
        select([["", "Sin logo"], ...images.map((m) => [m.id, m.name])], s.brand_logo_media_id, (v) => { s.brand_logo_media_id = v; draw(); }),
        btn("Subir", { icon: "upload", cls: "sm", onClick: async () => { const items = await importMedia("visual"); if (items[0]) { s.brand_logo_media_id = items[0].id; draw(); } } }))),
      h("div", { class: "grid g2" },
        field("Posición del logo", select([["top-right", "Arriba derecha"], ["top-left", "Arriba izquierda"], ["bottom-right", "Abajo derecha"], ["bottom-left", "Abajo izquierda"]], s.brand_logo_pos, (v) => (s.brand_logo_pos = v))),
        field("Tamaño", slider(s.brand_logo_scale, 0.06, 0.4, 0.01, (v) => (s.brand_logo_scale = v), (v) => `${Math.round(v * 100)}%`))),
      field("Opacidad del logo", slider(s.brand_logo_opacity, 0.2, 1, 0.05, (v) => (s.brand_logo_opacity = v), (v) => `${Math.round(v * 100)}%`)),
      h("div", { class: "grid g2" },
        field("Tu @usuario (marca de agua)", input("brand_handle", { placeholder: "@tucuenta" })),
        field("Color de palabras clave", h("div", { class: "row" }, h("input", { type: "color", value: s.brand_keyword_color || "#39ff6a", style: { width: "44px", height: "36px", border: 0, background: "none" }, oninput: (e) => (s.brand_keyword_color = e.target.value) }), btn("Por estilo", { cls: "ghost sm", onClick: () => { s.brand_keyword_color = ""; toast("Se usará el color de cada estilo", "info"); } })))),
      h("div", { class: "toggle-row" }, h("div", {}, h("span", {}, "Llamada a la acción al final"), h("div", { class: "muted small" }, "Se añade en los últimos 2,5 s de cada reel nuevo")), toggle(s.brand_cta_enabled, (v) => (s.brand_cta_enabled = v))),
      field("Texto de la llamada a la acción", input("brand_cta", { placeholder: "Sígueme para más" })),
      h("div", { class: "grid g2" },
        field("Intro (opcional)", select([["", "Sin intro"], ...visual.map((m) => [m.id, m.name])], s.brand_intro_media_id, (v) => (s.brand_intro_media_id = v))),
        field("Outro (opcional)", select([["", "Sin outro"], ...visual.map((m) => [m.id, m.name])], s.brand_outro_media_id, (v) => (s.brand_outro_media_id = v)))),
      h("div", { class: "muted small" }, "El logo y el @usuario se aplican al exportar; la intro, la outro y la llamada a la acción al crear reels (Reel automático, Clips y Lote)."),
    );
  };
  draw();
  return section("Kit de marca", "sparkles", media);
}
