// Generación de imágenes, vídeos y música (local o Google).
import { api, fileUrl, runJob } from "../api.js";
import { newProjectDialog } from "./home.js";
import { state } from "../state.js";
import { btn, clear, confirmDialog, field, h, icon, modal, segmented, select, slider, toast } from "../ui.js";

const STYLE_NAMES = { none: "Ninguno", cinematic: "Cinemático", photo: "Foto realista", anime: "Anime", "3d": "3D Pixar", comic: "Cómic", neon: "Neón", minimal: "Minimalista" };

export async function render(view, arg) {
  let tab = ["image", "video", "music"].includes(arg) ? arg : "image";
  const body = h("div");
  const gallery = h("div", { class: "gallery" });
  const draw = () => {
    clear(body);
    ({ image: imageTab, video: videoTab, music: musicTab })[tab](body, loadGallery);
    loadGallery();
  };
  const loadGallery = async () => {
    const all = await api.get("/api/media");
    const items = all.filter((m) => (tab === "music" ? m.source === "music" : m.kind === tab && ["image", "video", "google", "flow"].includes(m.source))).slice(0, 60);
    clear(gallery, items.length ? items.map((m) => galleryItem(m, loadGallery)) : h("div", { class: "empty", style: { gridColumn: "1/-1" } }, "Tus creaciones aparecerán aquí."));
  };
  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Generar con ", h("span", { class: "grad-text" }, "IA")), h("p", {}, "Todo lo que generes se guarda en la biblioteca para usarlo en el editor.")),
      segmented([["image", "🖼️ Imagen"], ["video", "🎬 Vídeo"], ["music", "🎵 Música"]], tab, (v) => { tab = v; draw(); })),
    body,
    h("div", { class: "section-title" }, "Resultados"),
    gallery,
  );
  draw();
}

function promptBox(placeholder) {
  const ta = h("textarea", { class: "textarea", placeholder, style: { minHeight: "110px", fontSize: "15px" } });
  const improve = btn("Mejorar prompt", { icon: "wand", cls: "sm ghost" });
  improve.onclick = async () => {
    if (!ta.value.trim()) return;
    improve.classList.add("loading");
    try {
      ta.value = (await runJob(api.post("/api/prompt/improve", { text: ta.value }))).prompt;
    } catch (e) {
      toast(e.message, "err");
    } finally {
      improve.classList.remove("loading");
    }
  };
  return { ta, improve };
}

function imageTab(body, reload) {
  const im = state.meta.image;
  const o = { provider: "local", model: state.settings.image_model in im.models ? state.settings.image_model : "sdxl-lightning", aspect: "9:16", count: 2, style: "cinematic", seed: "" };
  const { ta, improve } = promptBox("Un astronauta caminando por un mercado nocturno de Tokio, lluvia, luces de neón…");
  const opts = h("div", { class: "col", style: { gap: "14px" } });
  const drawOpts = () => clear(opts,
    field("Motor", segmented([["local", "Local (GPU)"], ["google", "Google Imagen"]], o.provider, (v) => { o.provider = v; drawOpts(); })),
    o.provider === "local" ? field("Modelo", select(Object.entries(im.models).map(([k, v]) => [k, v.name]), o.model, (v) => (o.model = v))) : null,
    field("Formato", segmented(im.aspects.map((a) => [a, a]), o.aspect, (v) => (o.aspect = v))),
    o.provider === "local" ? field("Estilo", select(im.styles.map((s) => [s, STYLE_NAMES[s] || s]), o.style, (v) => (o.style = v))) : null,
    field("Cantidad", slider(o.count, 1, 4, 1, (v) => (o.count = v))),
    o.provider === "local" ? field("Semilla (opcional)", h("input", { class: "input", type: "number", placeholder: "Aleatoria", value: o.seed, oninput: (e) => (o.seed = e.target.value) })) : null,
  );
  drawOpts();
  const go_ = btn("Generar imágenes", { cls: "primary lg", icon: "sparkles" });
  go_.onclick = async () => {
    if (!ta.value.trim()) return toast("Describe la imagen", "info");
    go_.classList.add("loading");
    try {
      if (o.provider === "google") await runJob(api.post("/api/google/image", { prompt: ta.value, aspect: o.aspect, count: o.count }));
      else await runJob(api.post("/api/image", { prompt: ta.value, model: o.model, aspect: o.aspect, count: o.count, style: o.style, seed: o.seed === "" ? null : Number(o.seed) }));
      toast("Imágenes listas", "ok");
      reload();
    } catch (e) {
      toast(e.message, "err", 9000);
    } finally {
      go_.classList.remove("loading");
    }
  };
  body.append(layoutTwo(h("div", { class: "card col", style: { gap: "12px" } }, ta, h("div", { class: "row" }, improve, h("div", { class: "spacer" }), go_)), h("div", { class: "card" }, opts)));
}

