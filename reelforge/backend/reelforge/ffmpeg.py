"""Localización y ejecución de FFmpeg/FFprobe con progreso."""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable

from . import config

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


class FFmpegError(RuntimeError):
    pass


def _candidates(name: str) -> list[str]:
    exe = f"{name}.exe" if os.name == "nt" else name
    out: list[str] = []
    custom = config.load_settings().get("ffmpeg_path") or ""
    if custom:
        p = Path(custom)
        out.append(str(p if p.name.lower().startswith(name) else p / exe))
        out.append(str(p / "bin" / exe))
    out.append(str(config.DATA_DIR / "ffmpeg" / "bin" / exe))
    found = shutil.which(name)
    if found:
        out.append(found)
    return out


@functools.lru_cache(maxsize=4)
def binary(name: str = "ffmpeg") -> str:
    for cand in _candidates(name):
        if cand and Path(cand).is_file():
            return cand
    if name == "ffmpeg":
        try:
            import imageio_ffmpeg  # type: ignore

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:  # noqa: BLE001
            pass
    raise FFmpegError(
        f"No se encontró {name}. Instálalo desde la pantalla de configuración inicial "
        "o indica su carpeta en Ajustes."
    )


def reset_cache() -> None:
    binary.cache_clear()
    capabilities.cache_clear()


def run(args: list[str], cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise FFmpegError(f"FFmpeg falló ({proc.returncode}):\n{tail}")
    return proc


def run_with_progress(
    args: list[str],
    duration: float,
    on_progress: Callable[[float], None] | None = None,
    cwd: str | Path | None = None,
    track: Callable[[subprocess.Popen], None] | None = None,
) -> None:
    """Ejecuta ffmpeg leyendo `-progress pipe:1` para informar avance 0..1."""
    full = [args[0], "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args[1:]]
    proc = subprocess.Popen(
        full,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if track:
        track(proc)
    stderr_lines: list[str] = []

    def _drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_lines.append(line)
            if len(stderr_lines) > 200:
                del stderr_lines[:100]

    import threading

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    assert proc.stdout is not None
    for line in proc.stdout:
        if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
            try:
                us = int(line.split("=", 1)[1].strip())
            except ValueError:
                continue
            if on_progress and duration > 0:
                on_progress(min(1.0, us / 1_000_000 / duration))
    proc.wait()
    t.join(timeout=2)
    if proc.returncode != 0:
        tail = "".join(stderr_lines[-15:])
        raise FFmpegError(f"FFmpeg falló ({proc.returncode}):\n{tail}")


def probe(path: str | Path) -> dict[str, Any]:
    proc = run(
        [
            binary("ffprobe"),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )
    data = json.loads(proc.stdout or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    info: dict[str, Any] = {
        "duration": float(fmt.get("duration") or 0) or None,
        "has_audio": audio is not None,
        "has_video": video is not None,
    }
    if video:
        info["width"] = int(video.get("width") or 0)
        info["height"] = int(video.get("height") or 0)
        rate = video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1"
        try:
            num, den = rate.split("/")
            info["fps"] = round(float(num) / float(den), 3) if float(den) else None
        except ValueError:
            info["fps"] = None
        # Las imágenes fijas aparecen como vídeo con 1 fotograma.
        info["is_image"] = video.get("codec_name") in {"png", "mjpeg", "webp", "bmp", "tiff"} and (
            info["duration"] is None or info["duration"] < 0.1 or str(fmt.get("format_name", "")).endswith("_pipe")
        )
    return info


def thumbnail(src: str | Path, dest: str | Path, at: float = 0.5, width: int = 240) -> None:
    run(
        [
            binary(),
            "-hide_banner",
            "-y",
            "-ss",
            f"{max(0.0, at):.3f}",
            "-i",
            str(src),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            str(dest),
        ]
    )


def waveform(src: str | Path, dest: str | Path, width: int = 800) -> None:
    run(
        [
            binary(),
            "-hide_banner",
            "-y",
            "-i",
            str(src),
            "-filter_complex",
            f"aformat=channel_layouts=mono,showwavespic=s={width}x80:colors=#ffffff",
            "-frames:v",
            "1",
            str(dest),
        ]
    )


@functools.lru_cache(maxsize=1)
def capabilities() -> dict[str, Any]:
    caps: dict[str, Any] = {"ffmpeg": None, "libass": False, "xfade": False, "encoders": []}
    try:
        exe = binary()
    except FFmpegError as exc:
        caps["error"] = str(exc)
        return caps
    caps["ffmpeg"] = exe
    try:
        filters = run([exe, "-hide_banner", "-filters"]).stdout
        caps["libass"] = bool(re.search(r"\ssubtitles\s", filters))
        caps["xfade"] = bool(re.search(r"\sxfade\s", filters))
        encoders = run([exe, "-hide_banner", "-encoders"]).stdout
        wanted = ["libx264", "libx265", "h264_nvenc", "hevc_nvenc", "av1_nvenc", "libsvtav1"]
        caps["encoders"] = [e for e in wanted if re.search(rf"\s{e}\s", encoders)]
    except FFmpegError as exc:
        caps["error"] = str(exc)
    caps["nvenc"] = _nvenc_works(exe) if "h264_nvenc" in caps["encoders"] else False
    return caps


def _nvenc_works(exe: str) -> bool:
    """Comprueba que NVENC funciona de verdad (el encoder puede estar compilado sin GPU)."""
    try:
        run(
            [
                exe,
                "-hide_banner",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=256x256:d=0.1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "-",
            ]
        )
        return True
    except FFmpegError:
        return False


def escape_filter_path(path: str | Path) -> str:
    """Escapa una ruta para usarla dentro de un filtro (p.ej. `subtitles`)."""
    p = str(Path(path).resolve()).replace("\\", "/")
    p = p.replace(":", r"\:").replace("'", r"\'")
    return f"'{p}'"
