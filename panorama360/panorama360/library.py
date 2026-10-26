"""Biblioteca de panorámicas guardadas: listado, miniaturas y metadatos."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

from .paths import DATA_DIR, OUTPUT_DIR, ROOT, SAMPLES_DIR

THUMBS_DIR = DATA_DIR / "miniaturas"
THUMB_WIDTH = 1024


def thumbnail(path: str | Path) -> str:
    """Miniatura 2:1 (las panorámicas completas pesan varios MB y harían lenta la galería)."""
    source = Path(path)
    stat = source.stat()
    key = hashlib.sha1(f"{source.resolve()}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16]
    target = THUMBS_DIR / f"{key}.jpg"
    if not target.exists():
        THUMBS_DIR.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image.convert("RGB").resize((THUMB_WIDTH, THUMB_WIDTH // 2), Image.Resampling.LANCZOS).save(
                target, quality=85
            )
    return str(target)


def list_outputs(limit: int = 200) -> list[Path]:
    files = [p for p in OUTPUT_DIR.rglob("*.jpg")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def metadata(path: str | Path) -> dict:
    meta = Path(path).with_suffix(".json")
    if not meta.exists():
        return {}
    try:
        return json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def public_relative(path: str | Path) -> str | None:
    """Ruta relativa segura para el visor, solo dentro de salidas/ o muestras/."""
    resolved = Path(path).resolve()
    for allowed in (OUTPUT_DIR.resolve(), SAMPLES_DIR.resolve()):
        if resolved.is_relative_to(allowed):
            return resolved.relative_to(ROOT.resolve()).as_posix()
    return None


def resolve_public(relative: str) -> Path | None:
    candidate = (ROOT / relative).resolve()
    if candidate.suffix.lower() != ".jpg" or not candidate.is_file():
        return None
    for allowed in (OUTPUT_DIR.resolve(), SAMPLES_DIR.resolve()):
        if candidate.is_relative_to(allowed):
            return candidate
    return None
