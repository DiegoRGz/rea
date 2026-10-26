// Línea de tiempo: pistas, arrastrar para reordenar/mover, recortar con
// tiradores, cabezal de reproducción e inserción desde la biblioteca.
import { fileUrl } from "../api.js";
import { groupWords } from "../captions.js";
import { clear, h, icon } from "../ui.js";
import { audioLength, newAudio, newClip } from "./model.js";

const LABEL_W = 92;

export class Timeline {
  constructor(ed) {
    this.ed = ed;
    this.pps = 70;
    this.scroll = h("div", { class: "tl-scroll" });
    this.inner = h("div", { class: "tl-inner" });
    this.playhead = h("div", { class: "tl-playhead" });
    this.insertMark = h("div", { class: "tl-insert hidden" });
    this.scroll.append(this.inner);
    this.scroll.addEventListener("dragover", (e) => this.onDragOver(e));
    this.scroll.addEventListener("dragleave", () => this.insertMark.classList.add("hidden"));
    this.scroll.addEventListener("drop", (e) => this.onDrop(e));
    this.scroll.addEventListener("wheel", (e) => {
      if (e.ctrlKey) {
        e.preventDefault();
        this.setZoom(this.pps * (e.deltaY < 0 ? 1.15 : 0.87));
      }
    }, { passive: false });
  }

  setZoom(v) {
    this.pps = Math.max(12, Math.min(400, v));
    this.ed.zoomInput && (this.ed.zoomInput.value = this.pps);
    this.render();
  }

  x(t) {
    return LABEL_W + t * this.pps;
  }

  timeFromEvent(e) {
    const r = this.inner.getBoundingClientRect();
    return Math.max(0, (e.clientX - r.left - LABEL_W) / this.pps);
  }

