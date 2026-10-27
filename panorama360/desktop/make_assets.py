"""Genera el icono y las imágenes del instalador (se crean al compilar; no se guardan binarios en git).

Uso: python make_assets.py CARPETA_DE_SALIDA
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

SIZE = 1024
TEAL = (16, 185, 129)
INDIGO = (49, 46, 129)
NIGHT = (11, 16, 32)


def _gradient(size: tuple[int, int], start: tuple[int, int, int], end: tuple[int, int, int]) -> Image.Image:
    """Degradado diagonal (arriba-izquierda → abajo-derecha)."""
    width, height = size
    t = (np.linspace(0, 1, width)[None, :] + np.linspace(0, 1, height)[:, None]) / 2
    pixels = np.asarray(start)[None, None] * (1 - t[..., None]) + np.asarray(end)[None, None] * t[..., None]
    return Image.fromarray(pixels.round().astype(np.uint8), "RGB")


def _globe(size: int) -> Image.Image:
    """Globo con meridianos y paralelos + anillo de órbita (el "360")."""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    center, radius = size / 2, size * 0.29
    box = (center - radius, center - radius, center + radius, center + radius)

    ring = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ring_draw = ImageDraw.Draw(ring)
    rx, ry, width = size * 0.43, size * 0.13, int(size * 0.03)
    ring_box = (center - rx, center - ry, center + rx, center + ry)
    ring_draw.arc(ring_box, 180, 360, fill=(255, 255, 255, 150), width=width)  # mitad trasera

    back = ring.rotate(18, resample=Image.Resampling.BICUBIC, center=(center, center))
    layer.alpha_composite(back)

    sphere = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    shade = Image.radial_gradient("L").resize((int(radius * 2.6), int(radius * 2.6)))
    shade = ImageChops.invert(shade)
    fill = Image.composite(Image.new("RGB", shade.size, (125, 245, 220)), Image.new("RGB", shade.size, (30, 64, 175)), shade)
    offset = (int(center - radius * 1.6), int(center - radius * 1.6))
    sphere.paste(fill, offset)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    sphere.putalpha(mask)

    grid = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(grid)
    line = max(2, int(size * 0.012))
    white = (255, 255, 255, 170)
    for factor in (1.0, 0.62, 0.22):
        half = radius * factor
        draw.ellipse((center - half, center - radius, center + half, center + radius), outline=white, width=line)
    for latitude in (-50, -22, 0, 22, 50):
        y = center - radius * math.sin(math.radians(latitude))
        half = radius * math.cos(math.radians(latitude))
        draw.line((center - half, y, center + half, y), fill=white, width=line)
    grid.putalpha(ImageChops.multiply(grid.getchannel("A"), mask))
    sphere.alpha_composite(grid)

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse(box, fill=(120, 255, 230, 140))
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(size * 0.04)))
    layer.alpha_composite(sphere)

    front = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    front_draw = ImageDraw.Draw(front)
    front_draw.arc(ring_box, 0, 180, fill=(255, 255, 255, 255), width=width)
    # Punta de flecha al final del arco delantero (sentido de giro).
    tip_x, tip_y = center - rx, center
    arrow = size * 0.06
    front_draw.polygon(
        [(tip_x - arrow * 0.7, tip_y + arrow * 0.1), (tip_x + arrow * 0.7, tip_y + arrow * 0.1), (tip_x, tip_y - arrow)],
        fill=(255, 255, 255, 255),
    )
    layer.alpha_composite(front.rotate(18, resample=Image.Resampling.BICUBIC, center=(center, center)))
    return layer


def icon(size: int = SIZE) -> Image.Image:
    base = _gradient((size, size), TEAL, INDIGO).convert("RGBA")
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=int(size * 0.22), fill=255)
    base.putalpha(mask)
    base.alpha_composite(_globe(size))
    return base


def wizard_image(width: int, height: int) -> Image.Image:
    image = _gradient((width, height), INDIGO, NIGHT).convert("RGBA")
    globe = _globe(width * 2).resize((int(width * 1.1), int(width * 1.1)), Image.Resampling.LANCZOS)
    image.alpha_composite(globe, (int(-width * 0.05), int(height * 0.3)))
    return image.convert("RGB")


def main(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    art = icon()
    art.resize((512, 512), Image.Resampling.LANCZOS).save(output / "icon.png")
    art.save(output / "icon.ico", sizes=[(s, s) for s in (16, 20, 24, 32, 40, 48, 64, 128, 256)])
    # Inno Setup 6 elige la imagen según el DPI de la pantalla.
    for scale, suffix in ((1, ""), (2, "@2x")):
        wizard_image(164 * scale, 314 * scale).save(output / f"wizard{suffix}.bmp")
        small = icon(256).resize((55 * scale, 55 * scale), Image.Resampling.LANCZOS)
        background = Image.new("RGB", small.size, (255, 255, 255))
        background.paste(small, mask=small.getchannel("A"))
        background.save(output / f"wizard_small{suffix}.bmp")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "build/assets"))
