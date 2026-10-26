"""Generación en la nube de Google (Imagen, Veo y Gemini Omni Flash)
mediante la API oficial de Gemini. Google Flow no ofrece API pública: la
pestaña "Google Flow" de la app abre Flow con tu cuenta e importa lo que
descargues."""

from __future__ import annotations

import base64
import threading
import time
from pathlib import Path

import httpx

from .. import config
from ..jobs import JobContext
from ..project import media_output_path, register_media


def _client():
    from google import genai

    key = config.load_settings().get("gemini_api_key")
    if not key:
        raise RuntimeError("Añade tu clave de API de Google AI Studio en Ajustes → Google.")
    return genai.Client(api_key=key)


def generate_image(ctx: JobContext, prompt: str, aspect: str = "9:16", count: int = 1) -> list[dict]:
    from google.genai import types

    ctx.progress(0.1, "Enviando a Imagen…")
    client = _client()
    model = config.load_settings()["google_image_model"]
    resp = client.models.generate_images(
        model=model,
        prompt=prompt,
        config=types.GenerateImagesConfig(number_of_images=max(1, min(4, count)), aspect_ratio=aspect),
    )
    out_items = []
    for img in resp.generated_images or []:
        out = media_output_path(".png", "imagen")
        out.write_bytes(img.image.image_bytes)
        item = register_media(out, source="google", name=f"Imagen · {prompt[:30]}", meta={"prompt": prompt, "model": model})
        out.unlink(missing_ok=True)
        out_items.append(item.model_dump())
    if not out_items:
        raise RuntimeError("Google no devolvió imágenes (posible filtro de seguridad)")
    return out_items


def generate_video(ctx: JobContext, prompt: str, aspect: str = "9:16", image_path: str | None = None,
                   negative: str = "", duration: int | None = None, resolution: str | None = None) -> dict:
    model = config.load_settings()["google_video_model"].strip()
    if model.startswith("gemini-omni"):
        out = _omni_video(ctx, model, prompt, aspect, image_path, negative, duration, resolution)
        label = "Omni"
    else:
        out = _veo_video(ctx, model, prompt, aspect, image_path, negative)
        label = "Veo"
    item = register_media(out, source="google", name=f"{label} · {prompt[:30]}", meta={"prompt": prompt, "model": model})
    out.unlink(missing_ok=True)
    return item.model_dump()


def _omni_video(ctx: JobContext, model: str, prompt: str, aspect: str, image_path: str | None, negative: str,
                duration: int | None, resolution: str | None) -> Path:
    """Gemini Omni Flash: se usa la API de Interactions (no la de Veo)."""
    client = _client()
    if not hasattr(client, "interactions"):
        raise RuntimeError("Tu versión de google-genai no soporta Gemini Omni. Actualízala: "
                           "Modelos → Paquetes, o `pip install -U google-genai`.")
    text = prompt if not negative else f"{prompt}\n\nAvoid: {negative}"
    if image_path:
        mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        payload = [{"type": "text", "text": text}, {"type": "image", "data": Path(image_path), "mime_type": mime}]
    else:
        payload = text
    fmt = {"type": "video", "aspect_ratio": aspect if aspect in ("9:16", "16:9") else "9:16"}
    if duration:
        fmt["duration"] = f"{int(duration)}s"
    if resolution:
        fmt["resolution"] = resolution
    result: dict = {}

    def call() -> None:
        try:
            result["interaction"] = client.interactions.create(
                model=model, input=payload, response_format=fmt, timeout=900
            )
        except Exception as exc:  # noqa: BLE001 - se reporta en el trabajo
            result["error"] = exc

    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    started = time.time()
    while worker.is_alive():
        ctx.check()
        elapsed = time.time() - started
        ctx.progress(min(0.9, 0.05 + elapsed / 180), f"Gemini Omni generando… {int(elapsed)} s")
        worker.join(2)
    if "error" in result:
        raise RuntimeError(f"Gemini Omni: {result['error']}")
    interaction = result["interaction"]
    video = getattr(interaction, "output_video", None)
    if video is None or not (video.data or video.uri):
        errors = getattr(interaction, "errors", None)
        status = getattr(interaction, "status", "?")
        raise RuntimeError(f"Gemini Omni no devolvió vídeo (estado: {status}). {errors or 'Posible filtro de seguridad.'}")
    out = media_output_path(".mp4", "omni")
    if video.data:
        out.write_bytes(base64.b64decode(video.data))
    else:
        key = config.load_settings().get("gemini_api_key", "")
        with httpx.Client(follow_redirects=True, timeout=300) as http:
            r = http.get(video.uri, headers={"x-goog-api-key": key})
            r.raise_for_status()
            out.write_bytes(r.content)
    return out


def _veo_video(ctx: JobContext, model: str, prompt: str, aspect: str, image_path: str | None,
               negative: str) -> Path:
    from google.genai import types

    client = _client()
    kwargs = {}
    if image_path:
        with open(image_path, "rb") as f:
            data = f.read()
        mime = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        kwargs["image"] = types.Image(image_bytes=data, mime_type=mime)
    cfg = types.GenerateVideosConfig(aspect_ratio=aspect, number_of_videos=1,
                                     negative_prompt=negative or None)
    ctx.progress(0.05, "Enviando a Veo…")
    op = client.models.generate_videos(model=model, prompt=prompt, config=cfg, **kwargs)
    started = time.time()
    while not op.done:
        ctx.check()
        elapsed = time.time() - started
        ctx.progress(min(0.9, 0.05 + elapsed / 240), f"Veo generando… {int(elapsed)} s")
        time.sleep(8)
        op = client.operations.get(op)
    if getattr(op, "error", None):
        raise RuntimeError(f"Veo: {op.error}")
    videos = (op.response.generated_videos if op.response else None) or []
    if not videos:
        raise RuntimeError("Veo no devolvió vídeo (posible filtro de seguridad)")
    out = media_output_path(".mp4", "veo")
    client.files.download(file=videos[0].video)
    videos[0].video.save(str(out))
    return out
