"""Catálogo de modelos (incluido + del usuario) y sus imágenes de muestra."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .paths import CONFIG_DIR, DATA_DIR, SAMPLES_DIR

USER_MODELS_FILE = DATA_DIR / "modelos_usuario.json"

SCHEDULERS = {
    "dpmpp_2m_karras": "DPM++ 2M Karras",
    "dpmpp_sde_karras": "DPM++ SDE Karras",
    "euler_a": "Euler Ancestral",
    "euler": "Euler",
}

SAMPLE_PROMPTS = {
    "Estadio nevado": "snow covered baseball stadium with green seats, overcast winter sky, distant desert plains and hills, light poles",
    "Plaza al atardecer": "colonial town square at golden hour, cobblestone, fountain, warm lights, mountains in the distance",
    "Bosque con niebla": "misty pine forest clearing at sunrise, soft volumetric light rays, moss, wildflowers",
    "Playa tropical": "tropical beach with turquoise water, palm trees, white sand, clear blue sky with soft clouds",
}
SAMPLE_SEED = 360360


@dataclass
class ModelEntry:
    key: str
    name: str
    source: str
    style: str = "Personalizado"
    description: str = ""
    variant: str | None = None
    size_gb: float | None = None
    steps: int = 30
    cfg: float = 6.0
    scheduler: str = "dpmpp_2m_karras"
    use_360_lora: bool = True
    default: bool = False
    user: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def is_local_file(self) -> bool:
        return self.source.lower().endswith((".safetensors", ".ckpt"))

    @property
    def page(self) -> str | None:
        if self.is_local_file or Path(self.source).exists():
            return None
        return f"https://huggingface.co/{self.source}"


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "modelo"


class Catalog:
    def __init__(self, config_file: Path = CONFIG_DIR / "models.json", user_file: Path = USER_MODELS_FILE):
        self.config_file = config_file
        self.user_file = user_file
        self.reload()

    def reload(self) -> None:
        config = json.loads(self.config_file.read_text(encoding="utf-8"))
        self.lora_360: dict = config["lora_360"]
        self.ip_adapter: dict = config["ip_adapter"]
        self.upscaler: dict = config["upscaler"]
        known = {item.name for item in ModelEntry.__dataclass_fields__.values()}
        self.models: dict[str, ModelEntry] = {}
        for raw in config["models"]:
            entry = ModelEntry(**{k: v for k, v in raw.items() if k in known})
            self.models[entry.key] = entry
        if self.user_file.exists():
            for raw in json.loads(self.user_file.read_text(encoding="utf-8")):
                entry = ModelEntry(**{k: v for k, v in raw.items() if k in known})
                entry.user = True
                self.models[entry.key] = entry

    def default_key(self) -> str:
        return next((m.key for m in self.models.values() if m.default), next(iter(self.models)))

    def get(self, key: str) -> ModelEntry:
        return self.models[key]

    def choices(self) -> list[tuple[str, str]]:
        return [(f"{m.name} · {m.style}", m.key) for m in self.models.values()]

    def add_user_model(self, name: str, source: str, style: str, steps: int, cfg: float, scheduler: str, use_lora: bool) -> ModelEntry:
        name, source = name.strip(), source.strip().strip('"')
        if not name or not source:
            raise ValueError("Escribe un nombre y un ID de Hugging Face o la ruta a un archivo .safetensors.")
        key = slugify(name)
        while key in self.models and not self.models[key].user:
            key += "-2"
        entry = ModelEntry(
            key=key, name=name, source=source, style=style.strip() or "Personalizado",
            description="Modelo añadido por ti.", steps=int(steps), cfg=float(cfg), scheduler=scheduler,
            use_360_lora=use_lora, user=True,
        )
        self.models[key] = entry
        self._save_user_models()
        return entry

    def remove_user_model(self, key: str) -> None:
        entry = self.models.get(key)
        if entry is None or not entry.user:
            raise ValueError("Solo se pueden quitar modelos añadidos por ti.")
        del self.models[key]
        self._save_user_models()

    def _save_user_models(self) -> None:
        self.user_file.parent.mkdir(parents=True, exist_ok=True)
        items = [asdict(m) for m in self.models.values() if m.user]
        for item in items:
            item.pop("user", None)
        self.user_file.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def is_downloaded(entry: ModelEntry) -> bool:
    if entry.is_local_file or Path(entry.source).exists():
        return Path(entry.source).exists()
    try:
        from huggingface_hub import try_to_load_from_cache

        return isinstance(try_to_load_from_cache(entry.source, "model_index.json"), str)
    except Exception:
        return False


def samples_for(key: str) -> list[tuple[str, str]]:
    """Muestras guardadas de un modelo, la más reciente primero: (ruta, leyenda)."""
    folder = SAMPLES_DIR / key
    if not folder.exists():
        return []
    items = []
    for image in sorted(folder.glob("*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True):
        caption = image.stem
        meta = image.with_suffix(".json")
        if meta.exists():
            try:
                data = json.loads(meta.read_text(encoding="utf-8"))
                caption = f"{data.get('sample_name') or data.get('prompt', '')[:40]} · semilla {data.get('seed')}"
            except (OSError, ValueError):
                pass
        items.append((str(image), caption))
    return items


def model_card(entry: ModelEntry) -> str:
    status = "✅ Descargado" if is_downloaded(entry) else "⬇️ Se descargará al usarlo por primera vez"
    size = f" (~{entry.size_gb:g} GB)" if entry.size_gb and not is_downloaded(entry) else ""
    lines = [
        f"### {entry.name}",
        f"**Estilo:** {entry.style}  ",
        f"{entry.description}  " if entry.description else "",
        f"**Estado:** {status}{size}  ",
        f"**Ajustes recomendados:** {entry.steps} pasos · CFG {entry.cfg:g} · {SCHEDULERS.get(entry.scheduler, entry.scheduler)}",
    ]
    if entry.page:
        lines.append(f"\n[Ver ejemplos oficiales del modelo ↗]({entry.page})")
    return "\n".join(line for line in lines if line)
