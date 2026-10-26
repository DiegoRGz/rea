// Google: Flow (web con tu cuenta) e Imagen/Veo por API.
import { api, fileUrl } from "../api.js";
import { go } from "../app.js";
import { state } from "../state.js";
import { bridge, btn, clear, h, icon, timeAgo } from "../ui.js";

export async function render(view) {
  const s = state.settings;
  const hasKey = !!s.gemini_api_key;
  const imported = h("div", { class: "gallery" });
  const load = async () => {
    const items = (await api.get("/api/media")).filter((m) => m.source === "flow" || m.source === "google").slice(0, 40);
    clear(imported, items.length ? items.map((m) => h("div", { class: "gal-item", style: m.thumb ? { backgroundImage: `url(${fileUrl.thumb(m.id)})` } : {}, title: `${m.name} · ${timeAgo(m.created)}` }, m.kind === "video" ? h("video", { src: fileUrl.media(m.id), muted: true, loop: true, preload: "metadata", onmouseenter: (e) => e.target.play(), onmouseleave: (e) => e.target.pause() }) : null)) : h("div", { class: "empty", style: { gridColumn: "1/-1" } }, "Lo que descargues de Flow o generes con la API aparecerá aquí."));
  };
  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Google ", h("span", { class: "grad-text" }, "Flow · Omni · Veo · Imagen")), h("p", {}, "Usa los modelos de Google junto a tu estudio local."))),
    h("div", { class: "grid g2 stagger" },
      h("div", { class: "card col", style: { gap: "12px" } },
        h("div", { class: "row" }, h("div", { class: "q-icon", style: { width: "42px", height: "42px", borderRadius: "12px", display: "grid", placeItems: "center", background: "rgba(124,92,255,.15)", color: "#c4b5fd" } }, icon("globe", 21)), h("div", {}, h("h3", {}, "Google Flow con tu cuenta"), h("div", { class: "muted small" }, "labs.google/flow"))),
        h("p", { class: "muted", style: { margin: 0 } }, "Abre Flow dentro de ReelForge e inicia sesión con tu cuenta de Google. Todo lo que descargues desde Flow se importa automáticamente a tu biblioteca, listo para el editor."),
        h("div", { class: "notice info" }, icon("info", 16), h("div", {}, "Flow no tiene una API pública: las generaciones se hacen en la propia web de Flow con los créditos de tu cuenta. ReelForge no automatiza ni lee tu sesión; sólo recoge los archivos que tú descargas.")),
        h("div", { class: "row" },
          btn(bridge.isElectron ? "Abrir Google Flow" : "Abrir Flow en el navegador", { cls: "primary", icon: "external", onClick: () => bridge.openFlow() }),
          !bridge.isElectron ? h("span", { class: "muted small" }, "En el navegador, importa luego tus descargas desde el editor.") : null)),
      h("div", { class: "card col", style: { gap: "12px" } },
        h("div", { class: "row" }, h("div", { class: "q-icon", style: { width: "42px", height: "42px", borderRadius: "12px", display: "grid", placeItems: "center", background: "rgba(255,77,157,.15)", color: "#f9a8d4" } }, icon("key", 21)), h("div", {}, h("h3", {}, "API de Gemini (Imagen, Omni Flash y Veo)"), h("div", { class: "muted small" }, "Los mismos modelos que usa Flow"))),
        h("p", { class: "muted", style: { margin: 0 } }, "Con una clave de Google AI Studio puedes generar imágenes (Imagen 4) y vídeos (Gemini Omni Flash o Veo) desde Generar o desde el Reel automático, sin salir de la app."),
        h("div", { class: "kv" }, h("span", {}, "Clave"), h("span", {}, hasKey ? h("span", { class: "badge ok" }, "configurada") : h("span", { class: "badge warn" }, "sin configurar")), h("span", {}, "Imagen"), h("code", { class: "inline" }, s.google_image_model), h("span", {}, "Vídeo"), h("code", { class: "inline" }, s.google_video_model)),
        h("div", { class: "row" }, btn("Configurar clave", { icon: "settings", onClick: () => go("settings") }), btn("Obtener clave", { icon: "external", cls: "ghost", onClick: () => bridge.openExternal("https://aistudio.google.com/apikey") }), hasKey ? btn("Generar", { icon: "sparkles", cls: "primary", onClick: () => go("generate", "video") }) : null)),
    ),
    h("div", { class: "section-title" }, "Importado de Google"),
    imported,
  );
  load();
  const off = bridge.onFlowDownload?.(() => load());
  return { destroy: () => typeof off === "function" && off() };
}
