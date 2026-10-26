// Reproductor en vivo de la línea de tiempo (cortes, Ken Burns, filtros,
// audio sincronizado y subtítulos). Las transiciones se ven en el render.
import { fileUrl } from "../api.js";
import { captionAt, groupWords, renderCaption } from "../captions.js";
import { state } from "../state.js";
import { h } from "../ui.js";
import { audioLength, clipAt, CSS_FILTERS, motionTransform } from "./model.js";

export class Player {
  constructor(ed) {
    this.ed = ed;
    this.t = 0;
    this.playing = false;
    this.frame = h("div", { class: "frame" });
    this.bg = h("img", { class: "bgblur", alt: "" });
    this.img = h("img", { class: "layer", alt: "" });
    this.videos = [h("video", { muted: true, playsinline: true, preload: "auto" }), h("video", { muted: true, playsinline: true, preload: "auto" })];
    this.videos.forEach((v) => (v.muted = false));
    this.overlay = h("div", { class: "overlay-layer" });
    this.empty = h("div", { class: "empty-frame" }, "Arrastra imágenes o vídeos a la línea de tiempo para empezar");
    this.brollImg = h("img", { class: "broll-layer", alt: "" });
    this.brollVideo = h("video", { class: "broll-layer", muted: true, playsinline: true, preload: "auto" });
    this.wrap = h("div", { class: "media-wrap" }, this.bg, this.img, ...this.videos, this.brollImg, this.brollVideo);
    this.flash = h("div", { class: "flash-layer" });
    this.safe = h("div", { class: "safe-zones" },
      h("div", { style: { left: 0, right: 0, top: 0, height: "11%" } }, h("span", {}, "Interfaz superior")),
      h("div", { style: { right: 0, top: "38%", width: "15%", bottom: "20%" } }, h("span", {}, "Botones")),
      h("div", { style: { left: 0, right: 0, bottom: 0, height: "20%" } }, h("span", {}, "Descripción y audio")));
    this.frame.append(this.wrap, this.flash, this.overlay, this.safe, this.empty);
    this.audios = new Map();
    this.capKey = "";
    this.activeVideo = null;
    this.groups = [];
    this.groupsKey = "";
    this.loop = this.loop.bind(this);
  }

  toggleSafe() {
    this.safe.classList.toggle("on");
  }

  /** Zoom/temblor/flash de los efectos y B-roll activos en el instante actual. */
  renderEffects() {
    const p = this.ed.project;
    const t = this.t;
    let z = 1;
    let dx = 0;
    let dy = 0;
    let flash = 0;
    for (const e of p.effects || []) {
      if (t < e.start || t > e.start + e.duration) continue;
      if (e.type === "punch") z += 0.14 * e.strength * Math.min(1, (t - e.start) / 0.06);
      else if (e.type === "shake") {
        z += 0.06 * e.strength;
        dx += 1.6 * e.strength * Math.sin(t * 95);
        dy += 1.1 * e.strength * Math.cos(t * 71);
      } else if (this.playing) flash = 0.6;
    }
    this.wrap.style.transform = z !== 1 || dx || dy ? `translate(${dx}%, ${dy}%) scale(${z})` : "none";
    this.flash.style.opacity = flash;
    const b = (p.broll || []).find((x) => t >= x.start && t < x.start + x.duration);
    const media = b ? this.ed.media.get(b.media_id) : null;
    if (!media) {
      this.brollImg.style.opacity = 0;
      this.brollVideo.style.opacity = 0;
      if (!this.brollVideo.paused) this.brollVideo.pause();
      return;
    }
    const src = fileUrl.media(media.id);
    if (media.kind === "image") {
      if (this.brollImg.dataset.src !== src) { this.brollImg.src = src; this.brollImg.dataset.src = src; }
      this.brollImg.style.opacity = 1;
      this.brollImg.style.transform = motionTransform(b.motion, Math.min(1, (t - b.start) / b.duration));
      this.brollVideo.style.opacity = 0;
    } else {
      if (this.brollVideo.dataset.src !== src) { this.brollVideo.src = src; this.brollVideo.dataset.src = src; }
      const want = (b.src_in || 0) + (t - b.start);
      if (Math.abs(this.brollVideo.currentTime - want) > 0.35) { try { this.brollVideo.currentTime = want; } catch { /* sin metadatos */ } }
      if (this.playing && this.brollVideo.paused) this.brollVideo.play().catch(() => {});
      if (!this.playing) this.brollVideo.pause();
      this.brollVideo.style.opacity = 1;
      this.brollImg.style.opacity = 0;
    }
  }

