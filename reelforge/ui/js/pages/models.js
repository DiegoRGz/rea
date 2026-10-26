// Gestor de modelos, fuentes, paquetes opcionales y estado del LLM.
import { api, runJob } from "../api.js";
import { injectFonts } from "../captions.js";
import { refreshMeta, state } from "../state.js";
import { bridge, btn, clear, confirmDialog, h, icon, toast } from "../ui.js";

export async function render(view) {
  const root = h("div");
  view.append(h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Modelos"), h("p", {}, "Descarga los modelos que quieras usar. Se guardan en tu PC y funcionan sin conexión."))), root);
  const draw = async () => {
    const [data, sys] = await Promise.all([api.get("/api/models"), api.get("/api/system")]);
    const rec = sys.recommend;
    const groups = {};
    for (const m of data.models) (groups[m.group] ||= []).push(m);
    const totalGb = data.models.filter((m) => m.downloaded).reduce((a, m) => a + m.size_gb, 0);
    clear(root,
      h("div", { class: "grid g3 stagger" },
        h("div", { class: "card stat" }, h("span", { class: "muted small" }, "GPU"), h("b", {}, sys.torch.device || sys.gpu?.name || "No detectada"), h("span", { class: "muted small" }, sys.torch.vram_gb ? `${sys.torch.vram_gb} GB VRAM · perfil ${rec.tier}` : sys.torch.torch ? "PyTorch sin CUDA" : "PyTorch no instalado")),
        h("div", { class: "card stat" }, h("span", { class: "muted small" }, "Modelos descargados"), h("b", {}, `${data.models.filter((m) => m.downloaded).length} / ${data.models.length}`), h("span", { class: "muted small" }, `~${totalGb.toFixed(1)} GB en disco`)),
        h("div", { class: "card stat" }, h("span", { class: "muted small" }, "IA de texto"), h("b", {}, data.llm.provider === "ollama" ? (data.llm.ollama.running ? `Ollama · ${data.llm.model}` : "Ollama no iniciado") : data.llm.provider === "gemini" ? "Gemini" : "Plantillas"), h("span", { class: "muted small" }, data.llm.ollama.running ? `${data.llm.ollama.models.length} modelos locales` : "Opcional: guiones con IA"))),
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
  const dl = btn(m.downloaded ? "Descargado" : "Descargar", { icon: m.downloaded ? "check" : "download", cls: m.downloaded ? "sm" : "sm primary" });
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
    h("div", { class: "row" }, dl));
}

function extraCard(x, reload) {
  const b = btn(x.installed ? "Instalado" : "Instalar", { icon: x.installed ? "check" : "download", cls: x.installed ? "sm" : "sm primary" });
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
