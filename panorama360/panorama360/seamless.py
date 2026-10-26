"""Continuidad horizontal (360°) para redes convolucionales y procesamiento por mosaicos.

Una panorámica equirectangular da la vuelta completa: la columna 0 es vecina de la
última. Aquí viven las dos piezas que lo garantizan:

* ``set_seamless``: hace que cada ``Conv2d`` rellene en horizontal con píxeles del
  lado opuesto (relleno circular) y en vertical con ceros, de modo que el modelo
  "ve" la imagen como un cilindro y no deja costura.
* ``tiled_apply``: aplica una función por mosaicos solapados, tomando las columnas
  con índice módulo ancho para que los mosaicos del borde reciban contexto del
  lado opuesto, y mezcla los solapes con pesos suaves para no dejar bordes.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import torch
import torch.nn.functional as F
from torch import nn

_MARK = "_pano360_seamless"


def _circular_conv_forward(conv: nn.Conv2d):
    pad_h, pad_w = conv.padding  # type: ignore[misc]

    def forward(x: torch.Tensor, weight: torch.Tensor, bias: torch.Tensor | None) -> torch.Tensor:
        if pad_w:
            x = F.pad(x, (pad_w, pad_w, 0, 0), mode="circular")
        if pad_h:
            x = F.pad(x, (0, 0, pad_h, pad_h), mode="constant", value=0.0)
        return F.conv2d(x, weight, bias, conv.stride, 0, conv.dilation, conv.groups)

    return forward


def set_seamless(module: nn.Module | None, enabled: bool) -> None:
    """Activa o desactiva el relleno circular horizontal en todas las Conv2d."""
    if module is None:
        return
    for layer in module.modules():
        if not isinstance(layer, nn.Conv2d) or isinstance(layer.padding, str):
            continue
        if layer.padding_mode != "zeros" or layer.padding == (0, 0):
            continue
        active = getattr(layer, _MARK, False)
        if enabled and not active:
            layer._conv_forward = _circular_conv_forward(layer)  # type: ignore[method-assign]
            setattr(layer, _MARK, True)
        elif not enabled and active:
            del layer._conv_forward
            setattr(layer, _MARK, False)


@contextmanager
def seamless(modules: list[nn.Module | None], enabled: bool) -> Iterator[None]:
    for module in modules:
        set_seamless(module, enabled)
    try:
        yield
    finally:
        for module in modules:
            set_seamless(module, not enabled)


def _align(value: float, align: int) -> int:
    return max(align, int(round(value / align)) * align)


def tile_starts(length: int, tile: int, overlap: int, align: int, wrap: bool) -> tuple[list[int], int]:
    """Devuelve (inicios, tamaño de mosaico) para cubrir ``length``.

    Con ``wrap`` siempre hay al menos dos mosaicos, así ningún mosaico tiene su
    propio borde izquierdo pegado al derecho y todos reciben contexto real.
    """
    overlap = min(overlap, tile // 2)
    if not wrap:
        if length <= tile:
            return [0], length
        count = math.ceil((length - overlap) / (tile - overlap))
        starts = [int(round(i * (length - tile) / (count - 1) / align)) * align for i in range(count)]
        starts[-1] = length - tile
        return starts, tile
    tile = min(tile, _align(length * 0.75, align))
    overlap = min(overlap, tile // 2)
    count = max(2, math.ceil(length / max(align, tile - overlap)))
    starts = [int(round(i * length / count / align)) * align for i in range(count)]
    return starts, tile


def _ramp(size: int, ramp: int, taper_start: bool, taper_end: bool, device: torch.device) -> torch.Tensor:
    """Peso 1D de un mosaico: 0 junto a los bordes interiores (contaminados por el relleno
    de la red), subida suave en el solape y 1 en el centro. Los bordes reales de la imagen
    sin continuidad no se atenúan porque ningún otro mosaico los cubre."""
    position = torch.arange(size, device=device, dtype=torch.float32) + 0.5
    margin = ramp / 4
    weights = torch.ones(size, device=device)
    for enabled, distance in ((taper_start, position), (taper_end, size - position)):
        if enabled:
            t = ((distance - margin) / max(ramp - margin, 1.0)).clamp(0.0, 1.0)
            weights = weights * (t * t * (3 - 2 * t))
    return weights.clamp_min(1e-6)


def tiled_apply(
    x: torch.Tensor,
    fn: Callable[[torch.Tensor], torch.Tensor],
    *,
    scale: float,
    tile: int,
    overlap: int,
    align: int = 1,
    wrap_x: bool = True,
    out_device: torch.device | str = "cpu",
    on_tile: Callable[[int, int], None] | None = None,
) -> torch.Tensor:
    """Aplica ``fn`` por mosaicos solapados, con continuidad horizontal opcional.

    ``scale`` es la relación entre el tamaño de salida y el de entrada (8 para
    decodificar latentes, 1/8 para codificar, 4 para un reescalador x4).
    """
    batch, _, height, width = x.shape
    y_starts, tile_h = tile_starts(height, tile, overlap, align, wrap=False)
    x_starts, tile_w = tile_starts(width, tile, overlap, align, wrap=wrap_x)
    out_h, out_w = round(height * scale), round(width * scale)
    ramp = max(1, round(min(overlap, tile_h // 2, tile_w // 2) * scale))
    out: torch.Tensor | None = None
    weight_sum = torch.zeros((1, 1, out_h, out_w), dtype=torch.float32, device=out_device)
    total = len(y_starts) * len(x_starts)
    done = 0
    for y0 in y_starts:
        for x0 in x_starts:
            columns = torch.arange(x0, x0 + tile_w, device=x.device) % width
            patch = x[:, :, y0 : y0 + tile_h].index_select(3, columns)
            result = fn(patch).to(device=out_device, dtype=torch.float32)
            if out is None:
                out = torch.zeros((batch, result.shape[1], out_h, out_w), dtype=torch.float32, device=out_device)
            res_h, res_w = result.shape[-2:]
            device = torch.device(out_device)
            wy = _ramp(res_h, ramp, y0 != y_starts[0], y0 != y_starts[-1], device)
            wx = _ramp(res_w, ramp, wrap_x or x0 != x_starts[0], wrap_x or x0 != x_starts[-1], device)
            weights = wy[:, None] * wx[None, :]
            oy0 = round(y0 * scale)
            out_columns = torch.arange(round(x0 * scale), round(x0 * scale) + res_w, device=out_device) % out_w
            out[:, :, oy0 : oy0 + res_h].index_add_(3, out_columns, result * weights)
            weight_sum[:, :, oy0 : oy0 + res_h].index_add_(3, out_columns, weights[None, None].expand(1, 1, -1, -1))
            done += 1
            if on_tile is not None:
                on_tile(done, total)
    assert out is not None
    return out / weight_sum
