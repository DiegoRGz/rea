// Utilidades de interfaz: creación de elementos, iconos, avisos, modales y controles.

// Las vistas componen hijos opcionales con `cond ? nodo : null`; append() los
// omite en lugar de insertar el texto "null".
const nativeAppend = Element.prototype.append;
Element.prototype.append = function (...nodes) {
  nativeAppend.apply(this, nodes.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false));
};

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") {
      for (const [sk, sv] of Object.entries(v)) {
        if (sk.startsWith("--")) el.style.setProperty(sk, sv);
        else el.style[sk] = sv;
      }
    }
    else if (k === "html") el.innerHTML = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear(el, ...children) {
  el.replaceChildren();
  append(el, children);
  return el;
}

// Iconos (trazos estilo Lucide, 24×24)
const P = {
  home: "M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z",
  sparkles: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9zM5 2l.6 1.4L7 4l-1.4.6L5 6l-.6-1.4L3 4l1.4-.6z",
  film: "M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM7 3v18M17 3v18M3 8h4M3 12h4M3 16h4M17 8h4M17 12h4M17 16h4",
  mic: "M12 2a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3zM19 10v1a7 7 0 0 1-14 0v-1M12 18v4M8 22h8",
  captions: "M3 5h18a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7 15h4M15 15h2M7 11h2M13 11h4",
  image: "M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM8.5 10a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM21 15l-5-5L5 21",
  video: "M15 10l5-3v10l-5-3zM3 6h12v12H3z",
  music: "M9 18V5l12-2v13M9 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0zM21 16a3 3 0 1 1-6 0 3 3 0 0 1 6 0z",
  cloud: "M17.5 19H9a7 7 0 1 1 6.7-9h1.8a4.5 4.5 0 1 1 0 9z",
  box: "M21 8 12 3 3 8v8l9 5 9-5zM3 8l9 5 9-5M12 13v8",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  plus: "M12 5v14M5 12h14",
  upload: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12",
  download: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3",
  play: "M7 4v16l13-8z",
  pause: "M7 4h3v16H7zM14 4h3v16h-3z",
  scissors: "M6 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12",
  trash: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  undo: "M9 14 4 9l5-5M4 9h11a5 5 0 0 1 0 10h-3",
  redo: "m15 14 5-5-5-5M20 9H9a5 5 0 0 0 0 10h3",
  x: "M18 6 6 18M6 6l12 12",
  check: "M20 6 9 17l-5-5",
  chevronR: "m9 18 6-6-6-6",
  chevronL: "m15 18-6-6 6-6",
  wand: "M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8 19 13M17.8 6.2 19 5M12.2 6.2 11 5M3 21l9-9",
  type: "M4 7V4h16v3M9 20h6M12 4v16",
  layers: "m12 2 10 5-10 5L2 7zM2 17l10 5 10-5M2 12l10 5 10-5",
  palette: "M12 22a10 10 0 1 1 10-10c0 3-2 4-4 4h-2a2 2 0 0 0-1 3.7A1.5 1.5 0 0 1 14 22zM7.5 11.5h.01M10.5 7.5h.01M15.5 7.5h.01M17.5 11.5h.01",
  shuffle: "M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5",
  folder: "M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z",
  external: "M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6",
  rocket: "M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 0 0-2.9-.1zM12 15l-3-3a22 22 0 0 1 2-3.9A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.5-6 11a22.4 22.4 0 0 1-4 2zM9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5",
  cpu: "M6 6h12v12H6zM9 9h6v6H9zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4",
  zap: "M13 2 3 14h9l-1 8 10-12h-9z",
  eye: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  minus: "M5 12h14",
  square: "M5 5h14v14H5z",
  info: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
  alert: "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
  grip: "M9 5h.01M9 12h.01M9 19h.01M15 5h.01M15 12h.01M15 19h.01",
  volume: "M11 5 6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14",
  globe: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20",
  key: "M21 2l-2 2m-7.6 7.6a5.5 5.5 0 1 1-7.8 7.8 5.5 5.5 0 0 1 7.8-7.8zM15.5 7.5l3 3L22 7l-3-3",
  refresh: "M21 12a9 9 0 0 1-15 6.7L3 16M3 12a9 9 0 0 1 15-6.7L21 8M21 3v5h-5M3 21v-5h5",
  clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
  maximize: "M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3",
  text2: "M17 6.1H3M21 12.1H3M15.1 18H3",
  magnet: "M6 15a6 6 0 0 0 12 0V4h-4v11a2 2 0 0 1-4 0V4H6zM6 8h4M14 8h4",
};