  resize(container) {
    const p = this.ed.project.format;
    const W = container.clientWidth - 36;
    const H = container.clientHeight - 36;
    const k = Math.min(W / p.width, H / p.height);
    this.frame.style.width = `${Math.max(80, p.width * k)}px`;
    this.frame.style.height = `${Math.max(80, p.height * k)}px`;
    this.scale = k;
    this.capKey = "";
    this.render(true);
  }

  toggle() {
    this.playing ? this.pause() : this.play();
  }

  play() {
    const total = this.ed.lay.total;
    if (!total) return;
    if (this.t >= total - 0.05) this.t = 0;
    this.playing = true;
    this.clock = performance.now();
    this.t0 = this.t;
    this.render(true);
    requestAnimationFrame(this.loop);
    this.ed.onPlayState?.(true);
  }

  pause() {
    this.playing = false;
    this.videos.forEach((v) => v.pause());
    this.audios.forEach((a) => a.el.pause());
    this.ed.onPlayState?.(false);
  }

  seek(t) {
    this.t = Math.max(0, Math.min(t, this.ed.lay.total || 0));
    if (this.playing) {
      this.clock = performance.now();
      this.t0 = this.t;
    }
    this.render(true);
  }

  loop(now) {
    if (!this.playing) return;
    this.t = this.t0 + (now - this.clock) / 1000;
    if (this.t >= this.ed.lay.total) {
      this.t = this.ed.lay.total;
      this.render(false);
      this.pause();
      return;
    }
    this.render(false);
    requestAnimationFrame(this.loop);
  }

  syncAudio(seeking) {
    const proj = this.ed.project;
    const alive = new Set();
    for (const a of proj.audio) {
      alive.add(a.id);
      const media = this.ed.media.get(a.media_id);
      if (!media) continue;
      let entry = this.audios.get(a.id);
      if (!entry || entry.media !== a.media_id) {
        entry?.el.pause();
        entry = { el: new Audio(fileUrl.media(a.media_id)), media: a.media_id };
        entry.el.preload = "auto";
        this.audios.set(a.id, entry);
      }
      const len = a.loop ? this.ed.lay.total - a.start : audioLength(a, media);
      const local = this.t - a.start;
      const el = entry.el;
      el.volume = Math.max(0, Math.min(1, a.volume));
      if (this.playing && local >= 0 && local < len) {
        const srcLen = audioLength(a, media) || 1;
        const want = a.src_in + (a.loop ? local % srcLen : local);
        if (seeking || Math.abs(el.currentTime - want) > 0.3) el.currentTime = want;
        if (el.paused) el.play().catch(() => {});
      } else if (!el.paused) el.pause();
    }
    for (const [id, entry] of this.audios) if (!alive.has(id)) { entry.el.pause(); this.audios.delete(id); }
  }

