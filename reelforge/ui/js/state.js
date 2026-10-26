// Estado global compartido entre páginas.
import { api } from "./api.js";
import { bridge, toast } from "./ui.js";

export const state = {
  meta: null,
  settings: null,
  health: null,
  system: null,
};

export async function refreshMeta() {
  [state.meta, state.settings, state.health] = await Promise.all([api.get("/api/meta"), api.get("/api/settings"), api.get("/api/health")]);
  return state;
}

/** Importa archivos a la biblioteca (diálogo nativo en Electron, <input> en navegador). */
export async function importMedia(kind = "all") {
  const filters = {
    all: [{ name: "Medios", extensions: ["mp4", "mov", "mkv", "webm", "png", "jpg", "jpeg", "webp", "mp3", "wav", "m4a", "ogg", "flac"] }],
    audio: [{ name: "Audio", extensions: ["mp3", "wav", "m4a", "ogg", "flac", "aac"] }],
    visual: [{ name: "Imagen/Vídeo", extensions: ["mp4", "mov", "mkv", "webm", "png", "jpg", "jpeg", "webp"] }],
  }[kind];
  try {
    if (bridge.pickFiles) {
      const paths = await bridge.pickFiles(filters);
      if (!paths?.length) return [];
      const items = await api.post("/api/media/import", { paths });
      toast(`${items.length} archivo(s) importado(s)`, "ok");
      return items;
    }
    const { pickFilesBrowser } = await import("./ui.js");
    const accept = { all: "video/*,image/*,audio/*", audio: "audio/*", visual: "video/*,image/*" }[kind];
    const files = await pickFilesBrowser(accept);
    if (!files.length) return [];
    const items = await api.upload(files);
    toast(`${items.length} archivo(s) importado(s)`, "ok");
    return items;
  } catch (e) {
    toast(e.message, "err");
    return [];
  }
}