  render() {
    const ed = this.ed;
    const lay = ed.lay;
    const width = this.x(Math.max(lay.total + 8, 20)) + 40;
    this.inner.style.width = `${width}px`;
    const ruler = h("div", { class: "tl-ruler" });
    const step = this.pps > 120 ? 0.5 : this.pps > 50 ? 1 : this.pps > 25 ? 2 : 5;
    for (let t = 0; t < lay.total + 8; t += step) {
      ruler.append(h("div", { class: "tick", style: { left: `${this.x(t)}px` } }, Number.isInteger(t) ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}` : ""));
    }
    ruler.addEventListener("pointerdown", (e) => this.scrub(e));

    const video = this.track("video", "Vídeo", "film");
    if (!lay.items.length) video.append(h("div", { class: "drop-hint", style: { marginLeft: `${LABEL_W}px`, width: "420px", position: "absolute", left: 0, top: 0 } }, "Arrastra medios aquí o pulsa + en la biblioteca"));
    for (const it of lay.items) video.append(this.clipEl(it));
    for (const it of lay.items.slice(0, -1)) {
      const has = it.clip.transition?.type && it.clip.transition.type !== "none";
      video.append(h("div", {
        class: `tl-trans ${has ? "has" : ""}`,
        title: has ? `Transición: ${ed.meta.transitions[it.clip.transition.type]}` : "Añadir transición",
        style: { left: `${this.x(it.visEnd)}px` },
        onpointerdown: (e) => e.stopPropagation(),
        onclick: () => { ed.select("clip", it.clip.id); ed.showTab("transitions"); },
      }, icon(has ? "shuffle" : "plus", 12)));
    }

    const broll = this.track("audio", "B-roll", "layers");
    for (const b of ed.project.broll || []) {
      const m = ed.media.get(b.media_id);
      const el = this.rangeEl("broll", b, b.start, b.duration, m?.name || "B-roll", null);
      if (m?.thumb) el.style.backgroundImage = `url(${fileUrl.thumb(m.id)})`;
      broll.append(el);
    }
    const fx = this.track("fx", "Efectos", "zap");
    for (const e of ed.project.effects || []) {
      const mk = h("div", { class: `tl-fx ${e.type} ${ed.sel?.type === "effect" && ed.sel.id === e.id ? "sel" : ""}`, title: { punch: "Zoom de impacto", shake: "Temblor", flash: "Flash" }[e.type], style: { left: `${this.x(e.start)}px` } });
      mk.addEventListener("pointerdown", (ev) => this.fxPointer(ev, e));
      fx.append(mk);
    }
    const texts = this.track("text", "Texto", "type");
    for (const t of ed.project.texts) texts.append(this.rangeEl("text", t, t.start, t.end - t.start, t.text.replace(/\|/g, " ")));

    const caps = this.track("caps", "Subtítulos", "captions");
    const cap = ed.project.captions;
    if (cap.enabled && cap.words.length) {
      for (const g of groupWords(cap.words, cap.max_words)) {
        caps.append(h("div", {
          class: "tl-caption",
          style: { left: `${this.x(g[0].s)}px`, width: `${Math.max(4, (g[g.length - 1].e - g[0].s) * this.pps)}px` },
          onclick: () => { ed.showTab("captions"); ed.player.seek(g[0].s); },
        }, g.map((w) => w.w).join(" ")));
      }
    }

    const voice = this.track("audio", "Voz / FX", "mic");
    const music = this.track("audio", "Música", "music");
    for (const a of ed.project.audio) {
      const m = ed.media.get(a.media_id);
      const len = a.loop ? Math.max(0.5, lay.total - a.start) : audioLength(a, m);
      (a.role === "music" ? music : voice).append(this.rangeEl(a.role, a, a.start, len, m?.name || "Audio", m));
    }

    clear(this.inner, ruler, video, broll, fx, texts, caps, voice, music, this.insertMark, this.playhead);
    this.inner.querySelectorAll(".tl-track").forEach((tr) => tr.addEventListener("pointerdown", (e) => {
      if (e.target === tr) {
        ed.select(null);
        this.scrub(e);
      }
    }));
    this.updatePlayhead(ed.player.t);
  }

  track(cls, label, ic) {
    return h("div", { class: `tl-track ${cls}` }, h("div", { class: "tl-label" }, icon(ic, 13), label));
  }

  clipEl(it) {
    const ed = this.ed;
    const c = it.clip;
    const m = ed.media.get(c.media_id);
    const w = Math.max(6, (it.visEnd - it.start) * this.pps);
    const el = h("div", {
      class: `tl-item clip ${ed.sel?.type === "clip" && ed.sel.id === c.id ? "sel" : ""}`,
      style: { left: `${this.x(it.start)}px`, width: `${w - 2}px`, backgroundImage: m?.thumb ? `url(${fileUrl.thumb(m.id)})` : "none" },
      title: m?.name,
    }, h("div", { class: "lbl" }, `${m?.name || "?"} · ${it.len.toFixed(1)}s`), h("div", { class: "handle l" }), h("div", { class: "handle r" }));
    el.addEventListener("pointerdown", (e) => this.clipPointer(e, it, el));
    return el;
  }

  rangeEl(kind, obj, start, len, label, media) {
    const ed = this.ed;
    const type = kind === "text" ? "text" : kind === "broll" ? "broll" : "audio";
    const el = h("div", {
      class: `tl-item ${kind} ${ed.sel?.type === type && ed.sel.id === obj.id ? "sel" : ""}`,
      style: { left: `${this.x(start)}px`, width: `${Math.max(6, len * this.pps) - 2}px` },
    }, media?.thumb ? h("div", { class: "wave", style: { backgroundImage: `url(${fileUrl.thumb(media.id)})` } }) : null, h("div", { class: "lbl" }, label), h("div", { class: "handle l" }), h("div", { class: "handle r" }));
    el.addEventListener("pointerdown", (e) => this.rangePointer(e, type, obj, el, media));
    return el;
  }

  updatePlayhead(t) {
    this.playhead.style.left = `${this.x(t)}px`;
    if (this.ed.player.playing) {
      const x = this.x(t);
      const sl = this.scroll.scrollLeft;
      if (x > sl + this.scroll.clientWidth - 60 || x < sl + LABEL_W) this.scroll.scrollLeft = x - LABEL_W - 40;
    }
  }

  scrub(e) {
    const move = (ev) => this.ed.player.seek(this.timeFromEvent(ev));
    move(e);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  /** Arrastre de clips: mover (reordenar) o recortar con los tiradores. */
  clipPointer(e, it, el) {
    e.stopPropagation();
    const ed = this.ed;
    const c = it.clip;
    const media = ed.media.get(c.media_id);
    ed.select("clip", c.id, false);
    const handle = e.target.classList.contains("handle") ? (e.target.classList.contains("l") ? "l" : "r") : null;
    const x0 = e.clientX;
    const orig = { duration: c.duration, src_in: c.src_in, src_out: c.src_out ?? media?.duration ?? c.duration };
    let moved = false;
    let target = it.index;
    const move = (ev) => {
      const dx = ev.clientX - x0;
      if (!moved && Math.abs(dx) < 4) return;
      if (!moved) ed.checkpoint();
      moved = true;
      const dt = dx / this.pps;
      if (handle === "r") {
        if (c.kind === "image") c.duration = Math.max(0.3, Math.round((orig.duration + dt) * 20) / 20);
        else c.src_out = Math.min(media?.duration ?? 1e9, Math.max(c.src_in + 0.2, orig.src_out + dt * c.speed));
        ed.refresh(false);
      } else if (handle === "l") {
        if (c.kind === "video") c.src_in = Math.max(0, Math.min(orig.src_out - 0.2, orig.src_in + dt * c.speed));
        else c.duration = Math.max(0.3, Math.round((orig.duration - dt) * 20) / 20);
        ed.refresh(false);
      } else {
        el.classList.add("dragging");
        el.style.transform = `translateX(${dx}px)`;
        const t = this.timeFromEvent(ev);
        const centers = ed.lay.items.map((x) => (x.start + x.visEnd) / 2);
        target = centers.filter((cx) => cx < t).length;
        const ref = target < ed.lay.items.length ? ed.lay.items[target].start : ed.lay.total;
        this.insertMark.style.left = `${this.x(ref)}px`;
        this.insertMark.classList.remove("hidden");
      }
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      this.insertMark.classList.add("hidden");
      if (!moved) {
        ed.select("clip", c.id);
        ed.player.seek(Math.max(ed.player.t, 0) >= it.start && ed.player.t < it.visEnd ? ed.player.t : it.start);
        return;
      }
      if (!handle) {
        const clips = ed.project.clips;
        const from = clips.indexOf(c);
        clips.splice(from, 1);
        clips.splice(target > from ? target - 1 : target, 0, c);
      }
      ed.commit();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  rangePointer(e, type, obj, el, media) {
    e.stopPropagation();
    const ed = this.ed;
    ed.select(type, obj.id, false);
    const handle = e.target.classList.contains("handle") ? (e.target.classList.contains("l") ? "l" : "r") : null;
    const x0 = e.clientX;
    const o = { ...obj };
    let moved = false;
    const move = (ev) => {
      const dx = ev.clientX - x0;
      if (!moved && Math.abs(dx) < 4) return;
      if (!moved) ed.checkpoint();
      moved = true;
      const dt = Math.round((dx / this.pps) * 20) / 20;
      if (type === "broll") {
        if (handle === "l") {
          const d = Math.max(-o.start, Math.min(dt, o.duration - 0.3));
          obj.start = o.start + d;
          obj.duration = o.duration - d;
        } else if (handle === "r") obj.duration = Math.max(0.3, o.duration + dt);
        else obj.start = Math.max(0, o.start + dt);
      } else if (type === "text") {
        if (handle === "l") obj.start = Math.max(0, Math.min(o.end - 0.2, o.start + dt));
        else if (handle === "r") obj.end = Math.max(o.start + 0.2, o.end + dt);
        else {
          const d = o.end - o.start;
          obj.start = Math.max(0, o.start + dt);
          obj.end = obj.start + d;
        }
      } else if (handle === "l") {
        const shift = Math.max(-o.src_in, Math.min(dt, (o.src_out ?? media?.duration ?? 0) - o.src_in - 0.2));
        obj.src_in = o.src_in + shift;
        obj.start = Math.max(0, o.start + shift);
      } else if (handle === "r") {
        const full = media?.duration ?? 0;
        obj.src_out = Math.max(o.src_in + 0.2, Math.min(full, (o.src_out ?? full) + dt));
      } else {
        obj.start = Math.max(0, o.start + dt);
      }
      ed.refresh(false);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (moved) ed.commit();
      else ed.select(type, obj.id);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  fxPointer(e, fx) {
    e.stopPropagation();
    const ed = this.ed;
    ed.select("effect", fx.id, false);
    const x0 = e.clientX;
    const start = fx.start;
    let moved = false;
    const move = (ev) => {
      const dx = ev.clientX - x0;
      if (!moved && Math.abs(dx) < 3) return;
      if (!moved) ed.checkpoint();
      moved = true;
      fx.start = Math.max(0, Math.round((start + dx / this.pps) * 100) / 100);
      ed.refresh(false);
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (moved) ed.commit();
      else { ed.select("effect", fx.id); ed.player.seek(fx.start); }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }

  onDragOver(e) {
    if (!e.dataTransfer.types.includes("text/x-media")) return;
    e.preventDefault();
    const t = this.timeFromEvent(e);
    const centers = this.ed.lay.items.map((x) => (x.start + x.visEnd) / 2);
    const idx = centers.filter((cx) => cx < t).length;
    const ref = idx < this.ed.lay.items.length ? this.ed.lay.items[idx].start : this.ed.lay.total;
    this.insertMark.style.left = `${this.x(ref)}px`;
    this.insertMark.classList.remove("hidden");
  }

  onDrop(e) {
    const id = e.dataTransfer.getData("text/x-media");
    this.insertMark.classList.add("hidden");
    if (!id) return;
    e.preventDefault();
    const media = this.ed.media.get(id);
    if (!media) return;
    const t = this.timeFromEvent(e);
    this.ed.checkpoint();
    if (media.kind === "audio") {
      const role = media.source === "music" ? "music" : media.source === "tts" ? "voice" : e.clientY > this.scroll.getBoundingClientRect().bottom - 50 ? "music" : "voice";
      const a = newAudio(media, role, Math.round(t * 20) / 20);
      this.ed.project.audio.push(a);
      this.ed.commit();
      this.ed.select("audio", a.id);
      return;
    }
    const centers = this.ed.lay.items.map((x) => (x.start + x.visEnd) / 2);
    const idx = centers.filter((cx) => cx < t).length;
    const clip = newClip(media);
    this.ed.project.clips.splice(idx, 0, clip);
    this.ed.commit();
    this.ed.select("clip", clip.id);
  }
}
