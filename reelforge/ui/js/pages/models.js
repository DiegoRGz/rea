// Gestor de modelos, fuentes, paquetes opcionales y estado del LLM.
import { api, runJob } from "../api.js";
import { injectFonts } from "../captions.js";
import { refreshMeta, state } from "../state.js";
import { bridge, btn, clear, confirmDialog, fmtBytes, h, icon, segmented, toast } from "../ui.js";

export async function render(view) {
  const root = h("div");
  view.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Modelos"), h("p", {}, "Descarga los modelos que quieras usar. Se guardan en tu PC y funcionan sin conexión."))), root);
  const draw = async () => {
    const [data, sys] = await Promise.all([api.get("/api/models"), api.get("/api/system")]);
    const rec = sys.recommend;
    const groups = {};
    for (const m of data.models) (groups[m.group] ||= []).push(m);
    const totalGb = data.models.reduce((a, m) => a + (m.disk_gb || 0), 0);
    const cacheGb = Object.values(data.cache || {}).reduce((a, v) => a + v, 0);
    clear(root,
      h("div", { class: "grid g3 stagger" },
        h("div", { class: "card stat" }, h("span", { class: "muted small" }, "GPU"), h("b", {}, sys.torch.device || sys.gpu?.name || "No detectada"), h("span", { class: "muted small" }, sys.torch.vram_gb ? `${sys.torch.vram_gb} GB VRAM · perfil ${rec.tier}` : sys.torch.torch ? "PyTorch sin CUDA" : "PyTorch no instalado")),
        h("div", { class: "card stat" }, h("span", { class: "muted small" }, "Modelos descargados"), h("b", {}, `${data.models.filter((m) => m.downloaded).length} / ${data.models.length}`), h("span", { class: "muted small" }, `${totalGb.toFixed(1)} GB en disco · caché de renders ${cacheGb.toFixed(1)} GB`),
          cacheGb > 0.01 ? btn("Limpiar caché de renders", { icon: "trash", cls: "sm ghost", onClick: async () => {
            if (!(await confirmDialog("Limpiar caché", `Se borrarán ${cacheGb.toFixed(2)} GB de clips preprocesados y vistas previas. Se regeneran solos al exportar; tus proyectos, medios y exportaciones no se tocan.`, "Limpiar"))) return;
            const r = await api.post("/api/cache/clear");
            toast(`Liberados ${r.freed_gb} GB`, "ok");
            draw();
          } }) : null),
        h("div", { class: "card stat" }, h("span", { class: "muted small" }, "IA de texto"), h("b", {}, data.llm.provider === "ollama" ? (data.llm.ollama.running ? `Ollama · ${data.llm.model}` : "Ollama no iniciado") : data.llm.provider === "gemini" ? "Gemini" : "Plantillas"), h("span", { class: "muted small" }, data.llm.ollama.running ? `${data.llm.ollama.models.length} modelos locales` : "Opcional: guiones con IA"))),
      h("div", { class: "section-title" }, "Explorar Hugging Face · lo más nuevo"),
      hubExplorer(draw),
      h("div", { class: "section-title" }, "Paquetes"),
      h("div", { class: "grid g2" }, data.extras.map((x) => extraCard(x, draw))),
      ...Object.entries(groups).flatMap(([group, models]) => [h("div", { class: "section-title" }, group), h("div", { class: "grid g3 stagger" }, models.map((m) => modelCard(m, rec, draw)))]),
      h("div", { class: "section-title" }, "Fuentes para subtítulos"),
      fontsCard(data.fonts, draw),
      h("div", { class: "section-title" }, "Guiones con LLM local (Ollama)"),
      ollamaCard(data.llm),
    );
  };
  await draw();
}

