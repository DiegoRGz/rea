"""Reescalado sin costura con Real-ESRGAN (o Lanczos si no está disponible)."""

from __future__ import annotations

import logging
import urllib.request
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from .paths import WEIGHTS_DIR
from .seamless import tiled_apply

log = logging.getLogger(__name__)


class Upscaler:
    def __init__(self, config: dict, device: str, tile: int):
        self.config = config
        self.device = device
        self.tile = tile
        self._model = None
        self._failed: str | None = None

    @property
    def path(self) -> Path:
        return WEIGHTS_DIR / self.config["file"]

    def _load(self, status) -> bool:
        if self._model is not None:
            return True
        if self._failed:
            return False
        try:
            if not self.path.exists():
                status(f"Descargando {self.config['name']} (una sola vez, ~65 MB)…")
                partial = self.path.with_suffix(".part")
                urllib.request.urlretrieve(self.config["url"], partial)
                partial.replace(self.path)
            from spandrel import ModelLoader

            model = ModelLoader().load_from_file(str(self.path)).eval()
            if self.device == "cuda":
                model = model.half()
            self._model = model.to(self.device)
            return True
        except Exception as exc:  # sin red, archivo dañado, arquitectura no soportada…
            self._failed = str(exc)
            log.warning("Reescalador no disponible, se usará Lanczos: %s", exc)
            return False

    def unload(self) -> None:
        self._model = None

    def upscale(self, image: Image.Image, width: int, status=lambda _msg: None, should_cancel=lambda: False) -> Image.Image:
        """Reescala al ancho indicado (proporción 2:1) conservando la continuidad 360°."""
        height = width // 2
        # Para ampliaciones pequeñas Lanczos basta y evita una imagen intermedia x4 enorme.
        if width < image.width * 1.5 or not self._load(status):
            return image.resize((width, height), Image.Resampling.LANCZOS)
        model = self._model
        scale = int(self.config.get("scale", 4))
        dtype = model.dtype
        pixels = torch.from_numpy(np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0)
        pixels = pixels.permute(2, 0, 1)[None].to(self.device)

        def run(patch: torch.Tensor) -> torch.Tensor:
            if should_cancel():
                from .engine import Cancelled

                raise Cancelled()
            with torch.no_grad():
                return model(patch.to(dtype)).float()

        result = tiled_apply(
            pixels, run, scale=scale, tile=self.tile, overlap=max(16, self.tile // 8),
            wrap_x=True, on_tile=lambda done, total: status(f"Reescalando ({done}/{total})…"),
        )
        array = (result[0].clamp(0, 1).permute(1, 2, 0).numpy() * 255.0 + 0.5).astype(np.uint8)
        upscaled = Image.fromarray(array)
        if upscaled.width != width:
            upscaled = upscaled.resize((width, height), Image.Resampling.LANCZOS)
        return upscaled
