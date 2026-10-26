// Editor de vídeo: biblioteca, vista previa, inspector, línea de tiempo y exportación.
import { api, fileUrl, runJob } from "../api.js";
import { go } from "../app.js";
import { styleCard } from "../captions.js";
import { Player } from "../editor/player.js";
import { Timeline } from "../editor/timeline.js";
import { addEffectAtPlayhead, brollInspector, effectInspector, viralPanel } from "../editor/viral.js";
import { CSS_FILTERS, layout, newAudio, newClip, TRANSITION_ANIM, uid } from "../editor/model.js";
import { importMedia, state } from "../state.js";
import { bridge, btn, clear, debounce, field, fmtBytes, fmtTime, h, icon, modal, ring, segmented, select, slider, toast, toggle, timeAgo } from "../ui.js";
import { newProjectDialog } from "./home.js";

export async function render(view, projectId) {
  if (!projectId) return picker(view);
  view.classList.add("full");
  const ed = new Editor(view, projectId);
  await ed.init();
  return ed;
}

async function picker(view) {
  const list = await api.get("/api/projects");
  view.append(
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Editor"), h("p", {}, "Abre un proyecto o crea uno nuevo.")), btn("Nuevo proyecto", { cls: "primary", icon: "plus", onClick: newProjectDialog })),
    list.length
      ? h("div", { class: "col stagger" }, list.map((p) => h("div", { class: "card hover row", onclick: () => go("editor", p.id) }, icon("film", 18), h("b", {}, p.name), h("span", { class: "spacer" }), h("span", { class: "muted small" }, `${fmtTime(p.duration, false)} · ${timeAgo(p.updated)}`), icon("chevronR", 16))))
      : h("div", { class: "empty" }, "No hay proyectos todavía."),
  );
}

class Editor {
  constructor(view, id) {
    this.view = view;
    this.id = id;
    this.meta = state.meta;
    this.media = new Map();
    this.sel = null;
    this.history = [];
    this.future = [];
    this.tab = "media";
    this.mediaFilter = "all";
    this.pending = false;
    this.save = debounce(() => this.persist(), 700);
    this.onKey = this.onKey.bind(this);
  }

  async init() {
    const [project, media] = await Promise.all([api.get(`/api/projects/${this.id}`), api.get("/api/media")]);
    delete project.duration;
    delete project.transitions_effective;
    this.project = project;
    media.forEach((m) => this.media.set(m.id, m));
    this.lay = layout(project, this.media);
    this.player = new Player(this);
    this.timeline = new Timeline(this);
    this.build();
    document.addEventListener("keydown", this.onKey);
    this.ro = new ResizeObserver(() => this.player.resize(this.canvas));
    this.ro.observe(this.canvas);
    this.onTime = (t) => {
      this.timeEl.textContent = `${fmtTime(t)} / ${fmtTime(this.lay.total)}`;
      this.timeline.updatePlayhead(t);
    };
    this.onPlayState = (p) => clear(this.playBtn, icon(p ? "pause" : "play", 18));
    this.refresh(false);
    this.renderPanel();
    this.renderInspector();
  }

  /** Recarga el proyecto del motor (tras la edición automática). */
  async reload() {
    const [project, media] = await Promise.all([api.get(`/api/projects/${this.id}`), api.get("/api/media")]);
    delete project.duration;
    delete project.transitions_effective;
    this.checkpoint();
    this.project = project;
    this.media.clear();
    media.forEach((m) => this.media.set(m.id, m));
    this.sel = null;
    this.wordsVersion = (this.wordsVersion || 0) + 1;
    this.refresh(false);
    this.renderInspector();
  }

  destroy() {
    document.removeEventListener("keydown", this.onKey);
    this.ro?.disconnect();
    this.player?.destroy();
    this.save.flush?.();
  }

