// Cálculos de la línea de tiempo (equivalentes a project.py del motor).

export function clipLength(clip, media) {
  if (clip.kind === "image") return Math.max(0.2, clip.duration);
  const end = clip.src_out ?? media?.duration ?? clip.duration;
  return Math.max(0.1, (end - clip.src_in) / Math.max(0.1, clip.speed));
}

export function layout(project, mediaMap) {
  const lengths = project.clips.map((c) => clipLength(c, mediaMap.get(c.media_id)));
  const trans = project.clips.slice(0, -1).map((c, i) => {
    const t = c.transition;
    if (!t || t.type === "none" || t.duration <= 0) return 0;
    const limit = Math.min(lengths[i], lengths[i + 1]) * 0.45;
    return Math.round(Math.max(0.05, Math.min(t.duration, limit)) * 1000) / 1000;
  });
  let start = 0;
  const items = project.clips.map((clip, i) => {
    const tOut = trans[i] || 0;
    const item = { clip, index: i, start, len: lengths[i], visEnd: start + lengths[i] - tOut, tOut };
    start += lengths[i] - tOut;
    return item;
  });
  let total = start;
  if (!items.length) {
    for (const a of project.audio) total = Math.max(total, a.start + audioLength(a, mediaMap.get(a.media_id)));
  }
  return { items, total, trans };
}

export function audioLength(a, media) {
  const end = a.src_out ?? media?.duration ?? 0;
  return Math.max(0, end - a.src_in);
}

export function clipAt(lay, t) {
  for (const it of lay.items) if (t >= it.start && t < it.visEnd) return it;
  return lay.items[lay.items.length - 1] && t >= lay.items[lay.items.length - 1].start ? lay.items[lay.items.length - 1] : null;
}

export const uid = () => Math.random().toString(16).slice(2, 12);

export function newClip(media) {
  return {
    id: uid(),
    media_id: media.id,
    kind: media.kind === "video" ? "video" : "image",
    src_in: 0,
    src_out: media.kind === "video" ? media.duration : null,
    duration: media.kind === "video" ? media.duration || 3 : 3,
    speed: 1,
    volume: 1,
    motion: media.kind === "image" ? "zoom_in" : "none",
    fit: media.width && media.height && media.width > media.height ? "blur" : "cover",
    filter: "none",
    transition: { type: "none", duration: 0.5 },
  };
}

export function newAudio(media, role, start = 0) {
  return { id: uid(), media_id: media.id, role, start, src_in: 0, src_out: null, volume: role === "music" ? 0.25 : 1, fade_in: 0, fade_out: role === "music" ? 1.5 : 0, loop: role === "music" };
}

export const CSS_FILTERS = {
  none: "none",
  vivid: "saturate(1.35) contrast(1.06)",
  cinematic: "contrast(1.08) saturate(.92) sepia(.12) hue-rotate(-8deg)",
  warm: "sepia(.25) saturate(1.15)",
  cool: "hue-rotate(12deg) saturate(.9) brightness(1.03)",
  bw: "grayscale(1) contrast(1.15)",
  vintage: "sepia(.45) contrast(.92) brightness(1.04)",
  matte: "contrast(.88) brightness(1.06) saturate(.86)",
};

export const TRANSITION_ANIM = {
  none: "tpNone", fade: "tpFade", fadeblack: "tpFade", fadewhite: "tpFlash", dissolve: "tpFade", zoomin: "tpZoom",
  smoothleft: "tpLeft", smoothright: "tpRight", smoothup: "tpUp", smoothdown: "tpDown", slideleft: "tpLeft",
  slideright: "tpRight", slideup: "tpUp", slidedown: "tpDown", wipeleft: "tpLeft", wiperight: "tpRight",
  circleopen: "tpCircle", circleclose: "tpCircle", radial: "tpCircle", pixelize: "tpBlur", hblur: "tpBlur",
  squeezeh: "tpZoom", diagtl: "tpUp", hlslice: "tpLeft", vertopen: "tpZoom", horzopen: "tpZoom",
};

/** Transformación CSS equivalente al Ken Burns del render. */
export function motionTransform(motion, p) {
  const k = 6.9;
  switch (motion) {
    case "zoom_in": return `scale(${1 + 0.18 * p})`;
    case "zoom_out": return `scale(${1.18 - 0.18 * p})`;
    case "pan_left": return `scale(1.16) translateX(${-k * (1 - 2 * p)}%)`;
    case "pan_right": return `scale(1.16) translateX(${k * (1 - 2 * p)}%)`;
    case "pan_up": return `scale(1.16) translateY(${-k * (1 - 2 * p)}%)`;
    case "pan_down": return `scale(1.16) translateY(${k * (1 - 2 * p)}%)`;
    default: return "none";
  }
}
