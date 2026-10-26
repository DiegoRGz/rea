// Panel «Viral»: edición automática de retención, puntuación y B-roll/efectos.
import { api, fileUrl, runJob } from "../api.js";
import { state } from "../state.js";
import { btn, clear, field, h, icon, ring, segmented, select, slider, toast, toggle } from "../ui.js";

const OPTS_KEY = "rf-autoedit-opts";

function loadOpts() {
  const defaults = { cut_silences: true, remove_fillers: true, min_gap: 0.4, jump_zoom: true, keywords: true, emojis: true, punch_zooms: true, hook_effects: true, sfx: true, sfx_volume: 0.55, broll: "none", broll_every: 5, broll_duration: 1.8, beat_sync: true };
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(OPTS_KEY) || "{}") };
  } catch {
    return defaults;
  }
}

export function viralPanel(ed, body) {
  const o = loadOpts();
  const save = () => {
    try {
      localStorage.setItem(OPTS_KEY, JSON.stringify(o));
    } catch {
      /* almacenamiento no disponible */
    }
  };
  const opt = (key, label, hint) => h("div", { class: "toggle-row" }, h("div", {}, h("span", {}, label), hint ? h("div", { class: "muted small" }, hint) : null), toggle(o[key], (v) => { o[key] = v; save(); }));
  const run = btn("Aplicar edición viral", { icon: "zap", cls: "primary" });
  run.style.width = "100%";
  run.onclick = async () => {
    ed.save.flush();
    run.classList.add("loading");
    try {
      const rep = await runJob(api.post(`/api/projects/${ed.id}/auto-edit`, {
        ...o, whisper_model: state.settings.whisper_model, lang: state.settings.language, image_model: state.settings.image_model,
      }));
      await ed.reload();
      const bits = [rep.cuts ? `${rep.cuts} cortes` : null, rep.keywords ? `${rep.keywords} palabras clave` : null, rep.effects ? `${rep.effects} efectos` : null, rep.sfx ? `${rep.sfx} sonidos` : null, rep.broll ? `${rep.broll} B-roll` : null].filter(Boolean);
      toast(`Edición viral aplicada: ${bits.join(" · ") || "sin cambios"} · puntuación ${rep.score}`, "ok", 7000);
      ed.showTab("viral");
    } catch (e) {
      toast(e.message, "err", 9000);
    } finally {
      run.classList.remove("loading");
    }
  };
  const scoreBox = h("div");
  body.append(
    h("div", { class: "notice info" }, icon("sparkles", 16), h("div", {}, "Un clic: cortes de silencios, jump-zooms, palabras clave en color con emojis, zooms de impacto, efectos de sonido, B-roll y cortes al ritmo. Puedes repetirlo: sólo se rehace lo automático.")),
    run,
    scoreBox,
    h("div", { class: "label" }, "Ajustes de la edición"),
    opt("cut_silences", "Quitar silencios", "En clips de vídeo hablados"),
    opt("remove_fillers", "Quitar muletillas", "«eh», «em», «mmm»…"),
    field("Silencio mínimo a cortar", slider(o.min_gap, 0.2, 1.2, 0.05, (v) => { o.min_gap = v; save(); }, (v) => `${v.toFixed(2)} s`)),
    opt("jump_zoom", "Jump-zoom entre cortes", "Alterna 100 % / 112 %"),
    opt("keywords", "Palabras clave en color"),
    opt("emojis", "Emojis sobre los subtítulos"),
    opt("punch_zooms", "Zooms de impacto", "En las palabras clave"),
    opt("hook_effects", "Gancho con impacto", "Flash, temblor y golpe de bajo al inicio"),
    opt("sfx", "Efectos de sonido", "Whoosh, pop, boom y ding automáticos"),
    field("Volumen de efectos", slider(o.sfx_volume, 0.1, 1, 0.05, (v) => { o.sfx_volume = v; save(); }, (v) => `${Math.round(v * 100)}%`)),
    field("B-roll automático", segmented([["none", "No"], ["library", "Biblioteca"], ["generate", "Generar IA"]], o.broll, (v) => { o.broll = v; save(); })),
    field("Un B-roll cada", slider(o.broll_every, 3, 12, 0.5, (v) => { o.broll_every = v; save(); }, (v) => `${v} s`)),
    opt("beat_sync", "Cortes al ritmo de la música", "Ajusta los cortes entre imágenes al beat"),
  );
  renderScore(ed, scoreBox);
}

