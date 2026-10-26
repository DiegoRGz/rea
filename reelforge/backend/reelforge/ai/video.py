"""Generación de vídeo local para 8 GB de VRAM.

* Wan 2.1 T2V 1.3B: texto → vídeo 480×832 (vertical).
* LTX-Video 2B: imagen → vídeo (anima una imagen generada o importada).

El codificador de texto T5 (≈10 GB) se ejecuta en CPU usando la RAM (48 GB) y
sólo el transformer y el VAE ocupan la GPU. Si aun así falta VRAM, se
reintenta con descarga secuencial a CPU (más lento, pero siempre cabe)."""

from __future__ import annotations

from typing import Any

from .. import gpu
from ..jobs import JobCancelled, JobContext
from ..project import get_media, media_output_path, register_media

MODELS = {
    "wan2.1-1.3b": {
        "name": "Wan 2.1 1.3B (texto → vídeo)",
        "repo": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "mode": "t2v",
        "fps": 16,
        "size_gb": 17.0,
        "vram": 8.0,
    },
    "ltx-video": {
        "name": "LTX-Video 2B (imagen → vídeo)",
        "repo": "Lightricks/LTX-Video",
        "mode": "i2v",
        "fps": 24,
        "size_gb": 19.0,
        "vram": 8.0,
    },
}

NEGATIVE = (
    "blurry, low quality, static, distorted, deformed, watermark, text, subtitles, worst quality, jpeg artifacts, "
    "ugly, extra limbs, poorly drawn face, messy background"
)


class _Holder:
    def __init__(self, pipe, text_encoder):
        self.pipe = pipe
        self.text_encoder = text_encoder
        self.sequential = False


def _load(model_id: str) -> _Holder:
    import torch

    cfg = MODELS[model_id]
    if model_id == "wan2.1-1.3b":
        from diffusers import AutoencoderKLWan, WanPipeline

        vae = AutoencoderKLWan.from_pretrained(cfg["repo"], subfolder="vae", torch_dtype=torch.float32)
        pipe = WanPipeline.from_pretrained(cfg["repo"], vae=vae, torch_dtype=torch.bfloat16)
    else:
        from diffusers import LTXImageToVideoPipeline

        pipe = LTXImageToVideoPipeline.from_pretrained(cfg["repo"], torch_dtype=torch.bfloat16)
    if hasattr(pipe.vae, "enable_tiling"):
        try:
            pipe.vae.enable_tiling()
        except Exception:  # noqa: BLE001
            pass
    return _Holder(pipe, pipe.text_encoder)


def _encode(holder: _Holder, prompt: str, negative: str) -> dict[str, Any]:
    """Codifica el prompt en CPU y devuelve kwargs de embeddings para el pipeline."""
    import torch

    pipe = holder.pipe
    pipe.register_modules(text_encoder=holder.text_encoder)
    holder.text_encoder.to("cpu")
    with torch.no_grad():
        res = pipe.encode_prompt(
            prompt=prompt,
            negative_prompt=negative,
            do_classifier_free_guidance=True,
            device=torch.device("cpu"),
            dtype=torch.bfloat16,
        )
    pipe.register_modules(text_encoder=None)
    if len(res) == 2:
        return {"prompt_embeds": res[0], "negative_prompt_embeds": res[1]}
    return {
        "prompt_embeds": res[0],
        "prompt_attention_mask": res[1],
        "negative_prompt_embeds": res[2],
        "negative_prompt_attention_mask": res[3],
    }


def generate(ctx: JobContext, prompt: str, model: str = "wan2.1-1.3b", seconds: float = 3.0,
             image_media_id: str | None = None, steps: int | None = None, seed: int | None = None,
             landscape: bool = False) -> dict:
    import torch
    from diffusers.utils import export_to_video, load_image

    if model.startswith("hf:"):
        from . import hub

        return hub.generate_video(ctx, model, prompt, seconds, image_media_id, steps, seed, landscape)
    if model not in MODELS:
        raise ValueError(f"Modelo desconocido: {model}")
    cfg = MODELS[model]
    if gpu.device() != "cuda":
        raise RuntimeError("La generación de vídeo local necesita una GPU NVIDIA con CUDA.")
    ctx.progress(0.03, "Cargando modelo de vídeo (la primera descarga puede tardar)…")
    holder: _Holder = gpu.acquire(f"video:{model}", lambda: _load(model), ctx, "Cargando modelo de vídeo")
    pipe = holder.pipe

    ctx.progress(0.1, "Codificando el prompt en CPU…")
    embeds = _encode(holder, prompt, NEGATIVE)
    width, height = (832, 480) if landscape else (480, 832)
    fps = cfg["fps"]
    if model == "wan2.1-1.3b":
        frames = int(round(seconds * fps / 4)) * 4 + 1  # Wan: 4k+1
        frames = max(17, min(81, frames))
        steps = steps or 30
        extra: dict[str, Any] = {"guidance_scale": 5.0}
    else:
        frames = int(round(seconds * fps / 8)) * 8 + 1  # LTX: 8k+1
        frames = max(25, min(121, frames))
        steps = steps or 40
        if not image_media_id:
            raise ValueError("LTX-Video necesita una imagen de partida")
        media = get_media(image_media_id)
        if not media:
            raise FileNotFoundError("Imagen no encontrada")
        extra = {"image": load_image(media.path), "guidance_scale": 3.0}

    def on_step(p, step, timestep, kwargs):
        if ctx.cancelled:
            raise JobCancelled()
        ctx.progress(0.15 + 0.75 * (step + 1) / steps, f"Generando vídeo · paso {step + 1}/{steps}")
        return kwargs

    gen = torch.Generator(device="cpu").manual_seed(seed if seed is not None and seed >= 0 else 42)
    def run():
        kw = {k: v.to("cuda") for k, v in embeds.items()}
        return pipe(**kw, **extra, width=width, height=height, num_frames=frames, num_inference_steps=steps,
                    generator=gen, callback_on_step_end=on_step).frames[0]

    try:
        if not holder.sequential:
            pipe.to("cuda")
        video = run()
    except torch.cuda.OutOfMemoryError:
        ctx.progress(0.15, "VRAM insuficiente: reintentando con descarga secuencial (más lento)…")
        pipe.to("cpu")
        torch.cuda.empty_cache()
        pipe.enable_sequential_cpu_offload()
        holder.sequential = True
        video = run()
    ctx.progress(0.93, "Codificando vídeo…")
    out = media_output_path(".mp4", "vid")
    export_to_video(video, str(out), fps=fps)
    item = register_media(out, source="video", name=f"IA · {prompt[:32]}",
                          meta={"prompt": prompt, "model": model, "frames": frames, "fps": fps})
    out.unlink(missing_ok=True)
    return item.model_dump()
