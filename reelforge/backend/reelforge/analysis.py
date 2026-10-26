"""Análisis de un reel: ritmo de la música (beats) y puntuación de retención."""

from __future__ import annotations

import subprocess
from typing import Any

import numpy as np

from . import ffmpeg
from .project import Project, get_media, timeline_duration
from .ffmpeg import CREATE_NO_WINDOW

SR = 11025
HOP = 256


def _decode(path: str, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    args = [ffmpeg.binary(), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}"]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += ["-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(args, capture_output=True, check=True, creationflags=CREATE_NO_WINDOW).stdout
    return np.frombuffer(raw, dtype=np.float32)


def onset_envelope(y: np.ndarray) -> np.ndarray:
    """Flujo espectral positivo (energía de los ataques) por bloque de HOP muestras."""
    n_fft = 1024
    if len(y) < n_fft:
        return np.zeros(0)
    frames = 1 + (len(y) - n_fft) // HOP
    idx = np.arange(n_fft)[None, :] + HOP * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(y[idx] * np.hanning(n_fft), axis=1))
    spec = np.log1p(spec * 10)
    flux = np.maximum(0.0, np.diff(spec, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    if flux.max() > 0:
        flux = flux / flux.max()
    return flux


def detect_beats(path: str, start: float = 0.0, duration: float | None = None) -> dict[str, Any]:
    """Devuelve {bpm, beats[]} (segundos relativos a `start`)."""
    y = _decode(path, start, duration)
    env = onset_envelope(y)
    fps = SR / HOP
    if len(env) < fps * 2:
        return {"bpm": None, "beats": []}
    # Tempo por autocorrelación entre 70 y 180 BPM
    env_c = env - env.mean()
    ac = np.correlate(env_c, env_c, mode="full")[len(env_c) - 1:]
    lo, hi = int(fps * 60 / 180), int(fps * 60 / 70)
    lag = lo + int(np.argmax(ac[lo:hi]))
    period = lag / fps
    # Fase: desplazamiento de la rejilla que acumula más energía de ataque
    best_phase, best_score = 0, -1.0
    for phase in range(lag):
        score = env[phase::lag].sum()
        if score > best_score:
            best_phase, best_score = phase, score
    beats = [round(t, 3) for t in np.arange(best_phase / fps, len(env) / fps, period)]
    return {"bpm": round(60 / period, 1), "beats": beats}


def music_beats(project: Project) -> list[float]:
    """Beats de la primera pista de música, en tiempo de la línea de tiempo."""
    total = timeline_duration(project)
    for item in project.audio:
        if item.role != "music":
            continue
        media = get_media(item.media_id)
        if not media:
            continue
        src_len = (item.src_out or media.duration or total) - item.src_in
        res = detect_beats(media.path, item.src_in, min(src_len, total - item.start + 1))
        beats = [item.start + b for b in res["beats"]]
        if item.loop and src_len > 0 and beats:
            local = [b - item.start for b in beats]
            reps = int((total - item.start) / src_len) + 1
            beats = [item.start + r * src_len + b for r in range(reps) for b in local]
        return [b for b in beats if 0 <= b <= total]
    return []


# --------------------------------------------------------------- retención

CTA_WORDS = ("sígueme", "sigueme", "suscríbete", "comenta", "guarda", "comparte", "follow", "like", "dale")


def retention_score(project: Project) -> dict[str, Any]:
    """Puntuación 0-100 basada en buenas prácticas de reels y consejos accionables."""
    from .project import clip_lengths, effective_transitions

    total = max(0.1, timeline_duration(project))
    lengths = clip_lengths(project)
    trans = effective_transitions(project, lengths)
    changes = [0.0]
    t = 0.0
    for i, ln in enumerate(lengths):
        t += ln - (trans[i] if i < len(trans) else 0)
        changes.append(t)
    changes += [b.start for b in project.broll] + [b.start + b.duration for b in project.broll]
    changes += [e.start for e in project.effects if e.type in ("punch", "shake")]
    changes += [x.start for x in project.texts]
    changes = sorted({round(c, 2) for c in changes if 0 <= c <= total} | {round(total, 2)})
    gaps = np.diff(changes) if len(changes) > 1 else np.array([total])
    words = project.captions.words if project.captions.enabled else []
    first_word = words[0].s if words else None
    hook_text = any(x.start < 1.0 for x in project.texts)
    spoken = sum(w.e - w.s for w in words)
    wps = len(words) / total if words else 0.0
    cta = any(any(c in w.w.lower() for c in CTA_WORDS) for w in words if w.s > total * 0.6) or any(
        x.start > total - 4 for x in project.texts)
    has_music = any(a.role == "music" for a in project.audio)
    sfx = sum(1 for a in project.audio if a.role == "sfx")
    keywords = sum(1 for w in words if w.emph)

    checks = [
        ("Gancho inmediato", 18, first_word is not None and first_word <= 0.6 or hook_text,
         "Empieza a hablar o muestra un texto gancho en los primeros 0,5 s."),
        ("Texto gancho en pantalla", 8, hook_text, "Añade un título llamativo en los primeros 2-3 s (Texto → Título)."),
        ("Duración ideal (15-45 s)", 12, 15 <= total <= 45 if total < 60 else False,
         f"Dura {total:.0f} s: los reels de 15-45 s retienen mejor; recorta lo prescindible."),
        ("Ritmo visual (cambio cada ≤ 3 s)", 16, float(np.mean(gaps)) <= 3.0,
         f"Hay un cambio visual cada {float(np.mean(gaps)):.1f} s de media: añade cortes, zooms o B-roll."),
        ("Sin tramos estáticos largos", 10, float(np.max(gaps)) <= 4.5,
         f"El tramo estático más largo dura {float(np.max(gaps)):.1f} s: rómpelo con un zoom o un B-roll."),
        ("Subtítulos", 12, bool(words) and spoken >= 0.5 * total * 0.6,
         "Genera subtítulos animados: la mayoría ve los reels sin sonido."),
        ("Ritmo de voz dinámico", 6, 2.0 <= wps <= 3.8 if words else False,
         f"Velocidad de habla {wps:.1f} palabras/s: lo ideal es 2,3-3,5 (sube la velocidad de la voz o corta silencios)."),
        ("Palabras clave resaltadas", 6, keywords >= max(1, int(total / 8)),
         "Resalta palabras clave en color (edición viral → palabras clave)."),
        ("Música de fondo", 5, has_music, "Añade música de fondo con ducking automático."),
        ("Efectos de sonido", 3, sfx >= 2, "Añade whooshes y pops en transiciones y palabras clave."),
        ("Llamada a la acción final", 4, cta, "Termina pidiendo seguir, comentar o guardar."),
    ]
    score = sum(weight for _, weight, ok, _ in checks if ok)
    return {
        "score": int(score),
        "grade": "Viral" if score >= 85 else "Bueno" if score >= 70 else "Mejorable" if score >= 50 else "Flojo",
        "checks": [{"name": n, "ok": bool(ok), "weight": w, "tip": None if ok else tip} for n, w, ok, tip in checks],
        "metrics": {"duration": round(total, 1), "avg_shot": round(float(np.mean(gaps)), 2),
                    "max_static": round(float(np.max(gaps)), 2), "words_per_sec": round(wps, 2),
                    "keywords": keywords, "sfx": sfx},
    }
