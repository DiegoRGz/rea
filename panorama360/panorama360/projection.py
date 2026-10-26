"""Proyección de una foto normal (perspectiva) dentro de una panorámica equirectangular."""

from __future__ import annotations

import math

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageFilter


def photo_to_equirect(
    photo: Image.Image, width: int, fov_degrees: float = 90.0, feather: int = 24
) -> tuple[Image.Image, Image.Image]:
    """Coloca ``photo`` al frente de una esfera 360° vista con el campo de visión indicado.

    Devuelve (panorámica parcial, máscara) donde la máscara es blanca en lo que hay
    que inventar y negra en lo que viene de la foto, con un borde difuminado.
    """
    height = width // 2
    rgb = torch.from_numpy(np.asarray(photo.convert("RGB"), dtype=np.float32) / 255.0).permute(2, 0, 1)[None]
    photo_w, photo_h = photo.size
    tan_x = math.tan(math.radians(fov_degrees) / 2)
    tan_y = tan_x * photo_h / photo_w

    lon = (torch.arange(width, dtype=torch.float32) + 0.5) / width * 2 * math.pi - math.pi
    lat = math.pi / 2 - (torch.arange(height, dtype=torch.float32) + 0.5) / height * math.pi
    lat, lon = torch.meshgrid(lat, lon, indexing="ij")
    dx = torch.cos(lat) * torch.sin(lon)
    dy = torch.sin(lat)
    dz = torch.cos(lat) * torch.cos(lon)
    front = dz > 1e-6
    safe_z = torch.where(front, dz, torch.ones_like(dz))
    u = dx / safe_z / tan_x  # -1..1 dentro de la foto
    v = -dy / safe_z / tan_y
    inside = front & (u.abs() <= 1) & (v.abs() <= 1)

    grid = torch.stack([u, v], dim=-1)[None]
    sampled = F.grid_sample(rgb, grid, mode="bilinear", padding_mode="border", align_corners=False)[0]
    sampled = sampled * inside[None]
    # Fuera de la foto se rellena con su color medio para que la difusión parta de algo coherente.
    mean = rgb.mean(dim=(2, 3))[0][:, None, None]
    canvas = torch.where(inside[None], sampled, mean.expand_as(sampled))

    pano = Image.fromarray((canvas.permute(1, 2, 0).numpy() * 255 + 0.5).astype(np.uint8))
    known = Image.fromarray((inside.numpy() * 255).astype(np.uint8))
    if feather > 0:
        known = known.filter(ImageFilter.MinFilter(feather // 2 * 2 + 1)).filter(ImageFilter.GaussianBlur(feather / 2))
    mask = Image.eval(known, lambda value: 255 - value)
    return pano, mask