function modelCard(m, rec, reload) {
  const recommended = [rec.image && `image:${rec.image}`, `whisper:${rec.whisper}`, rec.video && `video:${rec.video}`, "kokoro"].includes(m.id);
  const dl = btn(m.downloaded ? "Descargado" : m.partial ? "Completar descarga" : "Descargar", { icon: m.downloaded ? "check" : "download", cls: m.downloaded ? "sm" : "sm primary" });
  if (m.downloaded || !m.installed) dl.disabled = true;
  dl.onclick = async () => {
    dl.classList.add("loading");
    try {
      await runJob(api.post("/api/models/download", { id: m.id }));
      toast(`${m.name} listo`, "ok");
      reload();
    } catch (e) {
      toast(e.message, "err", 9000);
      dl.classList.remove("loading");
    }
  };
  return h("div", { class: "card model-card" },
    h("div", { class: "mc-head" }, h("div", { style: { flex: 1 } }, h("h3", {}, m.name), h("div", { class: "muted small", style: { marginTop: "4px" } }, m.desc)), recommended ? h("span", { class: "badge accent" }, "Recomendado") : null),
    h("div", { class: "row wrap" }, h("span", { class: "badge" }, `${m.size_gb} GB`), h("span", { class: `badge ${m.vram <= (state.system?.torch?.vram_gb || 8) ? "ok" : "warn"}` }, `VRAM ~${m.vram} GB`), h("span", { class: "badge" }, m.license), !m.installed ? h("span", { class: "badge warn" }, "falta paquete") : null),
    h("div", { class: "row" }, dl,
      m.disk_gb > 0 ? btn(`Eliminar (${fmtBytes(m.disk_gb * 1024 ** 3)})`, { icon: "trash", cls: "sm ghost danger", title: "Borra los archivos descargados de este modelo", onClick: async (e) => {
        const b = e.currentTarget; // capturado antes del await: currentTarget se anula al terminar el evento
        if (!(await confirmDialog("Eliminar modelo", `¿Borrar ${m.name} del disco (${fmtBytes(m.disk_gb * 1024 ** 3)})? Podrás volver a descargarlo cuando quieras.`, "Eliminar", true))) return;
        b.classList.add("loading");
        try {
          const r = await api.post("/api/models/delete", { id: m.id });
          toast(`${m.name}: liberados ${fmtBytes(r.freed_gb * 1024 ** 3)}${r.kept_shared.length ? " (se conservan archivos compartidos con otro modelo)" : ""}`, "ok", 6000);
          reload();
        } catch (err) {
          toast(err.message, "err", 8000);
          b.classList.remove("loading");
        }
      } }) : null,
      m.custom ? btn("Quitar de la lista", { icon: "x", cls: "sm ghost", onClick: async () => {
      if (!(await confirmDialog("Quitar modelo", `¿Quitar ${m.name} de la app? Los archivos descargados se conservan en la caché.`, "Quitar", true))) return;
      await api.post("/api/hub/remove", { id: m.id.slice(3) });
      await refreshMeta();
      reload();
    } }) : null));
}

