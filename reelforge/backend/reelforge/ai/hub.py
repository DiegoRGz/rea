"""Explorador de Hugging Face y cargador genérico de modelos `diffusers`.

Permite descubrir los modelos de imagen/vídeo que son tendencia en el Hub,
estimar si caben en la GPU, añadirlos a la app y generar con ellos sin que
el programa tenga que conocerlos de antemano."""

from __future__ import annotations

import inspect
import json
import threading
from pathlib import Path
from typing import Any

import httpx

from .. import config, gpu
from ..jobs import JobCancelled, JobContext
from ..project import get_media, media_output_path, register_media

API = "https://huggingface.co/api"
TASKS = {"image": "text-to-image", "video": "text-to-video", "i2v": "image-to-video"}
SORTS = {"trending": "trendingScore", "downloads": "downloads", "likes": "likes", "recent": "createdAt"}

# Modelos recientes destacados (se cargan con el cargador genérico).
FEATURED: list[dict[str, Any]] = [
    {"repo": "black-forest-labs/FLUX.2-klein-4B", "kind": "image", "name": "FLUX.2 [klein] 4B",
     "steps": 4, "guidance": 1.0, "license": "Apache-2.0", "size_gb": 16.0,
     "note": "Calidad muy alta en 4 pasos. En 8 GB se ejecuta con descarga a RAM."},
    {"repo": "Tongyi-MAI/Z-Image-Turbo", "kind": "image", "name": "Z-Image Turbo",
     "steps": 9, "guidance": 0.0, "license": "Apache-2.0", "size_gb": 20.0,
     "note": "Fotorrealismo y texto legible en la imagen. Con descarga a RAM en 8 GB."},
    {"repo": "Wan-AI/Wan2.2-TI2V-5B-Diffusers", "kind": "video", "name": "Wan 2.2 TI2V 5B",
     "steps": 30, "guidance": 5.0, "license": "Apache-2.0", "size_gb": 32.0, "fps": 24, "i2v": True,
     "note": "Texto o imagen → vídeo 720p. Muy lento en 8 GB."},
]

_lock = threading.Lock()


def _custom_file() -> Path:
    return config.MODELS_DIR / "custom_models.json"


def _headers() -> dict[str, str]:
    token = config.load_settings().get("hf_token") or ""
    return {"authorization": f"Bearer {token}"} if token else {}


# ----------------------------------------------------------- registro local


def custom_models() -> list[dict[str, Any]]:
    try:
        data = json.loads(_custom_file().read_text("utf-8"))
        return [m for m in data if isinstance(m, dict) and m.get("repo")]
    except (OSError, json.JSONDecodeError):
        return []


def _save_custom(items: list[dict[str, Any]]) -> None:
    f = _custom_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), "utf-8")
    tmp.replace(f)


def add_model(repo: str, kind: str, name: str | None = None, size_gb: float | None = None,
              i2v: bool = False, license_: str | None = None) -> dict[str, Any]:
    if kind not in ("image", "video"):
        raise ValueError("Tipo no válido")
    featured = next((f for f in FEATURED if f["repo"] == repo), {})
    entry = {**featured, "repo": repo, "kind": kind, "name": name or featured.get("name") or repo.split("/")[-1],
             "size_gb": size_gb or featured.get("size_gb"), "i2v": i2v or featured.get("i2v", False),
             "license": license_ or featured.get("license")}
    with _lock:
        items = [m for m in custom_models() if m["repo"] != repo]
        items.append(entry)
        _save_custom(items)
    return entry


def remove_model(repo: str) -> bool:
    with _lock:
        items = custom_models()
        keep = [m for m in items if m["repo"] != repo]
        _save_custom(keep)
        return len(keep) != len(items)


def models(kind: str) -> dict[str, dict[str, Any]]:
    """Modelos genéricos disponibles para un tipo, con id `hf:<repo>`."""
    return {f"hf:{m['repo']}": {**m, "name": f"{m['name']} · HF"} for m in custom_models() if m["kind"] == kind}


def entry(model_id: str) -> dict[str, Any]:
    repo = model_id.removeprefix("hf:")
    found = next((m for m in custom_models() if m["repo"] == repo), None)
    if not found:
        raise ValueError(f"El modelo {repo} no está añadido. Añádelo en Modelos → Explorar Hugging Face.")
    return found


# ------------------------------------------------------------- explorador


