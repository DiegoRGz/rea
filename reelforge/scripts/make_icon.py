"""Genera build/icon.png (512×512) para el instalador, sin binarios en el repositorio."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 512
OUT = Path(__file__).resolve().parents[1] / "build" / "icon.png"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def main() -> None:
    stops = [(0.0, (124, 92, 255)), (0.55, (255, 77, 157)), (1.0, (255, 138, 61))]
    grad = Image.new("RGB", (SIZE, SIZE))
    px = grad.load()
    for y in range(SIZE):
        for x in range(SIZE):
            t = (x + y) / (2 * (SIZE - 1))
            for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
                if t <= t1:
                    px[x, y] = lerp(c0, c1, (t - t0) / (t1 - t0))
                    break
    mask = Image.new("L", (SIZE, SIZE), 0)
    pad = 28
    ImageDraw.Draw(mask).rounded_rectangle((pad, pad, SIZE - pad, SIZE - pad), radius=128, fill=255)
    icon = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    icon.paste(grad, (0, 0), mask)
    shadow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    tri = [(206, 160), (206, 352), (366, 256)]
    ImageDraw.Draw(shadow).polygon([(x + 6, y + 10) for x, y in tri], fill=(60, 0, 40, 110))
    icon = Image.alpha_composite(icon, shadow.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(icon)
    d.polygon(tri, fill=(255, 255, 255, 255))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    icon.save(OUT)
    print(f"Icono generado en {OUT}")


if __name__ == "__main__":
    main()