function videoTab(body, reload) {
  const vm = state.meta.video.models;
  const o = { provider: "local", model: "wan2.1-1.3b", seconds: 3, image: "", aspect: "9:16", gDuration: 0, gResolution: "" };
  const gModel = state.settings.google_video_model || "";
  const isOmni = gModel.startsWith("gemini-omni");
  const { ta, improve } = promptBox("Primer plano de una taza de café humeante, cámara lenta, luz de mañana…");
  const opts = h("div", { class: "col", style: { gap: "14px" } });
  const drawOpts = async () => {
    const images = (await api.get("/api/media?kind=image")).slice(0, 80);
    const needsImage = o.provider === "local" && vm[o.model]?.mode === "i2v";
    clear(opts,
      field("Motor", segmented([["local", "Local (GPU)"], ["google", isOmni ? "Google Omni Flash" : "Google Veo"]], o.provider, (v) => { o.provider = v; drawOpts(); })),
      o.provider === "local" ? field("Modelo", select(Object.entries(vm).map(([k, v]) => [k, v.name]), o.model, (v) => { o.model = v; drawOpts(); })) : field("Formato", segmented([["9:16", "9:16"], ["16:9", "16:9"]], o.aspect, (v) => (o.aspect = v))),
      o.provider === "local" ? field("Duración", slider(o.seconds, 1, 5, 0.5, (v) => (o.seconds = v), (v) => `${v} s`)) : null,
      o.provider === "google" && isOmni ? h("div", { class: "grid g2" },
        field("Duración", select([[0, "Automática"], ...[4, 6, 8, 10].map((n) => [n, `${n} s`])], o.gDuration, (v) => (o.gDuration = Number(v)))),
        field("Resolución", select([["", "Por defecto (720p)"], ["720p", "720p"], ["1080p", "1080p"], ["4k", "4K"]], o.gResolution, (v) => (o.gResolution = v)))) : null,
      field(needsImage ? "Imagen de partida (obligatoria)" : "Imagen de partida (opcional)", select([["", "— Ninguna —"], ...images.map((m) => [m.id, m.name])], o.image, (v) => (o.image = v))),
      o.provider === "local" ? h("div", { class: "notice" }, icon("clock", 16), h("div", {}, "En una RTX 5050 (8 GB) un clip de 3 s tarda varios minutos. Para reels rápidos usa imágenes con movimiento (Ken Burns) o Google Veo.")) : h("div", { class: "notice info" }, icon("cloud", 16), `${isOmni ? "Gemini Omni Flash" : "Veo"} genera en la nube de Google con tu clave de API (modelo ${gModel}; consulta precios en Google AI Studio). Cámbialo en Ajustes → Google.`),
    );
  };
  drawOpts();
  const go_ = btn("Generar vídeo", { cls: "primary lg", icon: "video" });
  go_.onclick = async () => {
    if (!ta.value.trim()) return toast("Describe el vídeo", "info");
    go_.classList.add("loading");
    try {
      if (o.provider === "google") await runJob(api.post("/api/google/video", { prompt: ta.value, aspect: o.aspect, image_media_id: o.image || null, duration: o.gDuration || null, resolution: o.gResolution || null }));
      else await runJob(api.post("/api/video", { prompt: ta.value, model: o.model, seconds: o.seconds, image_media_id: o.image || null }));
      toast("Vídeo listo", "ok");
      reload();
    } catch (e) {
      toast(e.message, "err", 9000);
    } finally {
      go_.classList.remove("loading");
    }
  };
  body.append(layoutTwo(h("div", { class: "card col", style: { gap: "12px" } }, ta, h("div", { class: "row" }, improve, h("div", { class: "spacer" }), go_)), h("div", { class: "card" }, opts)));
}

