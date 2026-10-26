// Vídeos exportados.
import { api, fileUrl } from "../api.js";
import { bridge, btn, clear, fmtBytes, h, icon, modal, timeAgo } from "../ui.js";

export async function render(view) {
  const list = h("div", { class: "col stagger" });
  view.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Exportados"), h("p", {}, "Tus vídeos listos para subir a TikTok, Reels y Shorts."))), list);
  const items = await api.get("/api/exports");
  clear(list, items.length ? items.map((f) => h("div", { class: "card row" },
    icon(f.name.endsWith(".mp4") ? "film" : "music", 20),
    h("div", { style: { flex: 1, minWidth: 0 } }, h("b", { style: { display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, f.name), h("span", { class: "muted small" }, `${fmtBytes(f.bytes)} · ${timeAgo(f.modified)}`)),
    f.name.endsWith(".mp4") ? btn("Ver", { icon: "play", cls: "sm", onClick: () => modal({ title: f.name, width: 520, body: h("video", { src: fileUrl.export(f.name), controls: true, autoplay: true, style: { width: "100%", maxHeight: "72vh", borderRadius: "12px", background: "#000" } }) }) }) : h("audio", { controls: true, src: fileUrl.export(f.name) }),
    bridge.showItemInFolder ? btn("Carpeta", { icon: "folder", cls: "sm ghost", onClick: () => bridge.showItemInFolder(f.path) }) : null,
    h("a", { class: "btn sm ghost", href: fileUrl.export(f.name), download: f.name }, icon("download", 14), "Descargar"))) : h("div", { class: "empty" }, "Todavía no has exportado ningún vídeo."));
}
