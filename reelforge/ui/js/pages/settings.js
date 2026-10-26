// Ajustes persistentes.
import { api } from "../api.js";
import { refreshMeta, state } from "../state.js";
import { bridge, btn, field, h, icon, select, toast, toggle } from "../ui.js";

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
      section("Rutas", "folder",
        field("Carpeta de FFmpeg (opcional)", input("ffmpeg_path", { placeholder: "C:\\ffmpeg\\bin" }), state.health.ffmpeg.ffmpeg ? `En uso: ${state.health.ffmpeg.ffmpeg}` : "FFmpeg no encontrado"),
        field("Caché de modelos Hugging Face (opcional)", input("hf_home", { placeholder: "Por defecto: carpeta de datos/models" }), "Requiere reiniciar la app.")),
      section("Acerca de", "info",
        h("div", { class: "kv" }, h("span", {}, "Versión"), h("span", {}, state.health.version), h("span", {}, "Motor"), h("span", {}, "FastAPI + PyTorch + FFmpeg"), h("span", {}, "Interfaz"), h("span", {}, bridge.isElectron ? "Electron" : "Navegador")),
        h("div", { class: "muted small" }, "Revisa las licencias de cada modelo antes de usarlo con fines comerciales (MusicGen y XTTS son no comerciales).")),
    ),
  );
}
