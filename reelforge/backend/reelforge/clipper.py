"""De vídeo largo a clips virales: transcripción, selección de los mejores
momentos con IA, reencuadre vertical que sigue a la persona que habla y
edición viral automática de cada clip."""

from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any, Callable, Optional

import numpy as np
from pydantic import BaseModel

from . import brand, config, ffmpeg, gpu, retention
from .ai import llm, stt
from .ffmpeg import CREATE_NO_WINDOW
from .jobs import JobContext
from .project import Captions, Clip, Project, TextOverlay, Word, get_media, save_project
from . import captions as captions_mod

YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")


class ClipperRequest(BaseModel):
    media_id: str
    count: int = 6
    min_len: float = 20.0
    max_len: float = 55.0
    lang: str = "es"
    whisper_model: str = "large-v3-turbo"
    reframe: bool = True
    caption_style: str = "viral"
    auto_edit: bool = True
    broll: str = "none"
    hook_title: bool = True
    brand: bool = True


# ------------------------------------------------------------- frases


def sentences(words: list[dict]) -> list[dict]:
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        end = re.search(r"[.!?…]$", w["w"]) or nxt is None or nxt["s"] - w["e"] > 0.8 or len(cur) >= 40
        if end:
            out.append({"i": len(out), "s": cur[0]["s"], "e": cur[-1]["e"], "text": " ".join(x["w"] for x in cur)})
            cur = []
    return out


HOOK_WORDS = ("nadie", "nunca", "secreto", "error", "verdad", "dinero", "increíble", "mejor", "peor", "cómo", "por qué",
              "problema", "truco", "importante", "cuidado", "jamás", "todos", "realmente", "imagina", "historia")


def _heuristic_score(text: str, first: str, wps: float) -> float:
    low = text.lower()
    score = 40 + min(20, 6 * sum(low.count(h) for h in HOOK_WORDS))
    score += 10 if "?" in first or "¿" in first else 0
    score += 8 if re.search(r"\d", text) else 0
    score += 8 if "!" in text or "¡" in text else 0
    score += 10 if 2.2 <= wps <= 3.8 else 0
    return min(97.0, score)


def _fit_bounds(sents: list[dict], i: int, j: int, lo: float, hi: float) -> tuple[int, int]:
    while j + 1 < len(sents) and sents[j]["e"] - sents[i]["s"] < lo:
        j += 1
    while j > i and sents[j]["e"] - sents[i]["s"] > hi:
        j -= 1
    return i, j


def heuristic_candidates(sents: list[dict], req: ClipperRequest) -> list[dict]:
    target = (req.min_len + req.max_len) / 2
    cands = []
    for i, first in enumerate(sents):
        j = i
        while j + 1 < len(sents) and sents[j]["e"] - first["s"] < target:
            j += 1
        i, j = _fit_bounds(sents, i, j, req.min_len, req.max_len)
        text = " ".join(s["text"] for s in sents[i:j + 1])
        dur = max(1.0, sents[j]["e"] - sents[i]["s"])
        cands.append({"start": i, "end": j, "score": _heuristic_score(text, first["text"], len(text.split()) / dur),
                      "title": first["text"][:70], "hook": " ".join(first["text"].split()[:7]),
                      "reason": "Selección automática por densidad de ganchos y ritmo"})
    return cands