const KIND_LABEL = { image: "Imagen", video: "Texto → vídeo", i2v: "Imagen → vídeo" };
const fmtNum = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)} M` : n >= 1e3 ? `${(n / 1e3).toFixed(1)} k` : String(n || 0));

/** Destacados recientes + búsqueda en vivo de los modelos en tendencia del Hub. */
function hubExplorer(reloadPage) {
  const st = { kind: "image", sort: "trending", q: "" };
  const featured = h("div", { class: "grid g3" });
  const results = h("div", { class: "col" });
  const search = h("input", { class: "input", placeholder: "Buscar modelo (p. ej. flux, wan, hunyuan, ltx)…", style: { maxWidth: "340px" } });
  let timer;
  search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => { st.q = search.value.trim(); load(); }, 450); });

  const add = async (button, repo, kind, extra = {}) => {
    button.classList.add("loading");
    try {
      await api.post("/api/hub/add", { repo, kind: kind === "image" ? "image" : "video", i2v: kind === "i2v", ...extra });
      await refreshMeta();
      toast(`${repo} añadido. Descárgalo abajo o úsalo directamente en Generar.`, "ok", 6000);
      reloadPage();
    } catch (e) {
      toast(e.message, "err");
      button.classList.remove("loading");
    }
  };

  api.get("/api/hub/featured").then((items) => clear(featured, items.map((f) => {
    const b = btn(f.added ? "Añadido" : "Añadir", { icon: f.added ? "check" : "plus", cls: f.added ? "sm" : "sm primary" });
    if (f.added) b.disabled = true;
    b.onclick = () => add(b, f.repo, f.kind === "video" ? (f.i2v ? "i2v" : "video") : "image", { name: f.name, size_gb: f.size_gb, license: f.license });
    return h("div", { class: "card model-card" },
      h("div", { class: "mc-head" }, h("div", { style: { flex: 1 } }, h("h3", {}, f.name), h("div", { class: "muted small", style: { marginTop: "4px" } }, f.note)), h("span", { class: "badge accent" }, "Nuevo")),
      h("div", { class: "row wrap" }, h("span", { class: "badge" }, f.kind === "image" ? "Imagen" : "Vídeo"), h("span", { class: "badge" }, `~${f.size_gb} GB`), h("span", { class: "badge" }, f.license)),
      h("div", { class: "row" }, b, btn("Ficha", { icon: "external", cls: "sm ghost", onClick: () => bridge.openExternal(`https://huggingface.co/${f.repo}`) })));
  })));

  const row = (m) => {
    const info = h("span", { class: "muted small" });
    const check = btn("Compatibilidad", { icon: "cpu", cls: "sm ghost" });
    const addBtn = btn(m.added ? "Añadido" : "Añadir", { icon: m.added ? "check" : "plus", cls: m.added ? "sm" : "sm primary" });
    if (m.added) addBtn.disabled = true;
    let details = null;
    check.onclick = async () => {
      check.classList.add("loading");
      try {
        details = await api.get(`/api/hub/info?repo=${encodeURIComponent(m.repo)}`);
        const cls = { ok: "ok", slow: "warn", no: "err" }[details.compat.level] || "";
        clear(info, h("span", { class: `badge ${cls}` }, details.compat.label), ` · pesos ~${details.size_gb} GB`, details.gated ? " · requiere aceptar la licencia y token de HF" : "", details.diffusers ? "" : " · no está en formato diffusers");
      } catch (e) {
        toast(e.message, "err");
      } finally {
        check.classList.remove("loading");
      }
    };
    addBtn.onclick = () => add(addBtn, m.repo, st.kind, details ? { size_gb: details.size_gb, license: details.license } : { license: m.license });
    return h("div", { class: "card row", style: { padding: "12px 14px" } },
      icon(st.kind === "image" ? "image" : "video", 18),
      h("div", { style: { flex: 1, minWidth: 0 } },
        h("div", { class: "row", style: { gap: "8px" } }, h("b", { style: { overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, m.repo), m.featured ? h("span", { class: "badge accent" }, "Destacado") : null),
        h("div", { class: "row wrap small muted", style: { gap: "10px", marginTop: "3px" } }, `♥ ${fmtNum(m.likes)}`, `↓ ${fmtNum(m.downloads)}`, m.created ? `publicado ${m.created.slice(0, 10)}` : "", m.license ? `licencia ${m.license}` : "", info)),
      check, addBtn, btn("", { icon: "external", cls: "ghost icon sm", title: "Abrir ficha", onClick: () => bridge.openExternal(`https://huggingface.co/${m.repo}`) }));
  };

  const load = async () => {
    clear(results, h("div", { class: "row muted small" }, h("div", { class: "spinner" }), "Consultando Hugging Face…"));
    try {
      const items = await api.get(`/api/hub/search?kind=${st.kind}&sort=${st.sort}&q=${encodeURIComponent(st.q)}&limit=20`);
      clear(results, items.length ? items.map(row) : h("div", { class: "empty" }, "Sin resultados."));
    } catch (e) {
      clear(results, h("div", { class: "notice" }, icon("alert", 16), e.message));
    }
  };
  load();
  return h("div", { class: "col", style: { gap: "14px" } },
    featured,
    h("div", { class: "row wrap" },
      segmented(Object.entries(KIND_LABEL), st.kind, (v) => { st.kind = v; load(); }),
      segmented([["trending", "Tendencia"], ["downloads", "Más descargados"], ["likes", "Más gustados"], ["recent", "Recientes"]], st.sort, (v) => { st.sort = v; load(); }),
      search),
    h("div", { class: "notice info" }, icon("info", 16), h("div", {}, "La lista se consulta en directo en Hugging Face, así que siempre verás los modelos más nuevos. Cualquier modelo en formato diffusers funciona con el cargador genérico; los que no caben en 8 GB se ejecutan descargando partes a la RAM (más lento). Si un modelo muy nuevo falla, pulsa «Actualizar motores de IA» en Paquetes.")),
    results);
}

function extraCard(x, reload) {
  const upgrade = x.id === "engines";
  const b = btn(upgrade ? "Actualizar" : x.installed ? "Instalado" : "Instalar", { icon: x.installed ? "check" : upgrade ? "refresh" : "download", cls: x.installed ? "sm" : "sm primary" });
  if (x.installed) b.disabled = true;
  b.onclick = async () => {
    if (!(await confirmDialog(`Instalar ${x.name}`, `Se ejecutará pip en el entorno de ReelForge. ${x.note}`, "Instalar"))) return;
    b.classList.add("loading");
    try {
      await runJob(api.post("/api/extras/install", { id: x.id }));
      toast(`${x.name} instalado. Reinicia la app para usarlo.`, "ok", 8000);
      reload();
    } catch (e) {
      toast(e.message, "err", 10000);
      b.classList.remove("loading");
    }
  };
  return h("div", { class: "card row" }, icon("box", 20), h("div", { style: { flex: 1 } }, h("b", {}, x.name), h("div", { class: "muted small" }, x.note)), b);
}

function fontsCard(fonts, reload) {
  const missing = fonts.filter((f) => !f.installed).length;
  const b = btn(missing ? `Descargar ${missing} fuentes` : "Fuentes instaladas", { icon: missing ? "download" : "check", cls: missing ? "sm primary" : "sm" });
  if (!missing) b.disabled = true;
  b.onclick = async () => {
    b.classList.add("loading");
    try {
      await runJob(api.post("/api/fonts/download"));
      await refreshMeta();
      injectFonts();
      toast("Fuentes instaladas", "ok");
      reload();
    } catch (e) {
      toast(e.message, "err");
      b.classList.remove("loading");
    }
  };
  return h("div", { class: "card col" },
    h("div", { class: "row wrap" }, fonts.map((f) => h("span", { class: `badge ${f.installed ? "ok" : ""}`, style: { fontFamily: `"${f.family}"` } }, f.family))),
    h("div", { class: "row" }, h("span", { class: "muted small" }, "Fuentes gratuitas (licencia OFL) de Google Fonts para los estilos virales. Sin ellas se usan Arial Black / Impact."), h("div", { class: "spacer" }), b));
}

function ollamaCard(llm) {
  return h("div", { class: "card col" },
    h("div", { class: "row" }, h("span", { class: `badge ${llm.ollama.running ? "ok" : "warn"}` }, h("span", { class: "dot" }), llm.ollama.running ? "Ollama en ejecución" : "Ollama no detectado"), llm.ollama.models.length ? h("span", { class: "muted small" }, llm.ollama.models.join(" · ")) : null),
    h("div", { class: "muted small" }, "Ollama es opcional y se instala aparte. Con 8 GB de VRAM se recomienda ", h("code", { class: "inline" }, "qwen3:8b"), " o ", h("code", { class: "inline" }, "gemma3:4b"), ". ReelForge libera la VRAM de Ollama tras cada guion."),
    h("div", { class: "row" }, h("code", { class: "inline" }, "ollama pull qwen3:8b"), h("div", { class: "spacer" }), btn("Descargar Ollama", { icon: "external", cls: "sm ghost", onClick: () => bridge.openExternal("https://ollama.com/download") })));
}
