"""Gestor de modelos: estado, descargas (con progreso) y extras opcionales."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx

from . import captions, config, gpu
from .ai import hub, image, music, video
from .ffmpeg import CREATE_NO_WINDOW
from .jobs import JobContext


def _hub_dir() -> Path:
    return Path(os.environ.get("HF_HOME", config.MODELS_DIR / "huggingface")) / "hub"


def _repo_dir(repo: str) -> Path:
    return _hub_dir() / ("models--" + repo.replace("/", "--"))


def _repo_ready(repo: str) -> bool:
    snap = _repo_dir(repo) / "snapshots"
    return snap.is_dir() and any(snap.iterdir())


def _dir_size(path: Path) -> int:
    total = 0
    if path.is_dir():
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
    return total


def _whisper_loader(name: str) -> Callable[[], Any]:
    def load():
        from faster_whisper import download_model

        download_model(name)

    return load


def _kokoro_loader():
    from kokoro import KPipeline

    pipe = KPipeline(lang_code="e", repo_id="hexgrad/Kokoro-82M", device="cpu")
    for voice in ("ef_dora", "em_alex", "em_santa"):
        pipe.load_voice(voice)


def _image_loader(mid: str):
    cfg = image.MODELS[mid]
    if cfg.get("generic"):
        return lambda: hub.download(_NullCtx(), cfg["repo"])  # sólo descarga, sin cargar 16 GB en RAM
    return lambda: image._load(mid)


def _video_loader(mid: str):
    return lambda: video._load(mid)


def _music_loader(mid: str):
    return lambda: music._load(mid)


def entries() -> list[dict[str, Any]]:
    out = [
        {"id": "kokoro", "group": "Voz", "name": "Kokoro 82M", "repos": ["hexgrad/Kokoro-82M"], "size_gb": 0.35,
         "vram": 1.0, "module": "kokoro", "license": "Apache-2.0",
         "desc": "Voz natural local en español, inglés, portugués, francés e italiano."},
        {"id": "whisper:large-v3-turbo", "group": "Transcripción", "name": "Whisper large-v3 turbo",
         "repos": ["mobiuslabsgmbh/faster-whisper-large-v3-turbo"], "size_gb": 1.6, "vram": 2.5,
         "module": "faster_whisper", "license": "MIT", "desc": "Transcripción precisa con tiempos por palabra."},
        {"id": "whisper:small", "group": "Transcripción", "name": "Whisper small (CPU rápido)",
         "repos": ["Systran/faster-whisper-small"], "size_gb": 0.5, "vram": 1.0, "module": "faster_whisper",
         "license": "MIT", "desc": "Ligero, ideal si la GPU está ocupada."},
    ]
    for mid, cfg in image.MODELS.items():
        repos = [cfg["repo"]]
        if not cfg.get("generic"):
            repos += ["madebyollin/sdxl-vae-fp16-fix"] + (["ByteDance/SDXL-Lightning"] if mid == "sdxl-lightning" else [])
        out.append({"id": f"image:{mid}", "group": "Imagen", "name": cfg["name"], "repos": repos,
                    "size_gb": cfg["size_gb"], "vram": cfg["vram"], "module": "diffusers",
                    "license": cfg.get("license", "OpenRAIL++ / SAI"),
                    "desc": cfg.get("desc", "Modelo ligero de 2023: rápido pero con más errores en manos y caras.")})
    for mid, cfg in video.MODELS.items():
        out.append({"id": f"video:{mid}", "group": "Vídeo", "name": cfg["name"], "repos": [cfg["repo"]],
                    "size_gb": cfg["size_gb"], "vram": cfg["vram"], "module": "diffusers",
                    "license": "Apache-2.0" if mid.startswith("wan") else "LTX OpenRAIL-M",
                    "desc": "Clips cortos generados en local (lento en 8 GB: 3-10 min por clip)."})
    for mid, cfg in music.MODELS.items():
        out.append({"id": f"music:{mid}", "group": "Música", "name": cfg["name"], "repos": [cfg["repo"]],
                    "size_gb": cfg["size_gb"], "vram": 2.0, "module": "transformers", "license": "CC-BY-NC-4.0",
                    "desc": "Música instrumental de fondo a partir de texto."})
    for m in hub.custom_models():
        group = "Imagen" if m["kind"] == "image" else "Vídeo"
        out.append({"id": f"hf:{m['repo']}", "group": group, "name": m["name"], "repos": [m["repo"]],
                    "size_gb": m.get("size_gb") or 0, "vram": min(8.0, m.get("size_gb") or 8.0), "module": "diffusers",
                    "license": m.get("license") or "ver ficha", "custom": True,
                    "desc": m.get("note") or "Añadido desde Hugging Face (cargador genérico)."})
    for e in out:
        e["installed"] = gpu.has_module(e["module"])
        e["downloaded"] = all(_repo_ready(r) for r in e["repos"])
        e["partial"] = not e["downloaded"] and any(_repo_dir(r).is_dir() for r in e["repos"])
        e["disk_gb"] = round(sum(_dir_size(_repo_dir(r)) for r in e["repos"]) / 1024**3, 4)
    return out


def _rmtree(path: Path) -> None:
    def onerror(func, p, _exc):  # Windows: archivos de sólo lectura en la caché de HF
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=onerror)
    else:
        shutil.rmtree(path, onerror=onerror)


def delete_model(model_id: str) -> dict[str, Any]:
    """Borra del disco los pesos de un modelo (sin tocar repos que usa otro modelo descargado)."""
    all_entries = entries()
    entry = next((e for e in all_entries if e["id"] == model_id), None)
    if not entry:
        raise ValueError("Modelo desconocido")
    gpu.release()
    shared = {r for e in all_entries if e["id"] != model_id and e["downloaded"] for r in e["repos"]}
    freed, kept = 0, []
    for repo in entry["repos"]:
        if repo in shared:
            kept.append(repo)
            continue
        folder = _repo_dir(repo)
        if folder.is_dir():
            freed += _dir_size(folder)
            _rmtree(folder)
            if folder.exists():
                raise RuntimeError(f"No se pudo borrar {folder} (¿está en uso? Cierra otras generaciones e inténtalo de nuevo)")
    return {"id": model_id, "freed_gb": round(freed / 1024**3, 4), "kept_shared": kept}


CACHE_FOLDERS = ("segments", "previews", "render", "gen", "uploads")


def cache_usage() -> dict[str, float]:
    return {name: round(_dir_size(config.CACHE_DIR / name) / 1024**3, 2) for name in CACHE_FOLDERS}


def clear_cache() -> dict[str, Any]:
    """Borra cachés regenerables (clips preprocesados, vistas previas, temporales)."""
    freed = 0
    for name in CACHE_FOLDERS:
        folder = config.CACHE_DIR / name
        if folder.is_dir():
            freed += _dir_size(folder)
            _rmtree(folder)
    return {"freed_gb": round(freed / 1024**3, 2)}


def _loader_for(model_id: str) -> Callable[[], Any]:
    if model_id == "kokoro":
        return _kokoro_loader
    if model_id.startswith("whisper:"):
        return _whisper_loader(model_id.split(":", 1)[1])
    if model_id.startswith("hf:"):
        repo = model_id[3:]
        return lambda: hub.download(_NullCtx(), repo)
    kind, mid = model_id.split(":", 1)
    return {"image": _image_loader, "video": _video_loader, "music": _music_loader}[kind](mid)


class _NullCtx:
    def progress(self, *_a, **_k) -> None:
        pass


def download(ctx: JobContext, model_id: str) -> dict:
    entry = next((e for e in entries() if e["id"] == model_id), None)
    if not entry:
        raise ValueError("Modelo desconocido")
    if not entry["installed"]:
        raise RuntimeError(f"Falta el paquete Python '{entry['module']}'. Ejecuta la instalación de IA.")
    expected = entry["size_gb"] * 1024**3
    dirs = [_repo_dir(r) for r in entry["repos"]]
    start = sum(_dir_size(d) for d in dirs)
    done = threading.Event()
    error: list[BaseException] = []

    def work():
        try:
            gpu.release()
            _loader_for(model_id)()
        except BaseException as exc:  # noqa: BLE001
            error.append(exc)
        finally:
            gpu.release()
            done.set()

    threading.Thread(target=work, daemon=True).start()
    while not done.wait(1.0):
        size = sum(_dir_size(d) for d in dirs)
        frac = min(0.97, max(0.0, size - start) / max(1, expected - start)) if not entry["downloaded"] else 0.9
        ctx.progress(frac, f"Descargando… {size / 1024**3:.2f} / ~{entry['size_gb']:.1f} GB")
    if error:
        raise error[0]
    return {"id": model_id, "downloaded": True}


def fonts_status() -> list[dict]:
    return [{"family": fam, "file": f, "installed": (config.FONTS_DIR / f).is_file()} for fam, f in captions.FONT_FILES.items()]


def download_fonts(ctx: JobContext) -> list[dict]:
    config.FONTS_DIR.mkdir(parents=True, exist_ok=True)
    items = list(captions.FONT_URLS.items())
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for i, (fname, url) in enumerate(items):
            ctx.progress(i / len(items), f"Fuente {fname}")
            dest = config.FONTS_DIR / fname
            if dest.is_file():
                continue
            r = client.get(url)
            r.raise_for_status()
            dest.write_bytes(r.content)
    return fonts_status()


def _genai_supports_omni() -> bool:
    try:
        from importlib.metadata import version

        major, minor = (int(x) for x in version("google-genai").split(".")[:2])
        return (major, minor) >= (2, 33)
    except Exception:  # noqa: BLE001
        return False


EXTRAS = {
    "engines": {"name": "Actualizar motores de IA (diffusers, transformers)",
                "packages": ["-U", "diffusers", "transformers", "accelerate", "huggingface_hub"],
                "module": "diffusers", "check": lambda: False,
                "note": "Los modelos nuevos de Hugging Face suelen requerir la última versión de diffusers."},
    "google": {"name": "Google GenAI actualizado (Gemini Omni Flash)", "packages": ["-U", "google-genai>=2.33"],
               "module": "google.genai", "check": _genai_supports_omni,
               "note": "Necesario para generar vídeo con gemini-omni-1.1-flash."},
    "xtts": {"name": "Clonación de voz XTTS-v2", "packages": ["coqui-tts>=0.24"], "module": "TTS",
             "note": "Licencia CPML (no comercial). ~2 GB adicionales al primer uso."},
    "ai": {"name": "Paquete de IA local completo", "packages": ["-r", str(config.BACKEND_DIR / "requirements-ai.txt")],
           "module": "diffusers",
           "check": lambda: all(gpu.has_module(m) for m in ("diffusers", "cv2", "bitsandbytes")),
           "note": "diffusers, transformers, faster-whisper, kokoro, OpenCV (Clips) y bitsandbytes (modelos en 4 bits)…"},
}


def extras_status() -> list[dict]:
    return [{"id": k, **{kk: vv for kk, vv in v.items() if kk not in ("packages", "check")},
             "installed": v["check"]() if "check" in v else gpu.has_module(v["module"])}
            for k, v in EXTRAS.items()]


def install_extra(ctx: JobContext, extra_id: str) -> dict:
    extra = EXTRAS.get(extra_id)
    if not extra:
        raise ValueError("Extra desconocido")
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade-strategy", "only-if-needed", *extra["packages"]]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW)
    ctx.track(proc)
    lines: list[str] = []
    started = time.time()
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line.rstrip())
        ctx.progress(min(0.95, (time.time() - started) / 600), line.strip()[:90] or None)
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("pip falló:\n" + "\n".join(lines[-10:]))
    return {"id": extra_id, "installed": True}