def llm_candidates(sents: list[dict], req: ClipperRequest, progress: Callable[[str], None]) -> list[dict]:
    system = (
        "Eres editor jefe de una agencia que convierte vídeos largos en clips virales para TikTok/Reels/Shorts. "
        "Eliges fragmentos que se entienden SIN contexto, empiezan con un gancho fuerte (pregunta, afirmación "
        "polémica, dato sorprendente o promesa) y terminan en un remate. Responde SOLO JSON: "
        "{\"clips\": [{\"start\": int, \"end\": int, \"title\": str, \"hook\": str, \"score\": int, "
        "\"reason\": str, \"hashtags\": [str]}]} donde start/end son índices de frase, title es un título "
        "viral (máx. 60 caracteres), hook un texto gancho para pantalla (máx. 7 palabras) y score 0-100 "
        "es el potencial viral."
    )
    out: list[dict] = []
    chunk: list[dict] = []
    chunks = []
    for s in sents:
        chunk.append(s)
        if s["e"] - chunk[0]["s"] > 420 or sum(len(c["text"]) for c in chunk) > 9000:
            chunks.append(chunk)
            chunk = chunk[-3:]
    if chunk:
        chunks.append(chunk)
    for n, ch in enumerate(chunks):
        progress(f"La IA busca momentos virales ({n + 1}/{len(chunks)})…")
        lines = "\n".join(f"[{s['i']}] ({int(s['s'] // 60)}:{int(s['s'] % 60):02d}) {s['text']}" for s in ch)
        user = (f"Idioma: {req.lang}. Cada clip debe durar entre {req.min_len:.0f} y {req.max_len:.0f} s. "
                f"Propón hasta {max(2, req.count // max(1, len(chunks)) + 2)} clips de este tramo:\n{lines}")
        data = llm.chat_json(system, user, num_ctx=16384)
        ids = {s["i"] for s in ch}
        for c in data.get("clips", []):
            try:
                i, j = int(c["start"]), int(c["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if i in ids and j in ids and j >= i:
                i, j = _fit_bounds(sents, i, j, req.min_len, req.max_len)
                out.append({**c, "start": i, "end": j, "score": float(c.get("score") or 50)})
    return out


def select(cands: list[dict], sents: list[dict], count: int) -> list[dict]:
    chosen: list[dict] = []
    for c in sorted(cands, key=lambda c: c["score"], reverse=True):
        s, e = sents[c["start"]]["s"], sents[c["end"]]["e"]
        overlap = any(min(e, x["e"]) - max(s, x["s"]) > 0.3 * (e - s) for x in chosen)
        if not overlap:
            chosen.append({**c, "s": s, "e": e})
        if len(chosen) >= count:
            break
    return chosen


# ------------------------------------------------------ seguimiento facial


def _face_detector(width: int, height: int) -> Optional[Callable[[np.ndarray], list[tuple[float, float, float]]]]:
    """Devuelve detect(frame_bgr) -> [(cx, cy, área)] normalizados, o None si no hay OpenCV."""
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    model = config.MODELS_DIR / "face_detection_yunet_2023mar.onnx"
    if not model.is_file():
        try:
            import httpx

            r = httpx.get(YUNET_URL, follow_redirects=True, timeout=60)
            r.raise_for_status()
            model.parent.mkdir(parents=True, exist_ok=True)
            model.write_bytes(r.content)
        except Exception:  # noqa: BLE001 - se usa Haar como respaldo
            pass
    if model.is_file() and hasattr(cv2, "FaceDetectorYN"):
        yn = cv2.FaceDetectorYN.create(str(model), "", (width, height), 0.6, 0.3, 50)

        def detect(frame):
            _, faces = yn.detect(frame)
            if faces is None:
                return []
            return [((f[0] + f[2] / 2) / width, (f[1] + f[3] / 2) / height, f[2] * f[3] / (width * height))
                    for f in faces]

        return detect
    if not hasattr(cv2, "CascadeClassifier"):  # OpenCV 5 ya no trae los clasificadores Haar
        return None
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def detect_haar(frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found = cascade.detectMultiScale(gray, 1.1, 5, minSize=(24, 24))
        return [((x + w / 2) / width, (y + h / 2) / height, w * h / (width * height)) for x, y, w, h in found]

    return detect_haar


def _frames(path: str, start: float, dur: float, fps: float, width: int):
    info = ffmpeg.probe(path)
    sw, sh = info.get("width") or 16, info.get("height") or 9
    height = int(round(width * sh / sw / 2)) * 2
    proc = subprocess.Popen(
        [ffmpeg.binary(), "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", path,
         "-vf", f"fps={fps},scale={width}:{height}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, creationflags=CREATE_NO_WINDOW)
    size = width * height * 3
    assert proc.stdout is not None
    k = 0
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        yield start + k / fps, np.frombuffer(buf, np.uint8).reshape(height, width, 3)
        k += 1
    proc.wait()


def _simplify(points: list[list[float]], tol: float = 0.012) -> list[list[float]]:
    """Ramer-Douglas-Peucker: menos fotogramas clave con la misma trayectoria."""
    if len(points) < 3:
        return points
    (t0, c0), (t1, c1) = points[0], points[-1]
    worst, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        t, c = points[i]
        expected = c0 + (c1 - c0) * (t - t0) / max(1e-6, t1 - t0)
        if abs(c - expected) > worst:
            worst, idx = abs(c - expected), i
    if worst <= tol:
        return [points[0], points[-1]]
    return _simplify(points[: idx + 1], tol)[:-1] + _simplify(points[idx:], tol)


def smooth_track(samples: list[tuple[float, Optional[float], bool]], dead_zone: float = 0.07,
                 ease: float = 0.35) -> list[list[float]]:
    """Convierte detecciones (t, cx|None, corte) en fotogramas clave de cámara estables."""
    if not samples:
        return []
    known = [c for _, c, _ in samples if c is not None]
    cam = known[0] if known else 0.5
    target = cam
    keys: list[list[float]] = []
    for t, cx, cut in samples:
        if cx is not None:
            target = cx
        if cut:
            if keys:
                keys.append([round(t - 0.001, 3), round(cam, 4)])
            cam = target
        elif abs(target - cam) > dead_zone:
            cam += (target - cam) * ease
        if not keys or abs(keys[-1][1] - cam) > 0.004 or cut:
            keys.append([round(t, 3), round(cam, 4)])
    if keys[-1][0] < samples[-1][0]:
        keys.append([round(samples[-1][0], 3), keys[-1][1]])
    return _simplify(keys)


def track_subject(path: str, start: float, end: float, fps: float = 3.0, width: int = 480,
                  detector: Optional[Callable] = None) -> list[list[float]]:
    """Fotogramas clave [t_origen, centro_x] siguiendo a la persona que habla. [] si no hay caras."""
    frames = list(_frames(path, start, end - start, fps, width))
    if not frames:
        return []
    h, w = frames[0][1].shape[:2]
    detect = detector or _face_detector(w, h)
    if detect is None:
        return []
    samples: list[tuple[float, Optional[float], bool]] = []
    prev_small = None
    prev_cx: Optional[float] = None
    found = 0
    for t, frame in frames:
        small = frame[::8, ::8].mean(axis=2)
        cut = prev_small is not None and float(np.abs(small - prev_small).mean()) > 28
        prev_small = small
        faces = detect(frame)
        cx = None
        if faces:
            found += 1
            biggest = max(faces, key=lambda f: f[2])
            if prev_cx is None or cut:
                cx = biggest[0]
            else:
                nearest = min(faces, key=lambda f: abs(f[0] - prev_cx))
                cx = biggest[0] if biggest[2] > 1.8 * nearest[2] else nearest[0]
            prev_cx = cx
        samples.append((t, cx, cut))
    if found < max(1, len(frames) * 0.15):
        return []
    return smooth_track(samples)


# --------------------------------------------------------------- proyecto


def build_clip_project(ctx: JobContext, req: ClipperRequest, cand: dict, words: list[dict], index: int) -> dict:
    media = get_media(req.media_id)
    assert media is not None
    s, e = max(0.0, cand["s"] - 0.15), min(media.duration or cand["e"] + 0.3, cand["e"] + 0.35)
    wide = (media.width or 9) > (media.height or 16)
    track: list[list[float]] = []
    if req.reframe and wide:
        ctx.progress(None, f"Clip {index + 1}: siguiendo a la persona que habla…")
        try:
            track = track_subject(media.path, s, e)
        except Exception:  # noqa: BLE001
            track = []
    fit = "track" if track else ("blur" if wide else "cover")
    clip = Clip(media_id=media.id, kind="video", src_in=round(s, 3), src_out=round(e, 3), fit=fit, track=track)
    clip_words = [Word(w=w["w"], s=round(w["s"] - s, 3), e=round(w["e"] - s, 3)) for w in words if s <= w["s"] < e]
    st = captions_mod.STYLES.get(req.caption_style, captions_mod.STYLES["viral"])
    title = str(cand.get("title") or f"Clip {index + 1}")[:80]
    hook = str(cand.get("hook") or "").strip()
    project = Project(
        name=f"{int(cand['score'])} · {title}",
        clips=[clip],
        captions=Captions(words=clip_words, style=req.caption_style, max_words=st["max_words"],
                          uppercase=st["uppercase"]),
        texts=[TextOverlay(text=hook.upper(), start=0, end=2.6, style="title", position=0.2)] if hook and req.hook_title else [],
        script={"title": title, "hook": hook, "reason": cand.get("reason", ""), "viral_score": cand["score"],
                "caption": title, "hashtags": [h if str(h).startswith("#") else f"#{h}" for h in cand.get("hashtags", [])][:8],
                "source": {"media_id": media.id, "start": s, "end": e}},
    )
    if req.auto_edit:
        retention.auto_edit(ctx, project, retention.AutoEditOptions(
            broll=req.broll, whisper_model=req.whisper_model, lang=req.lang, beat_sync=False))
    if req.brand:
        brand.apply_brand(project)
    save_project(project)
    return {"project_id": project.id, "title": title, "score": cand["score"], "start": s, "end": e,
            "reason": cand.get("reason", ""), "tracked": bool(track), "retention": (project.score or {}).get("score")}


def _results_file(media_id: str):
    return config.DATA_DIR / "clipper" / f"{media_id}.json"


def load_results(media_id: str) -> list[dict]:
    try:
        return json.loads(_results_file(media_id).read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def run(ctx: JobContext, req: ClipperRequest) -> dict[str, Any]:
    media = get_media(req.media_id)
    if not media or media.kind != "video":
        raise ValueError("Elige un vídeo de la biblioteca")
    ctx.progress(0.02, "Transcribiendo el vídeo completo…")
    words = media.meta.get("words") or stt.transcribe_media(ctx, media.id, req.whisper_model, req.lang)["words"]
    gpu.release()
    if not words:
        raise RuntimeError("No se detectó voz en el vídeo")
    sents = sentences(words)
    ctx.progress(0.35, "Buscando los mejores momentos…")
    try:
        cands = llm_candidates(sents, req, lambda m: ctx.progress(None, m))
        method = "ia"
    except Exception:  # noqa: BLE001 - sin LLM disponible: heurística local
        cands = []
    if not cands:
        cands, method = heuristic_candidates(sents, req), "heurística"
    chosen = select(cands, sents, req.count)
    results = []
    for i, cand in enumerate(chosen):
        ctx.progress(0.45 + 0.5 * i / max(1, len(chosen)), f"Creando clip {i + 1}/{len(chosen)}: {cand.get('title', '')[:40]}")
        results.append(build_clip_project(ctx, req, cand, words, i))
    out = {"media_id": media.id, "method": method, "created": time.time(), "clips": results}
    f = _results_file(media.id)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps([out] + load_results(media.id)[:4], ensure_ascii=False, indent=1), "utf-8")
    return out
