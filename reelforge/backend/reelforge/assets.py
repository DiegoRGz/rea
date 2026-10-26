"""Recursos generados localmente para la edición viral: efectos de sonido
sintetizados con FFmpeg (sin descargas ni licencias) y emojis a color en PNG."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from . import config, ffmpeg
from .project import get_media, register_media

# nombre -> (descripción, fuente lavfi, duración)
SFX: dict[str, tuple[str, str, float]] = {
    "whoosh": ("Whoosh (transición)",
               "anoisesrc=d=0.6:c=pink:a=0.9:r=48000,highpass=f=350,lowpass=f=7000,"
               "afade=t=in:d=0.28:curve=exp,afade=t=out:st=0.28:d=0.32,volume=0.9", 0.6),
    "pop": ("Pop (palabra clave)",
            "aevalsrc='0.9*sin(2*PI*(950-750*t)*t)*exp(-t*26)':d=0.2:s=48000", 0.2),
    "boom": ("Boom (gancho)",
             "aevalsrc='0.95*sin(2*PI*(75-35*t)*t)*exp(-t*3.5)+0.35*sin(2*PI*150*t)*exp(-t*9)':d=1.3:s=48000,"
             "lowpass=f=900", 1.3),
    "ding": ("Ding (dato)",
             "aevalsrc='0.55*sin(2*PI*1760*t)*exp(-t*4.5)+0.25*sin(2*PI*2640*t)*exp(-t*6)':d=1.0:s=48000", 1.0),
    "riser": ("Riser (tensión)",
              "aevalsrc='0.35*sin(2*PI*(180+700*t*t)*t)*(t/1.6)':d=1.6:s=48000,afade=t=out:st=1.45:d=0.15", 1.6),
    "click": ("Click (corte)",
              "aevalsrc='0.8*sin(2*PI*2400*t)*exp(-t*90)':d=0.06:s=48000", 0.06),
}

_lock = threading.Lock()


def _sfx_index() -> Path:
    return config.DATA_DIR / "sfx" / "index.json"


def sfx_media(name: str) -> str:
    """Devuelve el id de biblioteca del efecto `name`, generándolo la primera vez."""
    if name not in SFX:
        raise ValueError(f"Efecto desconocido: {name}")
    with _lock:
        idx_file = _sfx_index()
        idx_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            index = json.loads(idx_file.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            index = {}
        if index.get(name) and get_media(index[name]):
            return index[name]
        label, src, dur = SFX[name]
        out = idx_file.parent / f"{name}.wav"
        ffmpeg.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i", src, "-t", f"{dur}",
                    "-ac", "2", "-ar", "48000", str(out)])
        item = register_media(out, source="sfx", name=f"SFX · {label}", meta={"sfx": name})
        index[name] = item.id
        idx_file.write_text(json.dumps(index), "utf-8")
        return item.id


# ------------------------------------------------------------------ emojis

EMOJI_FONTS = ["NotoColorEmoji.ttf", "seguiemj.ttf", "AppleColorEmoji.ttc"]


def _emoji_font():
    from PIL import ImageFont

    for name in EMOJI_FONTS:
        for cand in (config.FONTS_DIR / name, name):
            try:
                return ImageFont.truetype(str(cand), 109)
            except OSError:
                continue
    return None


def emoji_png(emoji: str, size: int = 160) -> Path | None:
    """PNG transparente del emoji (None si no hay fuente de emojis a color)."""
    key = "-".join(f"{ord(c):x}" for c in emoji if ord(c) not in (0xFE0F,))
    out = config.CACHE_DIR / "emoji" / f"{key}-{size}.png"
    if out.is_file():
        return out
    font = _emoji_font()
    if font is None:
        return None
    from PIL import Image, ImageDraw

    canvas = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((80, 80), emoji, font=font, embedded_color=True, anchor="mm")
    box = canvas.getbbox()
    if not box:
        return None
    img = canvas.crop(box)
    img.thumbnail((size, size), Image.LANCZOS)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out
