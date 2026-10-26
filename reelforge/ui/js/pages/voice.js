// Estudio de voz: texto a voz con varios motores y clonación opcional.
import { api, fileUrl, runJob } from "../api.js";
import { importMedia, state } from "../state.js";
import { btn, clear, field, fmtTime, h, icon, segmented, select, slider, toast, timeAgo } from "../ui.js";

export async function render(view) {
  const cat = state.meta.tts;
  const s = { engine: state.settings.tts_engine, voice: state.settings.tts_voice, speed: 1, pitch: 0, lang: state.settings.language };
  const text = h("textarea", { class: "textarea", style: { minHeight: "190px", fontSize: "15px" }, placeholder: "Escribe o pega aquí la narración de tu vídeo…" });
  const stats = h("span", { class: "muted small" });
  text.addEventListener("input", () => {
    const words = text.value.split(/\s+/).filter(Boolean).length;
    stats.textContent = `${text.value.length} caracteres · ${words} palabras · ~${fmtTime(words / 2.6, false)}`;
  });
  text.dispatchEvent(new Event("input"));
  const voices = h("div", { class: "grid g3" });
  const pitchWrap = h("div");
  const engineNote = h("div");
  const drawVoices = () => {
    const list = cat.voices[s.engine] || [];
    if (!list.some((v) => v.id === s.voice)) s.voice = list[0]?.id;
    clear(voices, list.length ? list.map((v) => h("div", { class: `voice-card ${s.voice === v.id ? "on" : ""}`, onclick: () => { s.voice = v.id; drawVoices(); } }, h("div", { class: "av" }, v.name[0]), h("div", { style: { minWidth: 0 } }, h("b", { class: "small" }, v.name), h("div", { class: "muted small" }, v.lang)))) : h("div", { class: "empty", style: { gridColumn: "1/-1" } }, "No hay muestras de voz guardadas. Usa «Clonar voz» abajo."));
    clear(pitchWrap, s.engine === "edge" ? field("Tono", slider(s.pitch, -30, 30, 1, (v) => (s.pitch = v), (v) => `${v > 0 ? "+" : ""}${v} Hz`)) : null);
    const eng = cat.engines.find((e) => e.id === s.engine);
    clear(engineNote, !eng?.installed ? h("div", { class: "notice" }, icon("alert", 16), `El motor «${eng?.name}» no está instalado. Ve a Modelos para instalarlo.`) : eng.license ? h("div", { class: "notice" }, icon("info", 16), eng.license) : !eng.local ? h("div", { class: "notice info" }, icon("globe", 16), "Edge TTS usa el servicio en línea de Microsoft: el texto sale de tu PC. Incluye tiempos por palabra para subtítulos perfectos.") : null);
  };
  drawVoices();
  const gen = btn("Generar voz", { cls: "primary lg", icon: "mic" });
  const results = h("div", { class: "col" });
  const loadResults = async () => {
    const items = (await api.get("/api/media?kind=audio")).filter((m) => m.source === "tts").slice(0, 30);
    clear(results, items.length ? items.map((m) => h("div", { class: "audio-row" }, icon("mic", 16), h("div", { style: { width: "200px", minWidth: 0 } }, h("b", { class: "small", style: { display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, m.name), h("span", { class: "muted small" }, `${m.meta.voice || ""} · ${timeAgo(m.created)}`)), h("audio", { controls: true, preload: "none", src: fileUrl.media(m.id) }), btn("", { icon: "trash", cls: "ghost icon sm danger", onClick: async () => { await api.del(`/api/media/${m.id}`); loadResults(); } }))) : h("div", { class: "empty" }, "Tus voces generadas aparecerán aquí."));
  };
  gen.onclick = async () => {
    if (!text.value.trim()) return toast("Escribe el texto a narrar", "info");
    gen.classList.add("loading");
    try {
      await runJob(api.post("/api/tts", { text: text.value, engine: s.engine, voice: s.voice, speed: s.speed, pitch: s.pitch, lang: s.lang }));
      toast("Voz generada y guardada en la biblioteca", "ok");
      loadResults();
    } catch (e) {
      toast(e.message, "err", 8000);
    } finally {
      gen.classList.remove("loading");
    }
  };

  // Clonación (XTTS)
  const cloneName = h("input", { class: "input", placeholder: "Nombre de la voz (p. ej. «Mi voz»)" });
  const cloneSrc = h("div");
  const drawClone = async () => {
    const audios = await api.get("/api/media?kind=audio");
    clear(cloneSrc, select([["", "— Elige una grabación de 6-20 s —"], ...audios.map((a) => [a.id, a.name])], ""));
  };
  drawClone();
  const saveClone = btn("Guardar muestra", { icon: "check", cls: "sm" });
  saveClone.onclick = async () => {
    const id = cloneSrc.querySelector("select").value;
    if (!id || !cloneName.value.trim()) return toast("Elige una grabación y ponle nombre", "info");
    try {
      await api.post("/api/tts/clone-sample", { media_id: id, name: cloneName.value });
      toast("Muestra guardada. Elige el motor XTTS para usarla.", "ok");
      await import("../state.js").then((m) => m.refreshMeta());
    } catch (e) {
      toast(e.message, "err");
    }
  };

  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Voz ", h("span", { class: "grad-text" }, "IA")), h("p", {}, "Narraciones naturales para tus reels, generadas en tu PC."))),
    h("div", { class: "grid stagger", style: { gridTemplateColumns: "minmax(0,1.4fr) minmax(0,1fr)", gap: "18px" } },
      h("div", { class: "card col", style: { gap: "14px" } }, text, h("div", { class: "row" }, stats, h("div", { class: "spacer" }), gen)),
      h("div", { class: "card col", style: { gap: "14px" } },
        field("Motor", select(cat.engines.map((e) => [e.id, `${e.name}${e.installed ? "" : " · no instalado"}`]), s.engine, (v) => { s.engine = v; drawVoices(); })),
        engineNote,
        field("Velocidad", slider(s.speed, 0.6, 1.6, 0.05, (v) => (s.speed = v), (v) => `${v.toFixed(2)}×`)),
        pitchWrap,
        field("Idioma (XTTS)", segmented([["es", "ES"], ["en", "EN"], ["pt", "PT"], ["fr", "FR"], ["it", "IT"]], s.lang, (v) => (s.lang = v)))),
    ),
    h("div", { class: "section-title" }, "Voces"),
    voices,
    h("div", { class: "section-title" }, "Generadas"),
    results,
    h("div", { class: "section-title" }, "Clonar voz (XTTS-v2, opcional)"),
    h("div", { class: "card col", style: { gap: "12px" } },
      h("div", { class: "muted small" }, "Usa una grabación limpia de 6 a 20 segundos, sin música. Clona sólo voces que tengas derecho a usar."),
      h("div", { class: "grid g3" }, cloneSrc, cloneName, h("div", { class: "row" }, saveClone, btn("Importar grabación", { icon: "upload", cls: "sm ghost", onClick: async () => { await importMedia("audio"); drawClone(); } })))),
  );
  loadResults();
}