  render(seeking) {
    const ed = this.ed;
    const lay = ed.lay;
    this.empty.classList.toggle("hidden", lay.items.length > 0);
    const it = clipAt(lay, this.t);
    if (!it) {
      this.img.style.opacity = 0;
      this.videos.forEach((v) => (v.style.opacity = 0));
    } else {
      const clip = it.clip;
      const media = ed.media.get(clip.media_id);
      const local = this.t - it.start;
      const filter = CSS_FILTERS[clip.filter] || "none";
      const fit = clip.fit === "cover" ? "cover" : "contain";
      const bgSrc = media ? (media.kind === "image" ? fileUrl.media(media.id) : fileUrl.thumb(media.id)) : "";
      this.bg.style.display = clip.fit === "blur" ? "block" : "none";
      if (clip.fit === "blur" && this.bg.dataset.src !== bgSrc) {
        this.bg.src = bgSrc;
        this.bg.dataset.src = bgSrc;
      }
      if (clip.kind === "image") {
        this.videos.forEach((v) => { v.pause(); v.style.opacity = 0; });
        this.activeVideo = null;
        const src = fileUrl.media(clip.media_id);
        if (this.img.dataset.src !== src) {
          this.img.src = src;
          this.img.dataset.src = src;
        }
        this.img.style.opacity = 1;
        this.img.style.objectFit = fit;
        this.img.style.filter = filter;
        this.img.style.transform = motionTransform(clip.motion, Math.min(1, local / it.len));
      } else {
        this.img.style.opacity = 0;
        const src = fileUrl.media(clip.media_id);
        let v = this.videos.find((x) => x.dataset.clip === clip.id) || this.videos.find((x) => x !== this.activeVideo);
        if (v.dataset.clip !== clip.id) {
          v.dataset.clip = clip.id;
          if (v.dataset.src !== src) {
            v.src = src;
            v.dataset.src = src;
          }
          seeking = true;
        }
        this.videos.forEach((x) => { if (x !== v) { x.pause(); x.style.opacity = 0; } });
        this.activeVideo = v;
        v.style.opacity = 1;
        v.style.objectFit = fit;
        v.style.filter = filter;
        v.style.transform = clip.zoom > 1.001 ? `scale(${clip.zoom})` : "none";
        v.style.transformOrigin = "50% 35%";
        if (clip.fit === "track" && media?.width && media?.height) {
          // object-position equivalente al recorte de FFmpeg centrado en cx
          const frac = Math.min(1, (ed.project.format.width / ed.project.format.height) / (media.width / media.height));
          const cx = trackAt(clip, clip.src_in + local * clip.speed);
          const pos = frac >= 1 ? 0.5 : Math.min(1, Math.max(0, (cx - frac / 2) / (1 - frac)));
          v.style.objectPosition = `${pos * 100}% 50%`;
        } else v.style.objectPosition = "50% 50%";
        v.volume = Math.max(0, Math.min(1, clip.volume));
        v.playbackRate = clip.speed;
        const want = clip.src_in + local * clip.speed;
        if (seeking || Math.abs(v.currentTime - want) > 0.35) {
          try { v.currentTime = want; } catch { /* aún sin metadatos */ }
        }
        if (this.playing && v.paused) v.play().catch(() => {});
        if (!this.playing && !v.paused) v.pause();
        this.preloadNext(it);
      }
    }
    this.syncAudio(seeking);
    this.renderEffects();
    this.renderOverlay();
    ed.onTime?.(this.t);
  }

  preloadNext(it) {
    const next = this.ed.lay.items[it.index + 1];
    if (!next || next.clip.kind !== "video") return;
    const other = this.videos.find((x) => x !== this.activeVideo);
    if (other.dataset.clip === next.clip.id) return;
    other.dataset.clip = next.clip.id;
    const src = fileUrl.media(next.clip.media_id);
    if (other.dataset.src !== src) {
      other.src = src;
      other.dataset.src = src;
    }
    try { other.currentTime = next.clip.src_in; } catch { /* sin metadatos */ }
  }

