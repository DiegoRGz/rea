"""Actualización desde la propia app: descarga la última versión del motor y la
interfaz desde GitHub, instala sólo las dependencias nuevas y deja la versión
lista para el próximo arranque (sin recompilar ni reinstalar el .exe)."""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from . import config, gpu
from .ffmpeg import CREATE_NO_WINDOW
from .jobs import JobContext

REPO = "DiegoRGz/rea"
BRANCH = "claude/cool-turing-pcvhqq"
API_COMMIT = f"https://api.github.com/repos/{REPO}/commits/{BRANCH}"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/{BRANCH}"
PARTS = ("reelforge/backend/", "reelforge/ui/")


def app_dir() -> Path:
    """Carpeta de versiones descargadas (Electron lee aquí `current.json`)."""
    local = os.environ.get("LOCALAPPDATA")
    if os.name == "nt" and local:
        return Path(local) / "ReelForge" / "app"
    return config.DATA_DIR / "app"


def current_version() -> dict[str, Any]:
    f = config.APP_ROOT / "version.json"
    try:
        data = json.loads(f.read_text("utf-8"))
        return {"sha": data.get("sha"), "date": data.get("date"), "source": "actualización"}
    except (OSError, json.JSONDecodeError):
        return {"sha": None, "date": None, "source": "instalación inicial"}


def check() -> dict[str, Any]:
    r = httpx.get(API_COMMIT, headers={"accept": "application/vnd.github+json"}, timeout=15, follow_redirects=True)
    r.raise_for_status()
    data = r.json()
    latest = {
        "sha": data["sha"],
        "date": data["commit"]["committer"]["date"],
        "message": data["commit"]["message"].splitlines()[0][:140],
    }
    current = current_version()
    pending = _pending()
    return {
        "current": current,
        "latest": latest,
        "available": current["sha"] != latest["sha"] and (pending or {}).get("sha") != latest["sha"],
        "pending_restart": bool(pending and pending.get("sha") != current["sha"]),
    }


def _pending() -> dict[str, Any] | None:
    try:
        return json.loads((app_dir() / "current.json").read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _pip(ctx: JobContext, requirements: Path, label: str) -> None:
    cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade-strategy",
           "only-if-needed", "-r", str(requirements)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace", creationflags=CREATE_NO_WINDOW)
    ctx.track(proc)
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line:
            tail = (tail + [line])[-12:]
            ctx.progress(None, f"{label}: {line[:90]}")
    proc.wait()
    ctx.untrack(proc)
    if proc.returncode != 0:
        raise RuntimeError("No se pudieron instalar las dependencias nuevas:\n" + "\n".join(tail))


def apply(ctx: JobContext) -> dict[str, Any]:
    info = check()
    latest = info["latest"]
    ctx.progress(0.03, "Descargando la última versión…")
    buf = io.BytesIO()
    with httpx.stream("GET", ZIP_URL, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        for chunk in r.iter_bytes(1 << 16):
            ctx.check()
            buf.write(chunk)
            if total:
                ctx.progress(0.03 + 0.4 * buf.tell() / total, f"Descargando… {buf.tell() / 1024**2:.1f} MB")
    zf = zipfile.ZipFile(buf)
    sha = zf.comment.decode("ascii", "ignore").strip() or latest["sha"]
    root = zf.namelist()[0].split("/")[0] + "/"
    dest = app_dir() / sha[:12]
    tmp = dest.with_name(dest.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    ctx.progress(0.45, "Descomprimiendo…")
    count = 0
    for name in zf.namelist():
        rel = name[len(root):]
        if not rel.startswith(PARTS) or name.endswith("/") or "/tests/" in rel or "__pycache__" in rel:
            continue
        target = tmp / rel[len("reelforge/"):]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(name))
        count += 1
    if not (tmp / "backend" / "reelforge" / "__main__.py").is_file() or not (tmp / "ui" / "index.html").is_file():
        raise RuntimeError("La descarga no contiene la app completa; inténtalo de nuevo más tarde")
    (tmp / "version.json").write_text(json.dumps({"sha": sha, "date": latest["date"]}), "utf-8")

    # Dependencias nuevas (pip sólo instala lo que falte)
    ctx.progress(0.5, "Comprobando dependencias…")
    _pip(ctx, tmp / "backend" / "requirements.txt", "Dependencias")
    if gpu.has_module("diffusers"):
        ctx.progress(0.75, "Comprobando paquetes de IA…")
        _pip(ctx, tmp / "backend" / "requirements-ai.txt", "Paquetes de IA")

    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    current = app_dir() / "current.json"
    current.write_text(json.dumps({"dir": str(dest), "sha": sha, "date": latest["date"], "installed": time.time()}),
                       "utf-8")
    # Conserva sólo la versión nueva y la anterior (para volver atrás si falla)
    versions = sorted((p for p in app_dir().iterdir() if p.is_dir() and not p.name.endswith(".part")),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    running = config.APP_ROOT.resolve()
    for old in versions[2:]:
        if old.resolve() != running:
            shutil.rmtree(old, ignore_errors=True)
    ctx.progress(1.0, "Actualización lista: reinicia la app")
    return {"sha": sha, "files": count, "dir": str(dest), "restart": True}
