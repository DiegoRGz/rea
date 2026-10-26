"""Generación de imágenes local.

* FLUX.2 [klein] 4B y Z-Image Turbo (recomendados): modelos de 2026 que en 8 GB
  se cargan comprimidos a 4 bits (NF4) con el cargador genérico.
* SDXL Lightning / Turbo: opción ligera y rápida (fp16, VAE fp16-fix)."""

from __future__ import annotations

from .. import config, gpu
from ..jobs import JobCancelled, JobContext
from ..project import media_output_path, register_media

MODELS = {
    "flux2-klein": {
        "name": "FLUX.2 [klein] 4B (recomendado)",
        "repo": "black-forest-labs/FLUX.2-klein-4B",
        "generic": True,
        "steps": 4,
        "guidance": 1.0,
        "vram": 7.0,
        "size_gb": 16.0,
        "license": "Apache-2.0",
        "desc": "Calidad muy alta, buena anatomía y texto legible en 4 pasos. En 8 GB se carga en 4 bits.",
    },
    "z-image-turbo": {
        "name": "Z-Image Turbo (fotorrealista)",
        "repo": "Tongyi-MAI/Z-Image-Turbo",
        "generic": True,
        "steps": 9,
        "guidance": 0.0,
        "vram": 7.5,
        "size_gb": 20.0,
        "license": "Apache-2.0",
        "desc": "Fotos muy realistas y texto bilingüe en la imagen. En 8 GB se carga en 4 bits.",
    },
    "sdxl-lightning": {
        "name": "SDXL Lightning (ligero, generación 2023)",
        "repo": "stabilityai/stable-diffusion-xl-base-1.0",
        "steps": 4,
        "vram": 7.5,
        "size_gb": 7.0,
    },
    "sdxl-turbo": {
        "name": "SDXL Turbo (ultrarrápido, baja calidad)",
        "repo": "stabilityai/sdxl-turbo",
        "steps": 2,
        "vram": 6.0,
        "size_gb": 7.0,
    },
}

ASPECTS = {
    "9:16": (768, 1344),
    "4:5": (896, 1152),
    "1:1": (1024, 1024),
    "16:9": (1344, 768),
}

STYLE_PRESETS = {
    "none": "",
    "cinematic": "cinematic film still, dramatic lighting, shallow depth of field, 35mm, highly detailed",
    "photo": "ultra realistic photograph, natural light, sharp focus, 8k, detailed skin texture",
    "anime": "anime key visual, vibrant colors, detailed background, studio quality",
    "3d": "3d render, pixar style, soft global illumination, octane render",
    "comic": "comic book illustration, bold ink lines, halftone shading, vibrant",
    "neon": "cyberpunk neon lights, night city, glowing reflections, moody atmosphere",
    "minimal": "minimalist flat illustration, clean shapes, pastel palette",
}

NEGATIVE = "lowres, blurry, deformed, bad anatomy, extra fingers, watermark, text, logo, jpeg artifacts"


