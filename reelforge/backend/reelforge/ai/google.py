"""Generación en la nube de Google (Imagen y Veo, los modelos que usa Flow)
mediante la API oficial de Gemini. Google Flow no ofrece API pública: la
pestaña "Google Flow" de la app abre Flow con tu cuenta e importa lo que
descargues."""

from __future__ import annotations

import time

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
                   negative: str = "") -> dict:
    from google.genai import types

    client = _client()
    model = config.load_settings()["google_video_model"]
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
    item = register_media(out, source="google", name=f"Veo · {prompt[:30]}", meta={"prompt": prompt, "model": model})
    out.unlink(missing_ok=True)
    return item.model_dump()
