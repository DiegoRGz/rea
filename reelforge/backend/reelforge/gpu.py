"""Detección de hardware y gestión de VRAM (un modelo grande cargado a la vez)."""

from __future__ import annotations

import gc
import importlib.util
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable

from .ffmpeg import CREATE_NO_WINDOW

_slot_lock = threading.RLock()
_slot: dict[str, Any] = {"key": None, "model": None}


def has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def torch_info() -> dict[str, Any]:
    info: dict[str, Any] = {"torch": None, "cuda": False}
    if not has_module("torch"):
        return info
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda"] = bool(torch.cuda.is_available())
        if info["cuda"]:
            props = torch.cuda.get_device_properties(0)
            info["device"] = props.name
            info["vram_gb"] = round(props.total_memory / 1024**3, 1)
            info["capability"] = f"{props.major}.{props.minor}"
            free, total = torch.cuda.mem_get_info()
            info["vram_free_gb"] = round(free / 1024**3, 2)
            info["bf16"] = bool(torch.cuda.is_bf16_supported())
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
    return info


def nvidia_smi() -> dict[str, Any] | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.used,utilization.gpu,temperature.gpu,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, creationflags=CREATE_NO_WINDOW,
        ).stdout.strip().splitlines()
        if not out:
            return None
        name, total, used, util, temp, driver = [x.strip() for x in out[0].split(",")]
        return {
            "name": name,
            "vram_total_mb": int(float(total)),
            "vram_used_mb": int(float(used)),
            "util": int(float(util)),
            "temp": int(float(temp)),
            "driver": driver,
        }
    except Exception:  # noqa: BLE001
        return None


def system_info() -> dict[str, Any]:
    ram = None
    try:
        if os.name == "nt":
            import ctypes

            class MEMSTAT(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

            st = MEMSTAT()
            st.dwLength = ctypes.sizeof(MEMSTAT)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))  # type: ignore[attr-defined]
            ram = round(st.ullTotalPhys / 1024**3, 1)
        else:
            with open("/proc/meminfo") as f:
                kb = int(f.readline().split()[1])
                ram = round(kb / 1024**2, 1)
    except Exception:  # noqa: BLE001
        pass
    return {"cpu_count": os.cpu_count(), "ram_gb": ram, "gpu": nvidia_smi(), "loaded_model": _slot["key"]}


def device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        return "cpu"


def download_meter() -> Callable[[], str | None]:
    """Devuelve una función que informa de cuánto ha crecido la caché de modelos."""
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"

    def size() -> int:
        total = 0
        if hub.is_dir():
            for root, _, files in os.walk(hub):
                if os.path.basename(root) != "blobs":
                    continue
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        return total

    base = size()

    def detail() -> str | None:
        grown = (size() - base) / 1024**2
        return f"descargados {grown:,.0f} MB" if grown >= 1 else None

    return detail


def acquire(key: str, loader: Callable[[], Any], ctx: Any = None, label: str = "Cargando modelo") -> Any:
    """Devuelve el modelo `key`, descargando de la VRAM el anterior si es distinto.

    Con `ctx`, la carga (y la descarga inicial de pesos) muestra progreso vivo."""
    with _slot_lock:
        if _slot["key"] == key and _slot["model"] is not None:
            return _slot["model"]
        release()
        if ctx is not None:
            from .jobs import heartbeat

            with heartbeat(ctx, f"{label} (la primera vez se descarga)", detail=download_meter(), expected=120):
                model = loader()
        else:
            model = loader()
        _slot["key"], _slot["model"] = key, model
        return model


def release() -> None:
    with _slot_lock:
        _slot["key"], _slot["model"] = None, None
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
        except Exception:  # noqa: BLE001
            pass


def recommendations() -> dict[str, Any]:
    """Perfil recomendado según la VRAM detectada (pensado para RTX 5050 8 GB)."""
    info = torch_info()
    vram = info.get("vram_gb") or 0
    if vram >= 12:
        tier = "alta"
    elif vram >= 7:
        tier = "media"
    elif info.get("cuda"):
        tier = "baja"
    else:
        tier = "cpu"
    return {
        "tier": tier,
        "vram_gb": vram,
        "whisper": "large-v3-turbo" if vram >= 4 else "small",
        "image": "flux2-klein" if vram >= 6 else "sdxl-lightning",
        "video": "wan2.1-1.3b" if vram >= 6 else None,
        "llm": "qwen3:8b" if vram >= 7 else "qwen3:4b",
        "notes": [
            "Los modelos se cargan de uno en uno para no superar la VRAM.",
            "Con 48 GB de RAM se usa descarga a CPU (offload) en los modelos de vídeo.",
        ],
    }