  // ------------------------------------------------------------ estructura
  build() {
    this.nameInput = h("input", { class: "name", value: this.project.name, onchange: () => this.change(() => (this.project.name = this.nameInput.value || "Sin título"), true) });
    this.saveState = h("span", { class: "save-state" }, icon("check", 13), "Guardado");
    const top = h(
      "div",
      { class: "ed-top" },
      btn("", { icon: "chevronL", cls: "ghost icon sm", title: "Inicio", onClick: () => go("home") }),
      this.nameInput,
      this.saveState,
      h("div", { class: "spacer" }),
      btn("", { icon: "undo", cls: "ghost icon sm", title: "Deshacer (Ctrl+Z)", onClick: () => this.undo() }),
      btn("", { icon: "redo", cls: "ghost icon sm", title: "Rehacer (Ctrl+Y)", onClick: () => this.redo() }),
      btn("Vista previa real", { icon: "eye", cls: "sm", title: "Render rápido con transiciones", onClick: (e) => this.renderPreview(e.currentTarget) }),
      btn("Exportar", { icon: "download", cls: "primary sm", onClick: () => this.exportDialog() }),
    );
    this.tabsEl = h("div", { class: "panel-tabs" });
    this.panelBody = h("div", { class: "panel-body" });
    const left = h("div", { class: "panel" }, this.tabsEl, this.panelBody);
    this.canvas = h("div", { class: "stage-canvas" }, this.player.frame);
    this.playBtn = h("button", { class: "play-btn", onclick: () => this.player.toggle(), title: "Reproducir (Espacio)" }, icon("play", 18));
    this.timeEl = h("span", { class: "time" }, "00:00.00");
    const stage = h(
      "div",
      { class: "stage" },
      this.canvas,
      h("div", { class: "transport" },
        btn("", { icon: "chevronL", cls: "ghost icon sm", title: "Inicio", onClick: () => this.player.seek(0) }),
        this.playBtn,
        btn("", { icon: "chevronR", cls: "ghost icon sm", title: "Final", onClick: () => this.player.seek(this.lay.total) }),
        this.timeEl,
        btn("Zonas seguras", { icon: "eye", cls: "ghost sm", title: "Muestra dónde tapan la interfaz de TikTok/Reels/Shorts", onClick: (e) => { this.player.toggleSafe(); e.currentTarget.classList.toggle("on"); } })),
    );
    this.inspector = h("div", { class: "inspector" });
    const right = h("div", { class: "panel right" }, this.inspector);
    this.zoomInput = h("input", { type: "range", min: 12, max: 400, value: this.timeline.pps, class: "zoom", oninput: (e) => this.timeline.setZoom(Number(e.target.value)) });
    const tools = h(
      "div",
      { class: "tl-tools" },
      btn("Dividir", { icon: "scissors", cls: "ghost sm", title: "Dividir en el cabezal (S)", onClick: () => this.split() }),
      btn("Duplicar", { icon: "copy", cls: "ghost sm", title: "Ctrl+D", onClick: () => this.duplicate() }),
      btn("Eliminar", { icon: "trash", cls: "ghost sm danger", title: "Supr", onClick: () => this.removeSelected() }),
      btn("Zoom", { icon: "plus", cls: "ghost sm", title: "Zoom de impacto en el cabezal", onClick: () => addEffectAtPlayhead(this, "punch") }),
      btn("Temblor", { icon: "plus", cls: "ghost sm", title: "Temblor de cámara en el cabezal", onClick: () => addEffectAtPlayhead(this, "shake") }),
      btn("Flash", { icon: "plus", cls: "ghost sm", title: "Flash blanco en el cabezal", onClick: () => addEffectAtPlayhead(this, "flash") }),
      h("div", { class: "spacer" }),
      h("span", { class: "muted small" }, "Zoom"),
      this.zoomInput,
    );
    const tl = h("div", { class: "timeline" }, tools, this.timeline.scroll);
    clear(this.view, h("div", { class: "editor" }, top, h("div", { class: "ed-mid" }, left, stage, right), tl));
  }

  // ---------------------------------------------------------- cambios
  checkpoint() {
    this.history.push(JSON.stringify(this.project));
    if (this.history.length > 80) this.history.shift();
    this.future = [];
  }

  /** Aplica un cambio desde el inspector; `final` = fin de la interacción. */
  change(fn, final = true) {
    if (!this.pending) {
      this.checkpoint();
      this.pending = true;
    }
    fn();
    if (final) {
      this.pending = false;
      this.commit(false);
    } else this.refresh(false);
  }

  refresh(save = true) {
    this.lay = layout(this.project, this.media);
    this.timeline.render();
    this.player.render(true);
    if (save) this.save();
  }

  commit(rerenderInspector = true) {
    this.refresh(true);
    this.saveState.replaceChildren(h("span", { class: "spinner", style: { width: "11px", height: "11px" } }), "Guardando…");
    if (rerenderInspector) this.renderInspector();
  }

  async persist() {
    try {
      await api.put(`/api/projects/${this.id}`, this.project);
      this.saveState.replaceChildren(icon("check", 13), "Guardado");
    } catch (e) {
      this.saveState.replaceChildren(icon("alert", 13), "Error al guardar");
      toast(e.message, "err");
    }
  }

  undo() {
    if (!this.history.length) return;
    this.future.push(JSON.stringify(this.project));
    this.project = JSON.parse(this.history.pop());
    this.wordsVersion = (this.wordsVersion || 0) + 1;
    this.commit();
  }

  redo() {
    if (!this.future.length) return;
    this.history.push(JSON.stringify(this.project));
    this.project = JSON.parse(this.future.pop());
    this.wordsVersion = (this.wordsVersion || 0) + 1;
    this.commit();
  }

  select(type, id, rerender = true) {
    this.sel = type ? { type, id } : null;
    if (rerender) {
      this.timeline.render();
      this.renderInspector();
      if (["transitions", "filters"].includes(this.tab)) this.renderPanel();
    }
  }

  selectedObj() {
    if (!this.sel) return null;
    const list = { clip: this.project.clips, audio: this.project.audio, text: this.project.texts, broll: this.project.broll, effect: this.project.effects }[this.sel.type];
    return list?.find((x) => x.id === this.sel.id) || null;
  }

  onKey(e) {
    if (e.target.closest("input, textarea, select, [contenteditable]")) return;
    const k = e.key.toLowerCase();
    if (k === " ") { e.preventDefault(); this.player.toggle(); }
    else if ((e.ctrlKey || e.metaKey) && k === "z") { e.preventDefault(); e.shiftKey ? this.redo() : this.undo(); }
    else if ((e.ctrlKey || e.metaKey) && k === "y") { e.preventDefault(); this.redo(); }
    else if ((e.ctrlKey || e.metaKey) && k === "d") { e.preventDefault(); this.duplicate(); }
    else if (k === "delete" || k === "backspace") this.removeSelected();
    else if (k === "s" && !e.ctrlKey) this.split();
    else if (k === "arrowleft") this.player.seek(this.player.t - (e.shiftKey ? 1 : 1 / this.project.format.fps));
    else if (k === "arrowright") this.player.seek(this.player.t + (e.shiftKey ? 1 : 1 / this.project.format.fps));
    else if (k === "home") this.player.seek(0);
  }

