"""Detección del equipo y perfil de rendimiento que se adapta a él."""

from __future__ import annotations

import platform
from dataclasses import asdict, dataclass

import psutil
import torch

GIB = 1024**3


@dataclass(frozen=True)
class Hardware:
    device: str  # "cuda", "mps" o "cpu"
    gpu_name: str
    vram_gib: float
    ram_gib: float
    system: str


@dataclass(frozen=True)
class Profile:
    key: str
    label: str
    description: str
    dtype: str  # "float16" o "float32"
    offload: str  # "none", "model" o "sequential"
    base_width: int  # ancho de la primera pasada (alto = ancho / 2)
    refine_tile: int  # píxeles por mosaico en la pasada de detalle
    decode_tile: int  # píxeles por mosaico al decodificar con el VAE
    full_decode: bool  # decodificar la base entera (mejor continuidad) en vez de por mosaicos
    upscale_tile: int  # píxeles de entrada por mosaico del reescalador
    default_final_width: int
    default_refine: bool

    def as_dict(self) -> dict:
        return asdict(self)


PROFILES: dict[str, Profile] = {
    "alta": Profile(
        "alta", "Alta (12 GB+ VRAM)", "Todo en la GPU; detalle a 3072 px y salida 6144 px.",
        "float16", "none", 1536, 1024, 1024, True, 512, 6144, True,
    ),
    "media": Profile(
        "media", "Media (8–12 GB VRAM)", "Descarga a RAM los modelos que no están en uso; ideal para 8 GB.",
        "float16", "model", 1536, 1024, 1024, True, 384, 4096, True,
    ),
    "baja": Profile(
        "baja", "Baja (5–8 GB VRAM)", "Mosaicos más pequeños para no agotar la memoria de video.",
        "float16", "model", 1536, 768, 768, False, 256, 4096, True,
    ),
    "minima": Profile(
        "minima", "Mínima (<5 GB VRAM)", "Carga capa por capa: funciona, pero es lento.",
        "float16", "sequential", 1280, 768, 512, False, 192, 3072, False,
    ),
    "mac": Profile(
        "mac", "Mac Apple Silicon", "Usa Metal (MPS) con memoria unificada.",
        "float16", "none", 1536, 768, 768, False, 256, 4096, True,
    ),
    "cpu": Profile(
        "cpu", "Solo CPU", "Sin GPU compatible: funciona pero cada panorámica tarda mucho.",
        "float32", "none", 1280, 768, 512, False, 192, 3072, False,
    ),
}


def detect() -> Hardware:
    ram = psutil.virtual_memory().total / GIB
    system = f"{platform.system()} {platform.release()}"
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        return Hardware("cuda", props.name, props.total_memory / GIB, ram, system)
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return Hardware("mps", "Apple Silicon (MPS)", ram, ram, system)
    return Hardware("cpu", platform.processor() or "CPU", 0.0, ram, system)


def recommend(hw: Hardware) -> Profile:
    if hw.device == "mps":
        return PROFILES["mac"]
    if hw.device == "cpu":
        return PROFILES["cpu"]
    # Las GPU "de 8 GB" reportan algo menos (≈7.6–8.0 GiB) y Windows reserva otra parte.
    if hw.vram_gib >= 11.5:
        return PROFILES["alta"]
    if hw.vram_gib >= 7.0:
        return PROFILES["media"]
    if hw.vram_gib >= 4.5:
        return PROFILES["baja"]
    return PROFILES["minima"]


def describe(hw: Hardware, profile: Profile) -> str:
    memory = f"{hw.vram_gib:.1f} GB VRAM" if hw.device == "cuda" else f"{hw.ram_gib:.0f} GB memoria"
    return f"{hw.gpu_name} · {memory} · {hw.ram_gib:.0f} GB RAM → perfil {profile.label}"
