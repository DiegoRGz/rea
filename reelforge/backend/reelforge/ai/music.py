"""Música de fondo con MusicGen (transformers). Pesos con licencia CC-BY-NC."""

from __future__ import annotations

from .. import gpu
from ..jobs import JobContext
from ..project import media_output_path, register_media

MODELS = {
    "musicgen-small": {"name": "MusicGen Small (rápido)", "repo": "facebook/musicgen-small", "size_gb": 2.4},
    "musicgen-medium": {"name": "MusicGen Medium (calidad)", "repo": "facebook/musicgen-medium", "size_gb": 8.0},
}

LICENSE = "Pesos MusicGen: CC-BY-NC 4.0 (uso no comercial)."


def _load(model_id: str):
    import torch
    from transformers import AutoProcessor, MusicgenForConditionalGeneration

    repo = MODELS[model_id]["repo"]
    processor = AutoProcessor.from_pretrained(repo)
    dtype = torch.float16 if gpu.device() == "cuda" else torch.float32
    model = MusicgenForConditionalGeneration.from_pretrained(repo, torch_dtype=dtype).to(gpu.device())
    return processor, model


def generate(ctx: JobContext, prompt: str, seconds: float = 20, model: str = "musicgen-small") -> dict:
    import numpy as np
    import soundfile as sf
    import torch

    ctx.progress(0.05, "Cargando MusicGen…")
    processor, mg = gpu.acquire(f"music:{model}", lambda: _load(model))
    seconds = max(4.0, min(30.0, float(seconds)))
    tokens = int(seconds * 50)  # ~50 tokens por segundo de audio
    ctx.progress(0.2, f"Componiendo {seconds:.0f} s de música…")
    inputs = processor(text=[prompt], padding=True, return_tensors="pt").to(gpu.device())
    with torch.no_grad():
        audio = mg.generate(**inputs, do_sample=True, guidance_scale=3.0, max_new_tokens=tokens)
    rate = mg.config.audio_encoder.sampling_rate
    data = audio[0, 0].float().cpu().numpy()
    peak = float(np.max(np.abs(data))) or 1.0
    out = media_output_path(".wav", "musica")
    sf.write(str(out), data / peak * 0.89, rate)
    item = register_media(out, source="music", name=f"Música · {prompt[:30]}",
                          meta={"prompt": prompt, "model": model, "license": LICENSE})
    out.unlink(missing_ok=True)
    return item.model_dump()