export function icon(name, size = 18, stroke = 1.9) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", stroke);
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  const path = document.createElementNS(ns, "path");
  path.setAttribute("d", P[name] || P.info);
  svg.append(path);
  return svg;
}

export function btn(label, opts = {}) {
  const { icon: ic, cls = "", onClick, title, size } = opts;
  const b = h("button", { class: `btn ${cls}`, title, onclick: onClick, type: "button" });
  if (ic) b.append(icon(ic, size || 16));
  if (label) b.append(h("span", {}, label));
  return b;
}

/** Ejecuta una acción asíncrona mostrando el botón en estado de carga. */
export async function busy(button, fn) {
  button.classList.add("loading");
  button.disabled = true;
  try {
    return await fn();
  } finally {
    button.classList.remove("loading");
    button.disabled = false;
  }
}

// Efecto "ripple" en todos los botones
document.addEventListener("pointerdown", (e) => {
  const b = e.target.closest(".btn, .play-btn, .chip, .tile, .option-card");
  if (!b || b.disabled) return;
  const r = b.getBoundingClientRect();
  const size = Math.max(r.width, r.height);
  const s = h("span", {
    class: "ripple",
    style: { width: `${size}px`, height: `${size}px`, left: `${e.clientX - r.left - size / 2}px`, top: `${e.clientY - r.top - size / 2}px` },
  });
  if (getComputedStyle(b).position === "static") b.style.position = "relative";
  b.style.overflow = "hidden";
  b.append(s);
  setTimeout(() => s.remove(), 650);
});

export function toast(message, type = "info", ms = 4200) {
  const root = document.getElementById("toasts");
  const ic = { ok: "check", err: "alert", info: "info" }[type] || "info";
  const t = h("div", { class: `toast ${type}` }, h("span", { class: "t-icon" }, icon(ic, 18)), h("div", {}, message));
  root.append(t);
  const close = () => {
    t.classList.add("out");
    setTimeout(() => t.remove(), 300);
  };
  t.addEventListener("click", close);
  setTimeout(close, ms);
}

export function modal({ title, body, actions = [], width, onClose }) {
  const back = h("div", { class: "modal-back" });
  const box = h("div", { class: "modal", style: width ? { width: `min(${width}px, calc(100vw - 60px))` } : null });
  const close = () => {
    back.classList.add("out");
    setTimeout(() => back.remove(), 200);
    document.removeEventListener("keydown", esc);
    onClose?.();
  };
  const esc = (e) => e.key === "Escape" && close();
  document.addEventListener("keydown", esc);
  box.append(
    h("div", { class: "modal-head" }, h("h2", {}, title), h("div", { class: "spacer" }), btn("", { icon: "x", cls: "ghost icon sm", onClick: close })),
    h("div", { class: "modal-body" }, body),
  );
  if (actions.length) box.append(h("div", { class: "modal-foot" }, actions));
  back.append(box);
  back.addEventListener("pointerdown", (e) => e.target === back && close());
  document.body.append(back);
  return { close, box };
}

export function confirmDialog(title, text, okLabel = "Aceptar", danger = false) {
  return new Promise((resolve) => {
    let done = false;
    const ok = btn(okLabel, { cls: danger ? "danger" : "primary" });
    const cancel = btn("Cancelar", { cls: "ghost" });
    const m = modal({
      title,
      body: h("p", { class: "muted", style: { margin: 0 } }, text),
      actions: [cancel, ok],
      width: 440,
      onClose: () => !done && resolve(false),
    });
    ok.onclick = () => {
      done = true;
      resolve(true);
      m.close();
    };
    cancel.onclick = () => m.close();
  });
}

export function field(label, control, hint) {
  return h("div", { class: "field" }, h("label", {}, label), control, hint ? h("div", { class: "muted small" }, hint) : null);
}

export function select(options, value, onChange) {
  const s = h("select", { class: "select" });
  for (const opt of options) {
    const [v, l] = Array.isArray(opt) ? opt : [opt, opt];
    s.append(h("option", { value: v }, l));
  }
  if (value !== undefined && value !== null) s.value = value;
  if (onChange) s.addEventListener("change", () => onChange(s.value));
  return s;
}

export function slider(value, min, max, step, onInput, fmt = (v) => v) {
  const input = h("input", { type: "range", min, max, step, value });
  const val = h("span", { class: "val" }, fmt(Number(value)));
  const paint = () => input.style.setProperty("--p", `${((input.value - min) / (max - min)) * 100}%`);
  paint();
  input.addEventListener("input", () => {
    paint();
    val.textContent = fmt(Number(input.value));
    onInput(Number(input.value), false);
  });
  input.addEventListener("change", () => onInput(Number(input.value), true));
  return h("div", { class: "range-field" }, input, val);
}