  // ----------------------------------------------------------- acciones
  split() {
    const t = this.player.t;
    const it = this.lay.items.find((x) => t > x.start + 0.1 && t < x.visEnd - 0.1);
    if (!it) return toast("Coloca el cabezal sobre un clip para dividirlo", "info");
    this.checkpoint();
    const c = it.clip;
    const local = t - it.start;
    const b = JSON.parse(JSON.stringify(c));
    b.id = uid();
    if (c.kind === "image") {
      b.duration = Math.max(0.2, c.duration - local);
      c.duration = local;
    } else {
      const cut = c.src_in + local * c.speed;
      b.src_in = cut;
      c.src_out = cut;
    }
    c.transition = { type: "none", duration: c.transition.duration };
    this.project.clips.splice(it.index + 1, 0, b);
    this.commit();
    this.select("clip", b.id);
  }

  duplicate() {
    const obj = this.selectedObj();
    if (!obj) return;
    this.checkpoint();
    const copy = { ...JSON.parse(JSON.stringify(obj)), id: uid() };
    if (this.sel.type === "clip") this.project.clips.splice(this.project.clips.indexOf(obj) + 1, 0, copy);
    else if (this.sel.type === "audio") { copy.start = obj.start + 0.5; this.project.audio.push(copy); }
    else if (this.sel.type === "broll") { copy.start = obj.start + obj.duration; this.project.broll.push(copy); }
    else if (this.sel.type === "effect") { copy.start = obj.start + 1; this.project.effects.push(copy); }
    else { const d = obj.end - obj.start; copy.start = obj.end; copy.end = obj.end + d; this.project.texts.push(copy); }
    this.commit();
    this.select(this.sel.type, copy.id);
  }

  removeSelected() {
    const obj = this.selectedObj();
    if (!obj) return;
    this.checkpoint();
    const key = { clip: "clips", audio: "audio", text: "texts", broll: "broll", effect: "effects" }[this.sel.type];
    this.project[key] = this.project[key].filter((x) => x !== obj);
    this.sel = null;
    this.commit();
  }

  addClip(media) {
    this.checkpoint();
    const c = newClip(media);
    this.project.clips.push(c);
    this.commit();
    this.select("clip", c.id);
  }

  addAudio(media, role) {
    this.checkpoint();
    const a = newAudio(media, role, role === "music" ? 0 : Math.round(this.player.t * 20) / 20);
    this.project.audio.push(a);
    this.commit();
    this.select("audio", a.id);
  }

  addText(style) {
    this.checkpoint();
    const t = { id: uid(), text: style === "label" ? "NUEVO" : "Tu texto aquí", start: Math.round(this.player.t * 10) / 10, end: Math.round(this.player.t * 10) / 10 + 3, style, position: style === "label" ? 0.3 : 0.2, scale: 1 };
    this.project.texts.push(t);
    this.commit();
    this.select("text", t.id);
  }

  async reloadMedia() {
    const media = await api.get("/api/media");
    this.media.clear();
    media.forEach((m) => this.media.set(m.id, m));
    if (this.tab === "media" || this.tab === "audio") this.renderPanel();
  }

  // ------------------------------------------------------------ paneles
  showTab(tab) {
    this.tab = tab;
    this.renderPanel();
  }

  renderPanel() {
    const tabs = [["viral", "Viral", "zap"], ["media", "Medios", "image"], ["audio", "Audio", "music"], ["text", "Texto", "type"], ["captions", "Subs", "captions"], ["transitions", "Trans.", "shuffle"], ["filters", "Filtros", "palette"]];
    clear(this.tabsEl, tabs.map(([id, label, ic]) => h("button", { class: this.tab === id ? "on" : "", onclick: () => this.showTab(id) }, icon(ic, 17), label)));
    const body = h("div", { class: "col", style: { gap: "14px" } });
    clear(this.panelBody, body);
    this.panelBody.style.animation = "none";
    void this.panelBody.offsetWidth;
    this.panelBody.style.animation = "";
    ({ viral: () => viralPanel(this, body), media: () => this.mediaPanel(body), audio: () => this.audioPanel(body), text: () => this.textPanel(body), captions: () => this.captionsPanel(body), transitions: () => this.transitionsPanel(body), filters: () => this.filtersPanel(body) })[this.tab]();
  }

  mediaPanel(body) {
    const grid = h("div", { class: "media-grid" });
    const fill = () => {
      const items = [...this.media.values()].filter((m) => m.kind !== "audio" && (this.mediaFilter === "all" || m.kind === this.mediaFilter));
      if (!items.length) return clear(grid, h("div", { class: "empty", style: { gridColumn: "1 / -1" } }, "Importa o genera imágenes y vídeos."));
      clear(grid, items.map((m) => this.mediaTile(m)));
    };
    body.append(
      h("div", { class: "row" },
        btn("Importar", { icon: "upload", cls: "sm", onClick: async () => { await importMedia("visual"); await this.reloadMedia(); } }),
        btn("Generar", { icon: "wand", cls: "sm ghost", onClick: () => go("generate") })),
      segmented([["all", "Todo"], ["video", "Vídeo"], ["image", "Imagen"]], this.mediaFilter, (v) => { this.mediaFilter = v; fill(); }),
      grid,
    );
    fill();
  }