function musicTab(body, reload) {
  const o = { model: "musicgen-small", seconds: 20 };
  const ta = h("textarea", { class: "textarea", placeholder: "Lo-fi hip hop relajado con piano y batería suave, 85 bpm", style: { minHeight: "110px", fontSize: "15px" } });
  const presets = ["upbeat electronic pop, energetic, 120 bpm", "cinematic epic orchestral build up, drums", "chill lofi hip hop, piano, vinyl crackle", "dark suspense ambient, deep bass, tension", "happy acoustic ukulele, claps, summer"];
  const go_ = btn("Generar música", { cls: "primary lg", icon: "music" });
  go_.onclick = async () => {
    if (!ta.value.trim()) return toast("Describe la música", "info");
    go_.classList.add("loading");
    try {
      await runJob(api.post("/api/music", { prompt: ta.value, seconds: o.seconds, model: o.model }));
      toast("Música lista", "ok");
      reload();
    } catch (e) {
      toast(e.message, "err", 9000);
    } finally {
      go_.classList.remove("loading");
    }
  };
  body.append(layoutTwo(
    h("div", { class: "card col", style: { gap: "12px" } }, ta, h("div", { class: "chips" }, presets.map((p) => h("button", { class: "chip", onclick: () => (ta.value = p) }, p.split(",")[0]))), h("div", { class: "row" }, h("div", { class: "spacer" }), go_)),
    h("div", { class: "card col", style: { gap: "14px" } },
      field("Modelo", select(Object.entries(state.meta.music.models).map(([k, v]) => [k, v.name]), o.model, (v) => (o.model = v))),
      field("Duración", slider(o.seconds, 5, 30, 1, (v) => (o.seconds = v), (v) => `${v} s`)),
      h("div", { class: "notice" }, icon("info", 16), state.meta.music.license)),
  ));
}

function layoutTwo(a, b) {
  return h("div", { class: "grid stagger", style: { gridTemplateColumns: "minmax(0,1.5fr) minmax(0,1fr)", gap: "18px" } }, a, b);
}

function galleryItem(m, reload) {
  const media = m.kind === "video" ? h("video", { src: fileUrl.media(m.id), muted: true, loop: true, preload: "metadata", onmouseenter: (e) => e.target.play(), onmouseleave: (e) => e.target.pause() }) : m.kind === "audio" ? h("div", { style: { padding: "14px", height: "100%", display: "flex", flexDirection: "column", justifyContent: "center", gap: "10px" } }, icon("music", 28), h("b", { class: "small" }, m.name), h("audio", { controls: true, src: fileUrl.media(m.id), style: { width: "100%" } })) : null;
  const item = h("div", { class: "gal-item", style: m.kind === "image" ? { backgroundImage: `url(${fileUrl.thumb(m.id)})` } : m.kind === "audio" ? { aspectRatio: "1" } : {}, title: m.meta?.prompt || m.name }, media);
  item.append(h("div", { class: "gal-actions" },
    m.kind !== "audio" ? btn("", { icon: "eye", cls: "icon sm", title: "Ver", onClick: () => modal({ title: m.name, width: 520, body: m.kind === "video" ? h("video", { src: fileUrl.media(m.id), controls: true, autoplay: true, style: { width: "100%", borderRadius: "12px" } }) : h("img", { src: fileUrl.media(m.id), style: { width: "100%", borderRadius: "12px" } }) }) }) : null,
    btn("", { icon: "film", cls: "icon sm", title: "Nuevo proyecto", onClick: () => newProjectDialog() }),
    btn("", { icon: "trash", cls: "icon sm danger", title: "Eliminar", onClick: async () => { if (await confirmDialog("Eliminar", `¿Eliminar «${m.name}» de la biblioteca?`, "Eliminar", true)) { await api.del(`/api/media/${m.id}`); reload(); } } })));
  return item;
}

