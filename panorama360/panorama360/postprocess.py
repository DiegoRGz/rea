"""Acabado de la panorámica: limpieza de polos y exportación compatible con Facebook."""

from __future__ import annotations

import io
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image

XMP_HEADER = b"http://ns.adobe.com/xap/1.0/\x00"


def clean_poles(image: Image.Image, start_degrees: float = 72.0, strength: float = 1.0) -> Image.Image:
    """Suaviza cenit y nadir para que el visor 360° no muestre un "remolino".

    En la proyección equirectangular la fila superior entera es un único punto
    (el cenit). Los modelos de difusión dibujan detalle ahí que el visor estira
    hasta formar un pellizco. Desde ``start_degrees`` de latitud hacia el polo,
    cada fila se mezcla con un desenfoque horizontal circular cuyo radio crece
    hasta abarcar toda la fila en el polo.
    """
    if strength <= 0:
        return image
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    height, width, _ = pixels.shape
    result = pixels.copy()
    start = math.radians(start_degrees)
    span = math.pi / 2 - start
    for row in range(height):
        latitude = abs((0.5 - (row + 0.5) / height) * math.pi)
        if latitude <= start:
            continue
        t = min(1.0, (latitude - start) / span)
        radius = max(1, int(round((width / 2 - 1) * t**2)))
        line = pixels[row]
        padded = np.concatenate([line[-radius:], line, line[: radius + 1]], axis=0)
        summed = np.cumsum(padded, axis=0, dtype=np.float64)
        blurred = (summed[2 * radius + 1 : 2 * radius + 1 + width] - summed[:width]) / (2 * radius + 1)
        mix = strength * t * t * (3 - 2 * t)
        result[row] = line * (1 - mix) + blurred.astype(np.float32) * mix
    return Image.fromarray(np.clip(result + 0.5, 0, 255).astype(np.uint8))


def gpano_xmp(width: int, height: int) -> bytes:
    """Metadatos GPano que Facebook (y Google Photos) usan para activar el visor 360°."""
    attributes = {
        "GPano:ProjectionType": "equirectangular",
        "GPano:UsePanoramaViewer": "True",
        "GPano:FullPanoWidthPixels": width,
        "GPano:FullPanoHeightPixels": height,
        "GPano:CroppedAreaImageWidthPixels": width,
        "GPano:CroppedAreaImageHeightPixels": height,
        "GPano:CroppedAreaLeftPixels": 0,
        "GPano:CroppedAreaTopPixels": 0,
    }
    rendered = "\n   ".join(f'{key}="{value}"' for key, value in attributes.items())
    packet = (
        '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '  <rdf:Description rdf:about="" xmlns:GPano="http://ns.google.com/photos/1.0/panorama/"\n'
        f"   {rendered}/>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        '<?xpacket end="w"?>'
    )
    return packet.encode("utf-8")


def insert_xmp(jpeg: bytes, xmp: bytes) -> bytes:
    """Inserta un segmento APP1/XMP tras SOI y los segmentos APP0 (JFIF)."""
    if jpeg[:2] != b"\xff\xd8":
        raise ValueError("no es un JPEG")
    payload = XMP_HEADER + xmp
    if len(payload) + 2 > 0xFFFF:
        raise ValueError("XMP demasiado grande para un segmento APP1")
    segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    position = 2
    while jpeg[position : position + 2] == b"\xff\xe0":
        position += 2 + int.from_bytes(jpeg[position + 2 : position + 4], "big")
    return jpeg[:position] + segment + jpeg[position:]


def save_panorama(image: Image.Image, path: Path, quality: int = 93, metadata: dict | None = None) -> Path:
    """Guarda un JPEG equirectangular con metadatos 360° y, opcionalmente, un JSON al lado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, subsampling=0, optimize=True)
    path.write_bytes(insert_xmp(buffer.getvalue(), gpano_xmp(image.width, image.height)))
    if metadata is not None:
        path.with_suffix(".json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def fit_equirect(image: Image.Image, width: int) -> Image.Image:
    """Ajusta una imagen a proporción 2:1 (estirando) al ancho indicado."""
    width -= width % 16
    return image.convert("RGB").resize((width, width // 2), Image.Resampling.LANCZOS)