  mediaTile(m) {
    const tile = h("div", { class: "media-tile", draggable: "true", style: m.thumb ? { backgroundImage: `url(${fileUrl.thumb(m.id)})` } : {}, title: m.name },
      h("span", { class: "kind badge" }, m.kind === "video" ? icon("video", 11) : icon("image", 11)),
      h("button", { class: "add", title: "Añadir al final", onclick: (e) => { e.stopPropagation(); this.addClip(m); } }, icon("plus", 15)),
      h("div", { class: "mt-meta" }, h("span", {}, m.name), m.duration ? h("span", {}, fmtTime(m.duration, false)) : null));
    tile.addEventListener("dragstart", (e) => { e.dataTransfer.setData("text/x-media", m.id); e.dataTransfer.effectAllowed = "copy"; });
    tile.addEventListener("dblclick", () => this.addClip(m));
    return tile;
  }

  audioPanel(body) {
    const list = h("div", { class: "col" });
    const audios = [...this.media.values()].filter((m) => m.kind === "audio");
    for (const m of audios) {
      const row = h("div", { class: "card", style: { padding: "10px", display: "flex", flexDirection: "column", gap: "8px" }, draggable: "true" },
        h("div", { class: "row" }, icon(m.source === "music" ? "music" : "mic", 15), h("b", { style: { flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: "12.5px" } }, m.name), h("span", { class: "muted small" }, fmtTime(m.duration, false))),
        h("audio", { controls: true, preload: "none", src: fileUrl.media(m.id), style: { width: "100%", height: "30px" } }),
        h("div", { class: "row" }, btn("Voz", { icon: "plus", cls: "sm", onClick: () => this.addAudio(m, "voice") }), btn("Música", { icon: "plus", cls: "sm", onClick: () => this.addAudio(m, "music") })));
      row.addEventListener("dragstart", (e) => e.dataTransfer.setData("text/x-media", m.id));
      list.append(row);
    }
    body.append(
      h("div", { class: "row wrap" },
        btn("Importar audio", { icon: "upload", cls: "sm", onClick: async () => { await importMedia("audio"); await this.reloadMedia(); } }),
        btn("Generar voz", { icon: "mic", cls: "sm ghost", onClick: () => go("voice") }),
        btn("Generar música", { icon: "music", cls: "sm ghost", onClick: () => go("generate", "music") })),
      audios.length ? list : h("div", { class: "empty" }, "Sin audios todavía."),
      h("div", { class: "toggle-row" }, h("span", {}, "Ducking (bajar música cuando hay voz)"), toggle(this.project.ducking, (v) => this.change(() => (this.project.ducking = v)))),
      h("div", { class: "toggle-row" }, h("span", {}, "Normalizar volumen (-14 LUFS)"), toggle(this.project.loudnorm, (v) => this.change(() => (this.project.loudnorm = v)))),
    );
  }

  textPanel(body) {
    const presets = [["title", "Título", "Caja negra, texto blanco"], ["label", "Etiqueta", "Amarillo llamativo"], ["outline", "Contorno", "Texto con borde"]];
    body.append(
      h("div", { class: "label" }, "Añadir texto en el cabezal"),
      h("div", { class: "col" }, presets.map(([id, name, desc]) => h("div", { class: "option-card", onclick: () => this.addText(id) }, h("b", {}, name), h("p", {}, desc)))),
      h("div", { class: "notice info" }, icon("info", 16), h("div", {}, "Usa ", h("code", { class: "inline" }, "|"), " para saltos de línea. Los textos se animan con un pop de entrada.")),
    );
  }