export async function renderScore(ed, box) {
  let s = ed.project.score;
  if (!s) {
    try {
      s = await api.get(`/api/projects/${ed.id}/score`);
      ed.project.score = s;
    } catch {
      return;
    }
  }
  const r = ring(96);
  requestAnimationFrame(() => r.set(s.score / 100));
  const color = s.score >= 85 ? "ok" : s.score >= 70 ? "accent" : s.score >= 50 ? "warn" : "err";
  clear(box, h("div", { class: "card", style: { padding: "14px", display: "flex", flexDirection: "column", gap: "10px" } },
    h("div", { class: "row" }, r, h("div", { class: "col", style: { gap: "4px" } }, h("span", { class: "label" }, "Puntuación de retención"), h("span", { class: `badge ${color}` }, s.grade), h("span", { class: "muted small" }, `${s.metrics.duration} s · cambio visual cada ${s.metrics.avg_shot} s`)),
      h("div", { class: "spacer" }), btn("", { icon: "refresh", cls: "ghost icon sm", title: "Recalcular", onClick: async () => { ed.save.flush(); ed.project.score = null; await new Promise((ok) => setTimeout(ok, 800)); renderScore(ed, box); } })),
    h("div", { class: "col", style: { gap: "6px" } }, s.checks.map((c) => h("div", { class: "row small", style: { alignItems: "flex-start", gap: "8px" } },
      h("span", { style: { color: c.ok ? "var(--ok)" : "var(--warn)", marginTop: "1px" } }, icon(c.ok ? "check" : "alert", 14)),
      h("div", {}, h("b", { style: { fontWeight: 600 } }, c.name), c.tip ? h("div", { class: "muted" }, c.tip) : null))))));
}

export function brollInspector(ed, root, b) {
  const m = ed.media.get(b.media_id);
  root.append(
    h("div", { class: "ins-head" }, h("div", { class: "ins-thumb", style: m?.thumb ? { backgroundImage: `url(${fileUrl.thumb(m.id)})` } : {} }), h("div", {}, h("b", {}, "B-roll"), h("div", { class: "muted small" }, m?.name || ""))),
    field("Aparece en", slider(b.start, 0, Math.max(1, ed.lay.total), 0.05, (v, f) => ed.change(() => (b.start = v), f), (v) => `${v.toFixed(2)} s`)),
    field("Duración", slider(b.duration, 0.4, 8, 0.05, (v, f) => ed.change(() => (b.duration = v), f), (v) => `${v.toFixed(2)} s`)),
    m?.kind === "image" ? field("Movimiento", select(Object.entries(ed.meta.motions), b.motion, (v) => ed.change(() => (b.motion = v)))) : null,
    field("Filtro", select(Object.entries(ed.meta.filters), b.filter || "none", (v) => ed.change(() => (b.filter = v)))),
  );
}

export function effectInspector(ed, root, e) {
  root.append(
    h("div", { class: "ins-head" }, h("div", { class: "ins-thumb", style: { display: "grid", placeItems: "center", color: "#fbbf24" } }, icon("zap", 20)), h("b", {}, "Efecto")),
    field("Tipo", segmented([["punch", "Zoom"], ["shake", "Temblor"], ["flash", "Flash"]], e.type, (v) => ed.change(() => (e.type = v)))),
    field("Momento", slider(e.start, 0, Math.max(1, ed.lay.total), 0.01, (v, f) => ed.change(() => (e.start = v), f), (v) => `${v.toFixed(2)} s`)),
    field("Duración", slider(e.duration, 0.05, 1.5, 0.01, (v, f) => ed.change(() => (e.duration = v), f), (v) => `${v.toFixed(2)} s`)),
    e.type !== "flash" ? field("Intensidad", slider(e.strength, 0.3, 2, 0.05, (v, f) => ed.change(() => (e.strength = v), f), (v) => `${v.toFixed(2)}×`)) : null,
  );
}

export function addEffectAtPlayhead(ed, type) {
  ed.checkpoint();
  const e = { id: Math.random().toString(16).slice(2, 12), type, start: Math.round(ed.player.t * 100) / 100, duration: type === "flash" ? 0.08 : 0.4, strength: 1, auto: false };
  ed.project.effects.push(e);
  ed.commit();
  ed.select("effect", e.id);
}