export function toggle(checked, onChange) {
  const input = h("input", { type: "checkbox", checked });
  input.addEventListener("change", () => onChange(input.checked));
  return h("label", { class: "switch" }, input, h("span"));
}

export function segmented(options, value, onChange) {
  const wrap = h("div", { class: "seg" });
  const pill = h("div", { class: "seg-pill" });
  wrap.append(pill);
  const buttons = options.map(([v, l]) => {
    const b = h("button", { type: "button", class: v === value ? "on" : "" }, l);
    b.onclick = () => {
      buttons.forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      move(b);
      onChange(v);
    };
    wrap.append(b);
    return b;
  });
  const move = (b) => {
    pill.style.left = `${b.offsetLeft}px`;
    pill.style.width = `${b.offsetWidth}px`;
  };
  requestAnimationFrame(() => move(buttons.find((b) => b.classList.contains("on")) || buttons[0]));
  return wrap;
}

export function chips(options, value, onChange, multi = false) {
  const wrap = h("div", { class: "chips" });
  let current = multi ? new Set(value || []) : value;
  for (const [v, l] of options) {
    const c = h("button", { type: "button", class: `chip ${(multi ? current.has(v) : current === v) ? "on" : ""}` }, l);
    c.onclick = () => {
      if (multi) {
        current.has(v) ? current.delete(v) : current.add(v);
        c.classList.toggle("on");
        onChange([...current]);
      } else {
        wrap.querySelectorAll(".chip").forEach((x) => x.classList.remove("on"));
        c.classList.add("on");
        current = v;
        onChange(v);
      }
    };
    wrap.append(c);
  }
  return wrap;
}

export function progressBar(value = 0) {
  const i = h("i", { style: { width: `${value * 100}%` } });
  const el = h("div", { class: "progress" }, i);
  el.set = (v) => {
    el.classList.toggle("indeterminate", v === null);
    if (v !== null) i.style.width = `${Math.max(0, Math.min(1, v)) * 100}%`;
  };
  return el;
}

export function ring(size = 150) {
  const r = size / 2 - 8;
  const c = 2 * Math.PI * r;
  const wrap = h("div", { class: "ring", style: { width: `${size}px`, height: `${size}px` } });
  wrap.innerHTML = `<svg width="${size}" height="${size}"><defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7c5cff"/><stop offset=".55" stop-color="#ff4d9d"/><stop offset="1" stop-color="#ff8a3d"/></linearGradient></defs><circle cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="rgba(255,255,255,.07)" stroke-width="10" fill="none"/><circle class="fg" cx="${size / 2}" cy="${size / 2}" r="${r}" stroke="url(#rg)" stroke-width="10" stroke-linecap="round" fill="none" stroke-dasharray="${c}" stroke-dashoffset="${c}"/></svg><div class="val">0%</div>`;
  const fg = wrap.querySelector(".fg");
  const val = wrap.querySelector(".val");
  wrap.set = (v) => {
    fg.style.strokeDashoffset = `${c * (1 - Math.max(0, Math.min(1, v)))}`;
    val.textContent = `${Math.round(v * 100)}%`;
  };
  return wrap;
}

export function fmtTime(t, ms = true) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  const cs = Math.floor((t % 1) * 100);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}${ms ? `.${String(cs).padStart(2, "0")}` : ""}`;
}

export function fmtBytes(b) {
  if (!b) return "0 B";
  const u = ["B", "KB", "MB", "GB"];
  const i = Math.min(u.length - 1, Math.floor(Math.log(b) / Math.log(1024)));
  return `${(b / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`;
}

export function debounce(fn, ms) {
  let t;
  const d = (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
  d.flush = (...a) => {
    clearTimeout(t);
    fn(...a);
  };
  return d;
}

export const timeAgo = (ts) => {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "ahora mismo";
  if (s < 3600) return `hace ${Math.floor(s / 60)} min`;
  if (s < 86400) return `hace ${Math.floor(s / 3600)} h`;
  return `hace ${Math.floor(s / 86400)} d`;
};

// Puente con Electron (con alternativas para el modo navegador)
export const bridge = window.reelforge || {
  isElectron: false,
  pickFiles: null,
  showItemInFolder: null,
  openExternal: (url) => window.open(url, "_blank"),
  openFlow: () => window.open("https://labs.google/fx/tools/flow", "_blank"),
  window: null,
  onFlowDownload: () => {},
};

export function pickFilesBrowser(accept = "video/*,image/*,audio/*", multiple = true) {
  return new Promise((resolve) => {
    const input = h("input", { type: "file", accept, multiple });
    input.onchange = () => resolve([...input.files]);
    input.click();
  });
}