def search(kind: str = "image", sort: str = "trending", query: str = "", limit: int = 30) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "pipeline_tag": TASKS.get(kind, "text-to-image"),
        "library": "diffusers",
        "sort": SORTS.get(sort, "trendingScore"),
        "direction": -1,
        "limit": max(1, min(60, limit)),
    }
    if query:
        params["search"] = query
    r = httpx.get(f"{API}/models", params=params, headers=_headers(), timeout=20)
    r.raise_for_status()
    added = {m["repo"] for m in custom_models()}
    out = []
    for m in r.json():
        tags = m.get("tags") or []
        out.append({
            "repo": m.get("id") or m.get("modelId"),
            "likes": m.get("likes", 0),
            "downloads": m.get("downloads", 0),
            "trending": m.get("trendingScore"),
            "created": m.get("createdAt"),
            "license": next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None),
            "gated": bool(m.get("gated")),
            "added": (m.get("id") or m.get("modelId")) in added,
            "featured": any(f["repo"] == m.get("id") for f in FEATURED),
        })
    return out


def _weights_size(files: list[dict[str, Any]]) -> float:
    """Tamaño aproximado de los pesos en formato diffusers (evita contar variantes duplicadas)."""
    weights = [f for f in files if f.get("type") == "file" and str(f.get("path", "")).endswith((".safetensors", ".bin"))]
    by_folder: dict[str, list[dict[str, Any]]] = {}
    for f in weights:
        by_folder.setdefault(str(f["path"]).rpartition("/")[0], []).append(f)
    total = 0
    for group in by_folder.values():
        safet = [f for f in group if f["path"].endswith(".safetensors")] or group
        variants = [f for f in safet if ".fp16." in f["path"] or ".bf16." in f["path"]]
        chosen = variants or [f for f in safet if not any(v in f["path"] for v in (".fp32.", ".fp8.", ".nf4."))] or safet
        total += sum(int(f.get("size") or (f.get("lfs") or {}).get("size") or 0) for f in chosen)
    return round(total / 1024**3, 2)


def compatibility(size_gb: float, vram_gb: float, ram_gb: float) -> dict[str, str]:
    if size_gb <= 0:
        return {"level": "unknown", "label": "Tamaño desconocido"}
    if size_gb <= vram_gb * 0.8:
        return {"level": "ok", "label": "Cabe en tu GPU"}
    if size_gb <= ram_gb * 0.6:
        return {"level": "slow", "label": "Funciona descargando a RAM (más lento)"}
    return {"level": "no", "label": "Demasiado grande para tu equipo"}


def info(repo: str) -> dict[str, Any]:
    head = httpx.get(f"{API}/models/{repo}", headers=_headers(), timeout=20)
    head.raise_for_status()
    meta = head.json()
    tree = httpx.get(f"{API}/models/{repo}/tree/main", params={"recursive": "true"}, headers=_headers(), timeout=30)
    tree.raise_for_status()
    files = tree.json()
    paths = {f.get("path") for f in files}
    size = _weights_size(files)
    tinfo = gpu.torch_info()
    sysinfo = gpu.system_info()
    vram = tinfo.get("vram_gb") or ((sysinfo.get("gpu") or {}).get("vram_total_mb", 0) / 1024) or 8.0
    tags = meta.get("tags") or []
    return {
        "repo": repo,
        "pipeline_tag": meta.get("pipeline_tag"),
        "diffusers": "model_index.json" in paths,
        "gated": bool(meta.get("gated")),
        "license": next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None),
        "likes": meta.get("likes"),
        "downloads": meta.get("downloads"),
        "size_gb": size,
        "compat": compatibility(size, vram, sysinfo.get("ram_gb") or 16),
        "i2v": meta.get("pipeline_tag") == "image-to-video" or "image-to-video" in tags,
    }


# ------------------------------------------------------- carga y generación


def _component_gb(module) -> float:
    try:
        return sum(p.numel() * p.element_size() for p in module.parameters()) / 1024**3
    except Exception:  # noqa: BLE001
        return 0.0


def _load(repo: str):
    import torch
    from diffusers import DiffusionPipeline

    dtype = torch.bfloat16 if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else torch.float16
    token = config.load_settings().get("hf_token") or None
    pipe = DiffusionPipeline.from_pretrained(repo, torch_dtype=dtype, token=token)
    for name in ("vae",):
        vae = getattr(pipe, name, None)
        for fn in ("enable_tiling", "enable_slicing"):
            if vae is not None and hasattr(vae, fn):
                try:
                    getattr(vae, fn)()
                except Exception:  # noqa: BLE001
                    pass
    if gpu.device() != "cuda":
        return pipe
    modules = [m for m in pipe.components.values() if isinstance(m, torch.nn.Module)]
    total = sum(_component_gb(m) for m in modules)
    largest = max((_component_gb(m) for m in modules), default=0)
    free = gpu.torch_info().get("vram_free_gb") or 6.0
    # Plan de memoria: todo en GPU → por componentes → capa a capa.
    if total < free * 0.85 and not config.load_settings().get("low_vram", True):
        pipe.to("cuda")
    elif largest < free * 0.8:
        pipe.enable_model_cpu_offload()
    else:
        pipe.enable_sequential_cpu_offload()
    return pipe