def _load(model_id: str):
    import torch
    from diffusers import AutoencoderKL, EulerDiscreteScheduler, StableDiffusionXLPipeline, UNet2DConditionModel

    cfg = MODELS[model_id]
    vae = AutoencoderKL.from_pretrained("madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16)
    if model_id == "sdxl-lightning":
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file

        unet_cfg = UNet2DConditionModel.load_config(cfg["repo"], subfolder="unet")
        unet = UNet2DConditionModel.from_config(unet_cfg).to(torch.float16)
        ckpt = hf_hub_download("ByteDance/SDXL-Lightning", "sdxl_lightning_4step_unet.safetensors")
        unet.load_state_dict(load_file(ckpt, device="cpu"))
        pipe = StableDiffusionXLPipeline.from_pretrained(
            cfg["repo"], unet=unet, vae=vae, torch_dtype=torch.float16, variant="fp16"
        )
        pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing")
    else:
        from diffusers import AutoPipelineForText2Image

        pipe = AutoPipelineForText2Image.from_pretrained(cfg["repo"], vae=vae, torch_dtype=torch.float16, variant="fp16")
    pipe.vae.enable_tiling()
    if gpu.device() == "cuda":
        if config.load_settings().get("low_vram", True):
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cuda")
    return pipe


def generate(ctx: JobContext, prompt: str, model: str = "sdxl-lightning", aspect: str = "9:16", count: int = 1,
             seed: int | None = None, style: str = "none", negative: str = "", steps: int | None = None,
             guidance: float | None = None) -> list[dict]:
    if model.startswith("hf:"):
        from . import hub

        full = ", ".join(p for p in [prompt.strip(), STYLE_PRESETS.get(style, "")] if p)
        return hub.generate_image(ctx, model, full, aspect, count, seed, negative, steps, guidance)
    if model not in MODELS:
        raise ValueError(f"Modelo desconocido: {model}")
    if MODELS[model].get("generic"):
        return _generate_generic(ctx, prompt, model, aspect, count, seed, style, negative, steps, guidance)
    import torch

    if gpu.device() != "cuda":
        ctx.progress(0.02, "Sin GPU CUDA: la generación en CPU será muy lenta")
    ctx.progress(0.05, "Cargando modelo de imagen (la primera vez se descarga)…")
    pipe = gpu.acquire(f"image:{model}", lambda: _load(model), ctx, "Cargando modelo de imagen")
    width, height = ASPECTS.get(aspect, ASPECTS["9:16"])
    if model == "sdxl-turbo":
        width, height = int(width * 0.75) // 64 * 64, int(height * 0.75) // 64 * 64
    full_prompt = ", ".join(p for p in [prompt.strip(), STYLE_PRESETS.get(style, "")] if p)
    steps = MODELS[model]["steps"]
    results = []
    base_seed = seed if seed is not None and seed >= 0 else int(torch.randint(0, 2**31 - 1, (1,)).item())
    for i in range(max(1, min(8, count))):
        ctx.check()

        def on_step(pipeline, step, timestep, kwargs, i=i):
            if ctx.cancelled:
                raise JobCancelled()
            ctx.progress(0.1 + 0.85 * (i + (step + 1) / steps) / count, f"Imagen {i + 1}/{count} · paso {step + 1}/{steps}")
            return kwargs

        gen = torch.Generator(device="cpu").manual_seed(base_seed + i)
        image = pipe(
            prompt=full_prompt,
            negative_prompt=(negative or NEGATIVE) if model == "sdxl-lightning" else None,
            num_inference_steps=steps,
            guidance_scale=0.0,
            width=width,
            height=height,
            generator=gen,
            callback_on_step_end=on_step,
        ).images[0]
        out = media_output_path(".png", "img")
        image.save(out)
        item = register_media(out, source="image", name=f"IA · {prompt[:32]}",
                              meta={"prompt": prompt, "model": model, "seed": base_seed + i, "style": style})
        out.unlink(missing_ok=True)
        results.append(item.model_dump())
    return results


def _generate_generic(ctx: JobContext, prompt: str, model: str, aspect: str, count: int, seed: int | None,
                      style: str, negative: str, steps: int | None, guidance: float | None) -> list[dict]:
    import random

    from . import hub

    cfg = MODELS[model]
    pipe = gpu.acquire(f"image:{model}", lambda: hub.load_pipeline(cfg["repo"], cfg["size_gb"]), ctx,
                       f"Cargando {cfg['name']}")
    width, height = ASPECTS.get(aspect, ASPECTS["9:16"])
    full_prompt = ". ".join(p for p in [prompt.strip(), STYLE_PRESETS.get(style, "")] if p)
    steps = steps or cfg["steps"]
    guidance = cfg["guidance"] if guidance is None else guidance
    base = seed if seed is not None and seed >= 0 else random.randint(0, 2**31 - 1)
    results = []
    for i in range(max(1, min(8, count))):
        ctx.check()
        ctx.progress(0.1 + 0.85 * i / count, f"Imagen {i + 1}/{count}")
        kw = hub._call_kwargs(pipe, prompt=full_prompt, negative=negative if guidance > 1 else "", width=width,
                              height=height, steps=steps, guidance=guidance, frames=None, image=None,
                              seed=base + i, ctx=ctx, total_steps=steps)
        image = pipe(**kw).images[0]
        out = media_output_path(".png", "img")
        image.save(out)
        item = register_media(out, source="image", name=f"IA · {prompt[:32]}",
                              meta={"prompt": prompt, "model": model, "seed": base + i, "style": style})
        out.unlink(missing_ok=True)
        results.append(item.model_dump())
    return results
