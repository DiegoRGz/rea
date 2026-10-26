// Vista previa de subtítulos en HTML que imita el render ASS del motor.
import { h } from "./ui.js";
import { state } from "./state.js";

const FALLBACK = { "Arial Black": '"Arial Black", "Arial", sans-serif', Impact: 'Impact, "Arial Black", sans-serif', "Segoe UI Semibold": '"Segoe UI Semibold", "Segoe UI", sans-serif' };

export function fontStack(style) {
  return `"${style.font}", ${FALLBACK[style.fallback] || '"Arial Black", sans-serif'}`;
}

/** Misma lógica de agrupación que captions.group_words (backend). */
export function groupWords(words, maxWords = 3, maxChars = 20, gap = 0.5) {
  const groups = [];
  let cur = [];
  for (const w of words) {
    if (!String(w.w).trim()) continue;
    if (cur.length) {
      const chars = cur.reduce((a, x) => a + x.w.length + 1, 0) + w.w.length;
      const prev = cur[cur.length - 1];
      if (cur.length >= maxWords || chars > maxChars || w.s - prev.e > gap || /[.!?;:,…]$/.test(prev.w)) {
        groups.push(cur);
        cur = [];
      }
    }
    cur.push(w);
  }
  if (cur.length) groups.push(cur);
  return groups;
}

/** Devuelve {group, active} para el instante t o null. */
export function captionAt(groups, t) {
  for (let gi = 0; gi < groups.length; gi++) {
    const g = groups[gi];
    const next = groups[gi + 1];
    let end = g[g.length - 1].e + 0.25;
    if (next) end = next[0].s - g[g.length - 1].e < 0.7 ? next[0].s : Math.min(end, next[0].s);
    if (t >= g[0].s && t < end) {
      let active = 0;
      for (let i = 0; i < g.length; i++) if (t >= g[i].s) active = i;
      return { gi, group: g, active };
    }
  }
  return null;
}

/** Elemento con el estilo del subtítulo; `px` = tamaño base en píxeles. */
export function renderCaption(styleId, words, activeIdx, px, opts = {}) {
  const st = state.meta?.caption_styles?.[styleId] || state.meta?.caption_styles?.viral;
  if (!st) return h("div");
  const upper = opts.uppercase ?? st.uppercase;
  const stroke = Math.max(0.5, (st.outline_w / st.size) * px * 1.3);
  const el = h("div", {
    class: "cap",
    style: {
      fontFamily: fontStack(st),
      fontSize: `${px}px`,
      color: st.effect === "karaoke" ? st.primary : st.primary,
      WebkitTextStroke: st.outline_w ? `${stroke}px ${st.outline}` : "0",
      paintOrder: "stroke fill",
      textShadow: st.effect === "neon" ? `0 0 ${px * 0.25}px ${st.active}, 0 0 ${px * 0.5}px ${st.active}` : st.shadow ? `0 ${px * 0.05}px 0 rgba(0,0,0,.6)` : "none",
    },
  });
  words.forEach((w, i) => {
    let text = String(w.w);
    if (upper) text = text.toUpperCase();
    const span = h("span", {}, text);
    const isActive = i === activeIdx;
    if (st.effect === "karaoke") {
      if (i <= activeIdx) span.style.color = st.active;
    } else if (isActive && st.effect !== "fade") {
      span.classList.add("act");
      if (st.effect === "box") {
        Object.assign(span.style, { background: st.active, borderRadius: `${px * 0.18}px`, padding: `0 ${px * 0.14}px`, WebkitTextStroke: "0" });
      } else if (st.effect !== "bounce") {
        span.style.color = st.active;
      }
    }
    el.append(span);
  });
  return el;
}

/** Tarjeta de galería con animación en bucle del estilo. */
export function styleCard(styleId, selected, onPick) {
  const st = state.meta.caption_styles[styleId];
  const sample = [{ w: "Esto" }, { w: "es" }, { w: "viral" }];
  const holder = h("div");
  const card = h("div", { class: `cap-style ${selected ? "on" : ""}`, onclick: () => onPick(styleId) }, holder, h("span", { class: "name" }, st.name));
  let i = 0;
  const words = st.max_words === 1 ? null : sample;
  const tick = () => {
    if (!card.isConnected) return;
    if (words) holder.replaceChildren(renderCaption(styleId, words, i % 3, 19));
    else holder.replaceChildren(renderCaption(styleId, [sample[i % 3]], 0, 26));
    i++;
    setTimeout(tick, 650);
  };
  requestAnimationFrame(tick);
  return card;
}

export function injectFonts() {
  const fonts = state.meta?.fonts || [];
  const css = fonts
    .filter((f) => f.installed)
    .map((f) => `@font-face{font-family:"${f.family}";src:url("/files/fonts/${f.file}?t=${encodeURIComponent(sessionStorage.getItem("rf-token") || "")}");font-display:swap}`)
    .join("\n");
  let tag = document.getElementById("rf-fonts");
  if (!tag) {
    tag = h("style", { id: "rf-fonts" });
    document.head.append(tag);
  }
  tag.textContent = css;
}