def _call_kwargs(pipe, *, prompt: str, negative: str, width: int, height: int, steps: int | None,
                 guidance: float | None, frames: int | None, image, seed: int, ctx: JobContext, total_steps: int):
    params = inspect.signature(pipe.__call__).parameters
    kw: dict[str, Any] = {"prompt": prompt}
    if negative and "negative_prompt" in params:
        kw["negative_prompt"] = negative
    if "width" in params:
        kw["width"], kw["height"] = width, height
    if steps and "num_inference_steps" in params:
        kw["num_inference_steps"] = steps
    if guidance is not None and "guidance_scale" in params:
        kw["guidance_scale"] = guidance
    if frames and "num_frames" in params:
        kw["num_frames"] = frames
    if image is not None:
        if "image" not in params:
            raise ValueError("Este modelo no acepta imagen de partida")
        kw["image"] = image
    if "generator" in params:
        import torch

        kw["generator"] = torch.Generator(device="cpu").manual_seed(seed)
    if "callback_on_step_end" in params:
        def on_step(p, step, timestep, cb_kwargs):
            if ctx.cancelled:
                raise JobCancelled()
            ctx.progress(0.15 + 0.75 * (step + 1) / max(1, total_steps), f"Paso {step + 1}/{total_steps}")
            return cb_kwargs

        kw["callback_on_step_end"] = on_step
    return kw


def _align(v: int, m: int) -> int:
    return max(m, int(round(v / m)) * m)


def generate_image(ctx: JobContext, model_id: str, prompt: str, aspect: str, count: int, seed: int | None,
                   negative: str = "", steps: int | None = None, guidance: float | None = None) -> list[dict]:
    import random

    m = entry(model_id)
    ctx.progress(0.03, f"Cargando {m['name']} (la primera vez se descarga)…")
    pipe = gpu.acquire(model_id, lambda: _load(m["repo"]))
    w, h = {"9:16": (768, 1344), "4:5": (896, 1120), "1:1": (1024, 1024), "16:9": (1344, 768)}.get(aspect, (768, 1344))
    steps = steps or m.get("steps")
    guidance = guidance if guidance is not None else m.get("guidance")
    base = seed if seed is not None and seed >= 0 else random.randint(0, 2**31 - 1)
    results = []
    for i in range(max(1, min(8, count))):
        ctx.check()
        kw = _call_kwargs(pipe, prompt=prompt, negative=negative, width=_align(w, 64), height=_align(h, 64), steps=steps,
                          guidance=guidance, frames=None, image=None, seed=base + i, ctx=ctx, total_steps=steps or 30)
        image = pipe(**kw).images[0]
        out = media_output_path(".png", "img")
        image.save(out)
        item = register_media(out, source="image", name=f"{m['name']} · {prompt[:28]}",
                              meta={"prompt": prompt, "model": m["repo"], "seed": base + i})
        out.unlink(missing_ok=True)
        results.append(item.model_dump())
    return results


def generate_video(ctx: JobContext, model_id: str, prompt: str, seconds: float, image_media_id: str | None,
                   steps: int | None, seed: int | None, landscape: bool) -> dict:
    from diffusers.utils import export_to_video, load_image

    m = entry(model_id)
    ctx.progress(0.03, f"Cargando {m['name']} (la primera vez se descarga)…")
    pipe = gpu.acquire(model_id, lambda: _load(m["repo"]))
    fps = int(m.get("fps") or 16)
    frames = max(9, int(round(seconds * fps / 4)) * 4 + 1)
    w, h = (832, 480) if landscape else (480, 832)
    image = None
    if image_media_id:
        media = get_media(image_media_id)
        if not media:
            raise FileNotFoundError("Imagen no encontrada")
        image = load_image(media.path)
    steps = steps or m.get("steps") or 30
    kw = _call_kwargs(pipe, prompt=prompt, negative="", width=_align(w, 16), height=_align(h, 16), steps=steps,
                      guidance=m.get("guidance"), frames=frames, image=image, seed=seed if seed and seed >= 0 else 42,
                      ctx=ctx, total_steps=steps)
    video = pipe(**kw).frames[0]
    ctx.progress(0.93, "Codificando vídeo…")
    out = media_output_path(".mp4", "vid")
    export_to_video(video, str(out), fps=fps)
    item = register_media(out, source="video", name=f"{m['name']} · {prompt[:28]}",
                          meta={"prompt": prompt, "model": m["repo"], "frames": frames, "fps": fps})
    out.unlink(missing_ok=True)
    return item.model_dump()


def download(ctx: JobContext, repo: str) -> None:
    """Descarga los pesos con la misma selección de archivos que usa diffusers."""
    from diffusers import DiffusionPipeline

    token = config.load_settings().get("hf_token") or None
    ctx.progress(None, f"Descargando {repo}…")
    DiffusionPipeline.download(repo, token=token)
