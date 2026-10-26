"""Carpetas del proyecto. Todo queda junto a la aplicación para que sea fácil de encontrar."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = APP_DIR / "config"
# Datos generados (salidas, muestras, cola). PANORAMA360_HOME permite moverlos a otro disco.
ROOT = Path(os.environ.get("PANORAMA360_HOME", APP_DIR))
OUTPUT_DIR = ROOT / "salidas"
SAMPLES_DIR = ROOT / "muestras"
DATA_DIR = ROOT / "datos"
REFS_DIR = DATA_DIR / "referencias"
WEIGHTS_DIR = DATA_DIR / "pesos"

for _folder in (OUTPUT_DIR, SAMPLES_DIR, DATA_DIR, REFS_DIR, WEIGHTS_DIR):
    _folder.mkdir(parents=True, exist_ok=True)
