"""Generación de imágenes local con SDXL (Lightning 4 pasos / Turbo).

Pensado para 8 GB de VRAM: fp16, VAE fp16-fix, VAE en mosaico y descarga a
CPU de los componentes que no se usan en cada fase."""

from __future__ import annotations

from .. import config, gpu
from ..jobs import JobCancelled, JobContext
from ..project import media_output_path, register_media

MODELS = {
    "sdxl-lightning": {
        "name": "SDXL Lightning (calidad, 4 pasos)",
        "repo": "stabilityai/stable-diffusion-xl-base-1.0",
        "steps": 4,
        "vram": 7.5,
        "size_gb": 7.0,
    },
    "sdxl-turbo": {
        "name": "SDXL Turbo (ultrarrápido)",
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
    import torch

    if model not in MODELS:
        raise ValueError(f"Modelo desconocido: {model}")
    if gpu.device() != "cuda":
        ctx.progress(0.02, "Sin GPU CUDA: la generación en CPU será muy lenta")
    ctx.progress(0.05, "Cargando modelo de imagen (la primera vez se descarga)…")
    pipe = gpu.acquire(f"image:{model}", lambda: _load(model))
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
