"""Rutas de datos y ajustes persistentes de ReelForge Studio."""

from __future__ import annotations

import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

APP_NAME = "ReelForge Studio"
VERSION = "1.0.0"

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent
APP_ROOT = BACKEND_DIR.parent


def _default_data_dir() -> Path:
    env = os.environ.get("REELFORGE_DATA")
    if env:
        return Path(env)
    if os.name == "nt":
        base = Path(os.environ.get("USERPROFILE", Path.home())) / "Documents"
    else:
        base = Path.home()
    return base / "ReelForge"


DATA_DIR = _default_data_dir()
PROJECTS_DIR = DATA_DIR / "projects"
LIBRARY_DIR = DATA_DIR / "library"
EXPORTS_DIR = DATA_DIR / "exports"
CACHE_DIR = DATA_DIR / "cache"
FONTS_DIR = DATA_DIR / "fonts"
MODELS_DIR = DATA_DIR / "models"
VOICES_DIR = DATA_DIR / "voices"
SETTINGS_FILE = DATA_DIR / "settings.json"

UI_DIR = Path(os.environ.get("REELFORGE_UI", APP_ROOT / "ui"))

DEFAULT_SETTINGS: dict[str, Any] = {
    "language": "es",
    "ffmpeg_path": "",
    "hf_home": "",
    "low_vram": True,
    "llm_provider": "ollama",  # ollama | gemini | none
    "ollama_url": "http://127.0.0.1:11434",
    "ollama_model": "qwen3:8b",
    "gemini_api_key": "",
    "hf_token": "",
    "gemini_text_model": "gemini-2.5-flash",
    "google_image_model": "imagen-4.0-generate-001",
    "google_video_model": "gemini-omni-1.1-flash",
    "tts_engine": "kokoro",
    "tts_voice": "ef_dora",
    "whisper_model": "large-v3-turbo",
    "image_model": "sdxl-lightning",
    "video_model": "wan2.1-1.3b",
    "export_preset": "tiktok",
    "caption_style": "viral",
    "accent": "violet",
}

SENSITIVE_KEYS = {"gemini_api_key", "hf_token"}

_lock = threading.Lock()


def ensure_dirs() -> None:
    for d in (
        DATA_DIR,
        PROJECTS_DIR,
        LIBRARY_DIR,
        EXPORTS_DIR,
        CACHE_DIR,
        FONTS_DIR,
        MODELS_DIR,
        VOICES_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict[str, Any]:
    with _lock:
        data = dict(DEFAULT_SETTINGS)
        if SETTINGS_FILE.exists():
            try:
                stored = json.loads(SETTINGS_FILE.read_text("utf-8"))
                if isinstance(stored, dict):
                    data.update({k: v for k, v in stored.items() if k in DEFAULT_SETTINGS})
            except (OSError, json.JSONDecodeError):
                pass
        return data


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    for key, value in patch.items():
        if key not in DEFAULT_SETTINGS:
            continue
        # La UI envía "••••" para indicar "sin cambios" en claves sensibles.
        if key in SENSITIVE_KEYS and isinstance(value, str) and set(value) == {"•"}:
            continue
        current[key] = value
    with _lock:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if SETTINGS_FILE.exists():
            shutil.copy2(SETTINGS_FILE, SETTINGS_FILE.with_suffix(".json.bak"))
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), "utf-8")
        tmp.replace(SETTINGS_FILE)
    apply_environment(current)
    return current


def public_settings() -> dict[str, Any]:
    data = load_settings()
    for key in SENSITIVE_KEYS:
        data[key] = "••••" if data.get(key) else ""
    return data


def apply_environment(settings: dict[str, Any] | None = None) -> None:
    settings = settings or load_settings()
    hf_home = settings.get("hf_home") or str(MODELS_DIR / "huggingface")
    os.environ.setdefault("HF_HOME", hf_home)
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