  captionsPanel(body) {
    const cap = this.project.captions;
    const styles = h("div", { class: "grid g2" });
    const drawStyles = () => clear(styles, Object.keys(this.meta.caption_styles).map((id) => styleCard(id, cap.style === id, (sid) => {
      const st = this.meta.caption_styles[sid];
      this.change(() => { cap.style = sid; cap.max_words = st.max_words; cap.uppercase = st.uppercase; });
      drawStyles();
      this.renderPanel();
    })));
    drawStyles();
    const voiceItems = this.project.audio.filter((a) => a.role === "voice");
    const videoClips = this.project.clips.filter((c) => c.kind === "video" && this.media.get(c.media_id)?.has_audio);
    const transcribeBtn = btn("Generar desde la voz", { icon: "sparkles", cls: "primary sm", onClick: () => this.autoCaptions(transcribeBtn) });
    if (!voiceItems.length && !videoClips.length) transcribeBtn.disabled = true;
    const words = h("div", { class: "words" });
    cap.words.slice(0, 400).forEach((w, i) => {
      const el = h("span", { class: `word ${w.emph ? "emph" : ""}`, contenteditable: "true", spellcheck: "false", title: "Clic: editar · Clic derecho: palabra clave · Alt+clic: emoji", dataset: { emoji: w.emoji || "" } }, w.w);
      el.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        this.change(() => { cap.words[i].emph = !cap.words[i].emph; this.wordsVersion = (this.wordsVersion || 0) + 1; });
        el.classList.toggle("emph", !!cap.words[i].emph);
      });
      el.addEventListener("click", (e) => {
        if (!e.altKey) return;
        e.preventDefault();
        const v = prompt("Emoji para esta palabra (vacío para quitarlo):", cap.words[i].emoji || "");
        if (v === null) return;
        this.change(() => { cap.words[i].emoji = v.trim() || null; this.wordsVersion = (this.wordsVersion || 0) + 1; });
        el.dataset.emoji = v.trim();
      });
      el.addEventListener("blur", () => {
        const v = el.textContent.trim();
        if (v && v !== w.w) this.change(() => { cap.words[i].w = v; this.wordsVersion = (this.wordsVersion || 0) + 1; });
      });
      el.addEventListener("keydown", (e) => e.key === "Enter" && (e.preventDefault(), el.blur()));
      el.addEventListener("focus", () => this.player.seek(w.s));
      words.append(el);
    });
    body.append(
      h("div", { class: "toggle-row" }, h("b", {}, "Subtítulos animados"), toggle(cap.enabled, (v) => this.change(() => (cap.enabled = v)))),
      transcribeBtn,
      h("div", { class: "muted small" }, voiceItems.length ? "Transcribe la pista de voz con Whisper (tiempos por palabra)." : videoClips.length ? "Transcribe el audio de tus clips de vídeo." : "Añade una voz o un vídeo con audio para generar subtítulos."),
      h("div", { class: "label" }, "Estilo"),
      styles,
      field("Palabras por bloque", slider(cap.max_words, 1, 6, 1, (v, f) => this.change(() => (cap.max_words = v), f))),
      field("Posición vertical", slider(cap.position, 0.1, 0.92, 0.01, (v, f) => this.change(() => (cap.position = v), f), (v) => `${Math.round(v * 100)}%`)),
      field("Tamaño", slider(cap.scale, 0.6, 1.6, 0.05, (v, f) => this.change(() => (cap.scale = v), f), (v) => `${v.toFixed(2)}×`)),
      h("div", { class: "toggle-row" }, h("span", {}, "MAYÚSCULAS"), toggle(cap.uppercase, (v) => this.change(() => (cap.uppercase = v)))),
      cap.words.length ? h("div", { class: "label" }, `Texto (${cap.words.length} palabras · clic para editar)`) : null,
      cap.words.length ? words : null,
      cap.words.length ? h("div", { class: "row" },
        h("a", { class: "btn sm ghost", href: fileUrl.withToken(`/api/projects/${this.id}/subtitles.srt`), download: `${this.project.name}.srt` }, icon("download", 14), "SRT"),
        h("a", { class: "btn sm ghost", href: fileUrl.withToken(`/api/projects/${this.id}/subtitles.vtt`), download: `${this.project.name}.vtt` }, icon("download", 14), "VTT"),
        h("a", { class: "btn sm ghost", href: fileUrl.withToken(`/api/projects/${this.id}/subtitles.ass`), download: `${this.project.name}.ass` }, icon("download", 14), "ASS")) : null,
    );
  }

  async autoCaptions(button) {
    const voice = this.project.audio.find((a) => a.role === "voice");
    button.classList.add("loading");
    try {
      let words = [];
      if (voice) {
        const media = this.media.get(voice.media_id);
        const res = media.meta?.words?.length ? { words: media.meta.words } : await runJob(api.post("/api/transcribe", { media_id: voice.media_id, model: state.settings.whisper_model, language: state.settings.language }));
        const end = voice.src_out ?? media.duration ?? 1e9;
        words = res.words.filter((w) => w.s >= voice.src_in && w.s < end).map((w) => ({ w: w.w, s: +(w.s - voice.src_in + voice.start).toFixed(3), e: +(w.e - voice.src_in + voice.start).toFixed(3) }));
      } else {
        for (const it of this.lay.items.filter((x) => x.clip.kind === "video" && this.media.get(x.clip.media_id)?.has_audio)) {
          const res = await runJob(api.post("/api/transcribe", { media_id: it.clip.media_id, model: state.settings.whisper_model, language: state.settings.language }));
          const c = it.clip;
          for (const w of res.words) {
            if (w.s < c.src_in || w.s >= (c.src_out ?? 1e9)) continue;
            words.push({ w: w.w, s: +(it.start + (w.s - c.src_in) / c.speed).toFixed(3), e: +(it.start + (w.e - c.src_in) / c.speed).toFixed(3) });
          }
        }
      }
      this.change(() => { this.project.captions.words = words; this.project.captions.enabled = true; this.wordsVersion = (this.wordsVersion || 0) + 1; });
      toast(`Subtítulos generados: ${words.length} palabras`, "ok");
      this.renderPanel();
    } catch (e) {
      toast(e.message, "err", 8000);
    } finally {
      button.classList.remove("loading");
    }
  }

  transitionsPanel(body) {
    const clip = this.sel?.type === "clip" ? this.selectedObj() : null;
    const idx = clip ? this.project.clips.indexOf(clip) : -1;
    const isLast = idx === this.project.clips.length - 1;
    const current = clip?.transition?.type || "none";
    const tiles = h("div", { class: "tiles" }, Object.entries(this.meta.transitions).map(([id, name]) =>
      h("div", { class: `tile ${current === id ? "on" : ""}`, onclick: () => {
        if (!clip) return toast("Selecciona un clip: la transición se aplica a su salida", "info");
        if (isLast) return toast("El último clip no tiene transición de salida", "info");
        this.change(() => (clip.transition = { type: id, duration: clip.transition?.duration || 0.5 }));
        this.renderPanel();
      } }, h("div", { class: "tp", style: { "--anim": TRANSITION_ANIM[id] || "tpFade" } }), name)));
    body.append(
      clip ? h("div", { class: "muted small" }, isLast ? "Último clip: no hay transición de salida." : `Transición entre el clip ${idx + 1} y el ${idx + 2}`) : h("div", { class: "notice info" }, icon("info", 16), "Selecciona un clip en la línea de tiempo."),
      clip && !isLast ? field("Duración", slider(clip.transition.duration, 0.1, 1.5, 0.05, (v, f) => this.change(() => (clip.transition.duration = v), f), (v) => `${v.toFixed(2)} s`)) : null,
      tiles,
      btn("Aplicar a todos los clips", { icon: "layers", cls: "sm", onClick: () => {
        const t = clip?.transition?.type && clip.transition.type !== "none" ? clip.transition : { type: "fade", duration: 0.4 };
        this.change(() => this.project.clips.slice(0, -1).forEach((c) => (c.transition = { ...t })));
        toast(`Transición «${this.meta.transitions[t.type]}» aplicada a todos`, "ok");
        this.renderPanel();
      } }),
      h("div", { class: "muted small" }, "Las transiciones se generan con FFmpeg (xfade). Usa «Vista previa real» para verlas."),
    );
  }

  filtersPanel(body) {
    const clip = this.sel?.type === "clip" ? this.selectedObj() : null;
    const m = clip ? this.media.get(clip.media_id) : null;
    const thumb = m?.thumb ? fileUrl.thumb(m.id) : null;
    body.append(
      clip ? null : h("div", { class: "notice info" }, icon("info", 16), "Selecciona un clip para aplicarle un filtro."),
      h("div", { class: "tiles" }, Object.entries(this.meta.filters).map(([id, name]) =>
        h("div", { class: `tile ${clip?.filter === id ? "on" : ""}`, onclick: () => { if (clip) { this.change(() => (clip.filter = id)); this.renderPanel(); } } },
          h("div", { class: "tp still", style: { background: thumb ? `url(${thumb}) center/cover` : "linear-gradient(135deg,#7c5cff,#ff8a3d)", filter: CSS_FILTERS[id] } }), name))),
      btn("Aplicar a todos", { icon: "layers", cls: "sm", onClick: () => clip && this.change(() => this.project.clips.forEach((c) => (c.filter = clip.filter))) }),
    );
  }

  // ---------------------------------------------------------- inspector
  renderInspector() {
    const obj = this.selectedObj();
    const root = this.inspector;
    clear(root);
    if (!obj) return this.projectInspector(root);
    if (this.sel.type === "clip") this.clipInspector(root, obj);
    else if (this.sel.type === "audio") this.audioInspector(root, obj);
    else if (this.sel.type === "broll") brollInspector(this, root, obj);
    else if (this.sel.type === "effect") effectInspector(this, root, obj);
    else this.textInspector(root, obj);
    root.append(h("div", { class: "row" }, btn("Duplicar", { icon: "copy", cls: "sm", onClick: () => this.duplicate() }), btn("Eliminar", { icon: "trash", cls: "sm danger", onClick: () => this.removeSelected() })));
  }

  projectInspector(root) {
    const p = this.project;
    root.append(
      h("div", { class: "ins-head" }, h("div", { class: "q-icon", style: { width: "40px", height: "40px", borderRadius: "10px", display: "grid", placeItems: "center", background: "rgba(124,92,255,.15)", color: "#c4b5fd" } }, icon("film", 19)), h("div", {}, h("b", {}, "Proyecto"), h("div", { class: "muted small" }, `${p.format.width}×${p.format.height} · ${fmtTime(this.lay.total)}`))),
      field("Fotogramas por segundo", segmented([[24, "24"], [30, "30"], [60, "60"]], p.format.fps, (v) => this.change(() => (p.format.fps = v)))),
      h("div", { class: "toggle-row" }, h("div", {}, h("span", {}, "Kit de marca"), h("div", { class: "muted small" }, "Logo y @usuario al exportar (Ajustes → Marca)")), toggle(p.brand !== false, (v) => this.change(() => (p.brand = v)))),
      h("div", { class: "kv" }, h("span", {}, "Clips"), h("span", {}, p.clips.length), h("span", {}, "Pistas de audio"), h("span", {}, p.audio.length), h("span", {}, "Textos"), h("span", {}, p.texts.length), h("span", {}, "Palabras subtituladas"), h("span", {}, p.captions.words.length)),
      p.script?.hashtags ? h("div", { class: "card", style: { padding: "12px" } }, h("div", { class: "label" }, "Descripción sugerida"), h("p", { class: "small", style: { userSelect: "text" } }, p.script.caption || "", " ", (p.script.hashtags || []).join(" "))) : null,
      h("div", { class: "notice info" }, icon("info", 16), h("div", {}, "Atajos: ", h("span", { class: "kbd" }, "Espacio"), " reproducir, ", h("span", { class: "kbd" }, "S"), " dividir, ", h("span", { class: "kbd" }, "Supr"), " eliminar, ", h("span", { class: "kbd" }, "Ctrl+Z"), " deshacer, ", h("span", { class: "kbd" }, "Ctrl+rueda"), " zoom.")),
    );
  }

  clipInspector(root, c) {
    const m = this.media.get(c.media_id);
    const idx = this.project.clips.indexOf(c);
    root.append(h("div", { class: "ins-head" }, h("div", { class: "ins-thumb", style: m?.thumb ? { backgroundImage: `url(${fileUrl.thumb(m.id)})` } : {} }), h("div", { style: { minWidth: 0 } }, h("b", { style: { display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, m?.name || "Clip"), h("div", { class: "muted small" }, `Clip ${idx + 1} · ${c.kind === "video" ? "vídeo" : "imagen"}`))));
    if (c.kind === "image") {
      root.append(field("Duración", slider(c.duration, 0.3, 20, 0.1, (v, f) => this.change(() => (c.duration = v), f), (v) => `${v.toFixed(1)} s`)));
      root.append(field("Movimiento (Ken Burns)", select(Object.entries(this.meta.motions), c.motion, (v) => this.change(() => (c.motion = v)))));
    } else {
      const full = m?.duration || 0;
      root.append(
        field("Inicio en el clip", slider(c.src_in, 0, Math.max(0.1, full - 0.2), 0.05, (v, f) => this.change(() => (c.src_in = Math.min(v, (c.src_out ?? full) - 0.2)), f), (v) => `${v.toFixed(2)} s`)),
        field("Fin en el clip", slider(c.src_out ?? full, 0.2, Math.max(0.2, full), 0.05, (v, f) => this.change(() => (c.src_out = Math.max(v, c.src_in + 0.2)), f), (v) => `${v.toFixed(2)} s`)),
        field("Velocidad", slider(c.speed, 0.25, 3, 0.05, (v, f) => this.change(() => (c.speed = v), f), (v) => `${v.toFixed(2)}×`)),
        field("Volumen del clip", slider(c.volume, 0, 2, 0.05, (v, f) => this.change(() => (c.volume = v), f), (v) => `${Math.round(v * 100)}%`)),
      );
    }
    root.append(
      field("Encuadre", segmented([["cover", "Llenar"], ["blur", "Fondo difuminado"], ["contain", "Ajustar"]], c.fit, (v) => this.change(() => (c.fit = v)))),
      field("Filtro de color", select(Object.entries(this.meta.filters), c.filter, (v) => this.change(() => (c.filter = v)))),
    );
    if (idx < this.project.clips.length - 1) {
      root.append(
        field("Transición de salida", select(Object.entries(this.meta.transitions), c.transition.type, (v) => this.change(() => (c.transition.type = v)))),
        c.transition.type !== "none" ? field("Duración de la transición", slider(c.transition.duration, 0.1, 1.5, 0.05, (v, f) => this.change(() => (c.transition.duration = v), f), (v) => `${v.toFixed(2)} s`)) : null,
      );
    }
  }

  audioInspector(root, a) {
    const m = this.media.get(a.media_id);
    root.append(
      h("div", { class: "ins-head" }, h("div", { class: "ins-thumb", style: { display: "grid", placeItems: "center", color: "#a78bfa" } }, icon(a.role === "music" ? "music" : "mic", 20)), h("div", { style: { minWidth: 0 } }, h("b", { style: { display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, m?.name || "Audio"), h("div", { class: "muted small" }, fmtTime(m?.duration || 0)))),
      field("Tipo de pista", segmented([["voice", "Voz"], ["music", "Música"], ["sfx", "Efecto"]], a.role, (v) => this.change(() => (a.role = v)))),
      field("Volumen", slider(a.volume, 0, 2, 0.01, (v, f) => this.change(() => (a.volume = v), f), (v) => `${Math.round(v * 100)}%`)),
      field("Empieza en", slider(a.start, 0, Math.max(1, this.lay.total), 0.05, (v, f) => this.change(() => (a.start = v), f), (v) => `${v.toFixed(2)} s`)),
      field("Fundido de entrada", slider(a.fade_in, 0, 5, 0.1, (v, f) => this.change(() => (a.fade_in = v), f), (v) => `${v.toFixed(1)} s`)),
      field("Fundido de salida", slider(a.fade_out, 0, 5, 0.1, (v, f) => this.change(() => (a.fade_out = v), f), (v) => `${v.toFixed(1)} s`)),
      h("div", { class: "toggle-row" }, h("span", {}, "Repetir hasta el final"), toggle(a.loop, (v) => this.change(() => (a.loop = v)))),
    );
  }

  textInspector(root, t) {
    const ta = h("textarea", { class: "textarea", style: { minHeight: "70px" }, value: t.text });
    ta.addEventListener("input", () => this.change(() => (t.text = ta.value), false));
    ta.addEventListener("change", () => this.change(() => (t.text = ta.value), true));
    root.append(
      h("div", { class: "ins-head" }, h("div", { class: "ins-thumb", style: { display: "grid", placeItems: "center", color: "#f9a8d4" } }, icon("type", 20)), h("b", {}, "Texto")),
      field("Contenido", ta),
      field("Estilo", segmented([["title", "Título"], ["label", "Etiqueta"], ["outline", "Contorno"]], t.style, (v) => this.change(() => (t.style = v)))),
      field("Posición vertical", slider(t.position, 0.05, 0.95, 0.01, (v, f) => this.change(() => (t.position = v), f), (v) => `${Math.round(v * 100)}%`)),
      field("Tamaño", slider(t.scale, 0.4, 2, 0.05, (v, f) => this.change(() => (t.scale = v), f), (v) => `${v.toFixed(2)}×`)),
      field("Aparece", slider(t.start, 0, Math.max(1, this.lay.total), 0.05, (v, f) => this.change(() => { const d = t.end - t.start; t.start = v; t.end = v + d; }, f), (v) => `${v.toFixed(2)} s`)),
      field("Duración", slider(t.end - t.start, 0.2, 15, 0.05, (v, f) => this.change(() => (t.end = t.start + v), f), (v) => `${v.toFixed(2)} s`)),
    );
  }

  // ------------------------------------------------- render y exportación
  async renderPreview(button) {
    this.save.flush();
    button.classList.add("loading");
    try {
      const res = await runJob(api.post(`/api/projects/${this.id}/preview`));
      const v = h("video", { src: fileUrl.withToken(res.url), controls: true, autoplay: true, style: { width: "100%", maxHeight: "70vh", borderRadius: "12px", background: "#000" } });
      modal({ title: "Vista previa (540p)", body: v, width: 520 });
    } catch (e) {
      toast(e.message, "err", 8000);
    } finally {
      button.classList.remove("loading");
    }
  }

  exportDialog() {
    this.save.flush();
    const meta = this.meta;
    const opts = { preset: state.settings.export_preset || "tiktok", resolution: "1080p", fps: this.project.format.fps, codec: "h264", quality: "high", hardware: true, subtitles_file: false, thumbnail: true, audio_only: false, cover_text: this.project.script?.hook || "" };
    const apply = (id) => {
      opts.preset = id;
      if (meta.export_presets[id]) Object.assign(opts, { resolution: meta.export_presets[id].resolution, fps: meta.export_presets[id].fps, codec: meta.export_presets[id].codec, quality: meta.export_presets[id].quality });
      draw();
    };
    const body = h("div", { class: "col", style: { gap: "16px" } });
    const nvenc = state.health.ffmpeg.nvenc;
    const draw = () => {
      clear(body,
        h("div", { class: "label" }, "Plataforma"),
        h("div", { class: "grid g3" }, [...Object.entries(meta.export_presets), ["custom", { name: "Personalizado", resolution: "", fps: "", codec: "" }]].map(([id, p]) =>
          h("div", { class: `option-card ${opts.preset === id ? "on" : ""}`, onclick: () => apply(id) }, h("b", {}, p.name), h("p", {}, id === "custom" ? "Elige cada ajuste" : `${p.resolution} · ${p.fps} fps · ${p.codec.toUpperCase()}`)))),
        h("div", { class: "grid g2" },
          field("Resolución", select(meta.resolutions.map((r) => [r, r === "2160p" ? "4K (2160p)" : r]), opts.resolution, (v) => { opts.resolution = v; opts.preset = "custom"; draw(); })),
          field("Fotogramas", select([[24, "24 fps"], [30, "30 fps"], [60, "60 fps"]], opts.fps, (v) => { opts.fps = Number(v); opts.preset = "custom"; draw(); })),
          field("Códec", select([["h264", "H.264 (máxima compatibilidad)"], ["h265", "H.265 / HEVC (menor tamaño)"], ["av1", "AV1 (RTX 40/50)"]], opts.codec, (v) => { opts.codec = v; opts.preset = "custom"; draw(); })),
          field("Calidad", select(Object.entries(meta.qualities), opts.quality, (v) => { opts.quality = v; opts.preset = "custom"; draw(); })),
        ),
        h("div", { class: "toggle-row" }, h("span", {}, "Aceleración por GPU (NVENC) ", nvenc ? h("span", { class: "badge ok" }, "disponible") : h("span", { class: "badge warn" }, "no detectada")), toggle(opts.hardware, (v) => (opts.hardware = v))),
        h("div", { class: "toggle-row" }, h("span", {}, "Exportar también subtítulos .SRT"), toggle(opts.subtitles_file, (v) => (opts.subtitles_file = v))),
        h("div", { class: "toggle-row" }, h("span", {}, "Generar portada (miniatura .JPG)"), toggle(opts.thumbnail, (v) => (opts.thumbnail = v))),
        h("div", { class: "toggle-row" }, h("span", {}, "Sólo audio (MP3)"), toggle(opts.audio_only, (v) => (opts.audio_only = v))),
        field("Texto de la portada (opcional)", h("input", { class: "input", value: opts.cover_text, placeholder: "Ej.: EL SECRETO QUE NADIE CUENTA", oninput: (e) => (opts.cover_text = e.target.value) })),
      );
    };
    draw();
    const go_ = btn("Exportar", { cls: "primary", icon: "rocket" });
    const m = modal({ title: "Exportar vídeo", body, actions: [go_], width: 680 });
    go_.onclick = async () => {
      const r = ring(140);
      const msg = h("div", { class: "muted" }, "Preparando…");
      clear(body, h("div", { class: "big-progress" }, r, h("h2", {}, "Exportando tu reel"), msg));
      go_.remove();
      try {
        const payload = { ...opts, preset: opts.preset === "custom" ? null : opts.preset, filename: this.project.name };
        const res = await runJob(api.post(`/api/projects/${this.id}/export`, payload), (j) => { r.set(j.progress); msg.textContent = j.message; });
        r.set(1);
        const name = res.path.replace(/\\/g, "/").split("/").pop();
        clear(body, h("div", { class: "big-progress" },
          h("div", { style: { color: "var(--ok)" } }, icon("check", 54, 2.4)),
          h("h2", {}, "¡Listo para publicar!"),
          h("div", { class: "muted" }, `${res.width}×${res.height} · ${res.fps} fps · ${fmtTime(res.duration)} · ${fmtBytes(res.bytes)} · ${res.seconds} s`),
          h("div", { class: "row" },
            bridge.showItemInFolder ? btn("Mostrar en carpeta", { icon: "folder", onClick: () => bridge.showItemInFolder(res.path) }) : null,
            h("a", { class: "btn", href: fileUrl.export(name), download: name }, icon("download", 16), "Descargar"),
            !opts.audio_only ? btn("Reproducir", { icon: "play", cls: "primary", onClick: () => { m.close(); modal({ title: name, width: 520, body: h("video", { src: fileUrl.export(name), controls: true, autoplay: true, style: { width: "100%", maxHeight: "72vh", borderRadius: "12px", background: "#000" } }) }); } }) : null)));
      } catch (e) {
        clear(body, h("div", { class: "big-progress" }, h("div", { style: { color: "var(--err)" } }, icon("alert", 48)), h("h2", {}, "La exportación falló"), h("pre", { class: "small muted", style: { whiteSpace: "pre-wrap", textAlign: "left", maxWidth: "100%", userSelect: "text" } }, e.message)));
      }
    };
  }
}