  renderOverlay() {
    const p = this.ed.project;
    const cap = p.captions;
    const gk = `${cap.words.length}:${cap.words[0]?.s}:${cap.words[cap.words.length - 1]?.e}:${cap.max_words}:${cap.scale}:${this.ed.wordsVersion || 0}`;
    if (gk !== this.groupsKey) {
      this.groups = groupWords(cap.words, cap.max_words, Math.max(10, Math.floor(22 / Math.max(0.6, cap.scale))));
      this.groupsKey = gk;
    }
    const at = cap.enabled ? captionAt(this.groups, this.t) : null;
    const texts = p.texts.filter((t) => this.t >= t.start && this.t < t.end);
    const emoji = cap.enabled ? cap.words.find((w) => w.emoji && this.t >= w.s && this.t < w.s + 0.9) : null;
    const brandOn = p.brand !== false;
    const key = JSON.stringify([at?.gi, at?.active, cap.style, cap.position, cap.scale, cap.uppercase, texts.map((t) => t.id + t.text + t.style + t.position + t.scale), this.scale, emoji?.s, brandOn, this.ed.wordsVersion || 0]);
    if (key === this.capKey) return;
    this.capKey = key;
    this.overlay.replaceChildren();
    const k = (this.scale || 0.3) * (p.format.width / 1080);
    for (const t of texts) {
      const styles = {
        title: { color: "#fff", background: "#000" },
        label: { color: "#000", background: "#FFE600" },
        outline: { color: "#fff", background: "transparent", WebkitTextStroke: `${7 * k}px #000`, paintOrder: "stroke fill" },
      }[t.style] || {};
      const lines = String(t.text).split("|");
      this.overlay.append(
        h("div", { class: "ov-text", style: { top: `${t.position * 100}%` } },
          lines.map((line) => h("div", {}, h("span", { style: { ...styles, fontSize: `${(t.style === "label" ? 70 : 94) * k * t.scale}px`, fontFamily: '"Poppins Black", "Arial Black", sans-serif' } }, line))),
        ),
      );
    }
    if (at) {
      const st = this.ed.meta.caption_styles[cap.style] || this.ed.meta.caption_styles.viral;
      const el = renderCaption(cap.style, at.group, at.active, st.size * k * cap.scale, { uppercase: cap.uppercase });
      this.overlay.append(h("div", { class: "ov-cap", style: { top: `${cap.position * 100}%` } }, el));
    }
    if (emoji) {
      const size = 150 * k * cap.scale;
      this.overlay.append(h("div", { class: "ov-emoji", style: { top: `calc(${cap.position * 100}% - ${95 * k * cap.scale}px)`, fontSize: `${size * 0.8}px` } }, emoji.emoji));
    }
    const handle = brandOn ? (state.settings?.brand_handle || "").trim() : "";
    if (handle) this.overlay.append(h("div", { class: "ov-handle", style: { fontSize: `${40 * k}px` } }, handle));
    const logoId = brandOn ? state.settings?.brand_logo_media_id : "";
    if (logoId && this.ed.media.get(logoId)) {
      const w = (p.format.width * (state.settings.brand_logo_scale || 0.16)) * (this.scale || 0.3);
      const pos = state.settings.brand_logo_pos || "top-right";
      const st = { width: `${w}px`, opacity: state.settings.brand_logo_opacity ?? 0.85 };
      st[pos.includes("right") ? "right" : "left"] = `${40 * k}px`;
      st[pos.includes("top") ? "top" : "bottom"] = pos.includes("top") ? `${120 * k}px` : `${260 * k}px`;
      this.overlay.append(h("img", { class: "ov-logo", src: fileUrl.media(logoId), style: st }));
    }
  }

  destroy() {
    this.pause();
    this.audios.forEach((a) => (a.el.src = ""));
    this.videos.forEach((v) => v.removeAttribute("src"));
  }
}

/** Centro horizontal (0..1) del reencuadre con seguimiento en el instante de origen `t`. */
function trackAt(clip, t) {
  const kf = clip.track || [];
  if (!kf.length) return 0.5;
  if (t <= kf[0][0]) return kf[0][1];
  for (let i = 1; i < kf.length; i++) {
    const [t1, c1] = kf[i];
    if (t <= t1) {
      const [t0, c0] = kf[i - 1];
      return c0 + ((c1 - c0) * (t - t0)) / Math.max(0.001, t1 - t0);
    }
  }
  return kf[kf.length - 1][1];
}
