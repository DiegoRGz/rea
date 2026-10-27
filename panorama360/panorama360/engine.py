"""Motor de generación: SDXL + LoRA 360 + continuidad horizontal + pasada de detalle por mosaicos.

El bucle de difusión es propio (en vez de llamar al ``pipeline`` de diffusers) para
que texto→panorámica, variación, extensión de foto y la pasada de detalle compartan
exactamente el mismo código, con continuidad 360° en todos ellos.
"""

from __future__ import annotations

import gc
import inspect
import logging
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass

import numpy as np
import torch
from PIL import Image

from .hardware import Hardware, Profile
from .models import Catalog, ModelEntry
from .postprocess import clean_poles, fit_equirect
from .projection import photo_to_equirect
from .seamless import seamless, set_seamless, tiled_apply
from .upscale import Upscaler

log = logging.getLogger(__name__)

FP16_FIX_VAE = "madebyollin/sdxl-vae-fp16-fix"
QUALITY_TAGS = "high quality, highly detailed, sharp focus, natural lighting"
NEGATIVE_BASE = (
    "blurry, lowres, jpeg artifacts, watermark, text, signature, logo, frame, border, vignette, "
    "visible seam, split screen, collage, tiled, duplicate, distorted, deformed, warped horizon, "
    "fisheye circle, black bars, oversaturated, cartoon, ugly"
)


class Cancelled(Exception):
    """El usuario canceló el trabajo en curso."""


@dataclass
class Request:
    model_key: str
    prompt: str
    negative: str = ""
    seed: int = 0
    steps: int | None = None
    cfg: float | None = None
    final_width: int = 4096
    refine: bool = True
    refine_strength: float = 0.3
    reference: str | None = None  # ruta de imagen
    reference_mode: str = "inspiracion"  # "inspiracion" | "variacion" | "extender"
    reference_similarity: float = 0.6  # 0 = libre, 1 = muy parecido
    photo_fov: float = 90.0
    clean_poles: bool = True
    lora_weight: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


Progress = Callable[[float, str], None]


def _make_scheduler(name: str, config):
    from diffusers import (
        DPMSolverMultistepScheduler,
        DPMSolverSDEScheduler,
        EulerAncestralDiscreteScheduler,
        EulerDiscreteScheduler,
    )

    if name == "dpmpp_sde_karras":
        try:
            import torchsde  # noqa: F401

            return DPMSolverSDEScheduler.from_config(config, use_karras_sigmas=True)
        except ImportError:
            log.warning("torchsde no está instalado; se usa DPM++ 2M Karras")
    if name == "euler_a":
        return EulerAncestralDiscreteScheduler.from_config(config)
    if name == "euler":
        return EulerDiscreteScheduler.from_config(config)
    return DPMSolverMultistepScheduler.from_config(config, use_karras_sigmas=True, algorithm_type="dpmsolver++")


class Engine:
    def __init__(self, catalog: Catalog, hardware: Hardware, profile: Profile):
        self.catalog = catalog
        self.hardware = hardware
        self.profile = profile
        self.pipe = None
        self.model_key: str | None = None
        self.lora_loaded = False
        self.ip_loaded = False
        self.warnings: list[str] = []
        self.upscaler = Upscaler(catalog.upscaler, hardware.device, profile.upscale_tile)

    # ------------------------------------------------------------------ carga

    @property
    def dtype(self) -> torch.dtype:
        if self.hardware.device == "cpu" or self.profile.dtype == "float32":
            return torch.float32
        return torch.float16

    def set_profile(self, profile: Profile) -> None:
        if profile.key != self.profile.key:
            self.unload()
            self.profile = profile
            self.upscaler = Upscaler(self.catalog.upscaler, self.hardware.device, profile.upscale_tile)

    def unload(self) -> None:
        if self.pipe is not None:
            try:
                self.pipe.remove_all_hooks()
            except Exception:
                pass
        self.pipe = None
        self.model_key = None
        self.lora_loaded = self.ip_loaded = False
        self.upscaler.unload()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _load(self, entry: ModelEntry, with_ip: bool, status: Progress) -> None:
        from diffusers import AutoencoderKL, StableDiffusionXLPipeline

        self.unload()
        self.warnings = []
        status(0.0, f"Cargando {entry.name}… (la primera vez se descarga, puede tardar)")
        kwargs: dict = {"torch_dtype": self.dtype}
        if self.dtype == torch.float16:
            # El VAE original de SDXL produce imágenes negras en fp16; esta versión corregida no.
            kwargs["vae"] = AutoencoderKL.from_pretrained(FP16_FIX_VAE, torch_dtype=self.dtype)
        if entry.is_local_file:
            pipe = StableDiffusionXLPipeline.from_single_file(entry.source, **kwargs)
        else:
            try:
                pipe = StableDiffusionXLPipeline.from_pretrained(
                    entry.source, variant=entry.variant, use_safetensors=True, **kwargs
                )
            except (OSError, ValueError, EnvironmentError):
                pipe = StableDiffusionXLPipeline.from_pretrained(entry.source, **kwargs)
        pipe.set_progress_bar_config(disable=True)
        self.pipe = pipe
        self.model_key = entry.key

        if entry.use_360_lora:
            lora = self.catalog.lora_360
            status(0.0, "Cargando LoRA 360°…")
            try:
                pipe.load_lora_weights(lora["source"], weight_name=lora.get("weight_name"), adapter_name="pano360")
                self.lora_loaded = True
            except Exception as exc:
                self.warnings.append(f"No se pudo cargar el LoRA 360 ({exc}); se genera sin él.")
                log.warning(self.warnings[-1])
        if with_ip:
            self._load_ip_adapter(status)
        self._place()

    def _load_ip_adapter(self, status: Progress) -> None:
        cfg = self.catalog.ip_adapter
        status(0.0, "Cargando adaptador de referencia (IP-Adapter)…")
        self.pipe.load_ip_adapter(
            cfg["source"], subfolder=cfg.get("subfolder"), weight_name=cfg["weight_name"],
            image_encoder_folder=cfg.get("image_encoder_folder"),
        )
        self.ip_loaded = True

    def _place(self) -> None:
        pipe, offload = self.pipe, self.profile.offload
        if self.hardware.device == "cuda" and offload == "sequential":
            pipe.enable_sequential_cpu_offload()
        elif self.hardware.device == "cuda" and offload == "model":
            pipe.enable_model_cpu_offload()
        else:
            pipe.to(self.hardware.device)
            if self.hardware.device == "mps":
                pipe.enable_attention_slicing()

    def ensure(self, entry: ModelEntry, with_ip: bool, status: Progress) -> None:
        if self.pipe is None or self.model_key != entry.key:
            self._load(entry, with_ip, status)
            return
        if with_ip == self.ip_loaded:
            return
        if self.profile.offload == "sequential":
            self._load(entry, with_ip, status)
            return
        self.pipe.remove_all_hooks()
        if with_ip:
            self._load_ip_adapter(status)
        else:
            self.pipe.unload_ip_adapter()
            self.ip_loaded = False
        self._place()

    # -------------------------------------------------------------- utilidades

    @property
    def device(self) -> torch.device:
        return self.pipe._execution_device

    def _vae_scale(self) -> float:
        return float(self.pipe.vae.config.scaling_factor)

    def _encode(self, image: Image.Image) -> torch.Tensor:
        vae = self.pipe.vae
        pixels = torch.from_numpy(np.asarray(image.convert("RGB"), dtype=np.float32) / 127.5 - 1.0)
        pixels = pixels.permute(2, 0, 1)[None].to(self.device)

        def encode(patch: torch.Tensor) -> torch.Tensor:
            with torch.no_grad():
                return vae.encode(patch.to(vae.dtype)).latent_dist.mean.float()

        if self.profile.full_decode and image.width <= 2048:
            with seamless([vae], True):
                latents = encode(pixels)
        else:
            set_seamless(vae, False)
            tile = self.profile.decode_tile
            latents = tiled_apply(
                pixels, encode, scale=1 / 8, tile=tile, overlap=tile // 4, align=8, out_device=self.device
            )
        return latents.to(self.device) * self._vae_scale()

    def _decode(self, latents: torch.Tensor, status: Callable[[str], None]) -> Image.Image:
        vae = self.pipe.vae
        latents = latents / self._vae_scale()

        def decode(patch: torch.Tensor) -> torch.Tensor:
            with torch.no_grad():
                return vae.decode(patch.to(vae.dtype)).sample.float()

        if self.profile.full_decode and latents.shape[-1] * 8 <= 2048:
            with seamless([vae], True):
                pixels = decode(latents).cpu()
        else:
            set_seamless(vae, False)
            tile = self.profile.decode_tile // 8
            pixels = tiled_apply(
                latents, decode, scale=8, tile=tile, overlap=max(8, tile // 4),
                on_tile=lambda done, total: status(f"Decodificando ({done}/{total})…"),
            )
        array = ((pixels[0].clamp(-1, 1) + 1) * 127.5 + 0.5).permute(1, 2, 0).numpy().astype(np.uint8)
        return Image.fromarray(array)

    def _conditioning(self, prompt: str, negative: str, cfg: float, ip_image: Image.Image | None):
        pipe = self.pipe
        with torch.no_grad():
            embeds, neg_embeds, pooled, neg_pooled = pipe.encode_prompt(
                prompt=prompt, device=self.device, num_images_per_prompt=1,
                do_classifier_free_guidance=True, negative_prompt=negative,
            )
            ip_embeds = None
            if ip_image is not None:
                ip_embeds = pipe.prepare_ip_adapter_image_embeds(
                    ip_image, None, self.device, 1, True
                )
        return {
            "embeds": torch.cat([neg_embeds, embeds]),
            "pooled": torch.cat([neg_pooled, pooled]),
            "ip": ip_embeds,
            "cfg": cfg,
        }

    def _predict(self, latents: torch.Tensor, t, cond: dict) -> torch.Tensor:
        unet = self.pipe.unet
        height, width = latents.shape[-2] * 8, latents.shape[-1] * 8
        time_ids = torch.tensor([[height, width, 0, 0, height, width]], device=self.device, dtype=cond["embeds"].dtype)
        added = {"text_embeds": cond["pooled"], "time_ids": time_ids.repeat(2, 1)}
        if cond["ip"] is not None:
            added["image_embeds"] = cond["ip"]
        model_input = torch.cat([latents, latents]).to(unet.dtype)
        with torch.no_grad():
            noise = unet(model_input, t, encoder_hidden_states=cond["embeds"], added_cond_kwargs=added).sample.float()
        uncond, text = noise.chunk(2)
        return uncond + cond["cfg"] * (text - uncond)

    def _denoise(
        self,
        *,
        entry: ModelEntry,
        shape: tuple[int, int],
        steps: int,
        cond: dict,
        generator: torch.Generator,
        strength: float = 1.0,
        init_latents: torch.Tensor | None = None,
        mask: torch.Tensor | None = None,
        tiled: bool = False,
        progress: Callable[[float], None],
        should_cancel: Callable[[], bool],
    ) -> torch.Tensor:
        scheduler = _make_scheduler(entry.scheduler, self.pipe.scheduler.config)
        scheduler.set_timesteps(steps, device=self.device)
        timesteps = scheduler.timesteps
        order = getattr(scheduler, "order", 1)
        if strength < 1.0:
            start = max(steps - min(int(round(steps * strength)), steps), 0)
            timesteps = timesteps[start * order :]
            if hasattr(scheduler, "set_begin_index"):
                scheduler.set_begin_index(start * order)
        height, width = shape
        noise = torch.randn((1, 4, height, width), generator=generator, dtype=torch.float32).to(self.device)
        if init_latents is not None and strength < 1.0:
            latents = scheduler.add_noise(init_latents, noise, timesteps[:1])
        else:
            latents = noise * scheduler.init_noise_sigma
        step_kwargs = {}
        if "generator" in inspect.signature(scheduler.step).parameters:
            step_kwargs["generator"] = generator

        unet = self.pipe.unet
        total = len(timesteps)
        tile = self.profile.refine_tile // 8
        for index, t in enumerate(timesteps):
            if should_cancel():
                raise Cancelled()
            model_input = scheduler.scale_model_input(latents, t)
            if tiled:
                set_seamless(unet, False)
                noise_pred = tiled_apply(
                    model_input, lambda patch, t=t: self._predict(patch, t, cond), scale=1, tile=tile,
                    overlap=tile // 4, align=1, wrap_x=True, out_device=self.device,
                )
            else:
                with seamless([unet], True):
                    noise_pred = self._predict(model_input, t, cond)
            latents = scheduler.step(noise_pred, t, latents, **step_kwargs).prev_sample
            if mask is not None and init_latents is not None:
                if index + 1 < total:
                    known = scheduler.add_noise(init_latents, noise, timesteps[index + 1 : index + 2])
                else:
                    known = init_latents
                latents = known * (1 - mask) + latents * mask
            progress((index + 1) / total)
        return latents

    # --------------------------------------------------------------- generar

    def generate(
        self, request: Request, progress: Progress, should_cancel: Callable[[], bool] = lambda: False
    ) -> tuple[Image.Image, dict]:
        started = time.time()
        entry = self.catalog.get(request.model_key)
        reference = Image.open(request.reference).convert("RGB") if request.reference else None
        mode = request.reference_mode if reference is not None else None
        similarity = min(max(request.reference_similarity, 0.0), 1.0)
        use_ip = mode in ("inspiracion", "extender")
        self.ensure(entry, use_ip, progress)
        pipe = self.pipe

        refine = request.refine
        base_w = self.profile.base_width
        base_h = base_w // 2
        work_w = min(request.final_width, base_w * 2)
        refine = refine and work_w > base_w
        base_share = 0.55 if refine else 0.85

        lora = self.catalog.lora_360
        if self.lora_loaded:
            weight = lora["weight"] if request.lora_weight is None else request.lora_weight
            pipe.set_adapters(["pano360"], adapter_weights=[weight])
        trigger = lora["trigger"] if self.lora_loaded else "equirectangular 360 degree panorama"
        prompt = f"{trigger}, {request.prompt.strip()}, {QUALITY_TAGS}"
        negative = f"{request.negative.strip()}, {NEGATIVE_BASE}" if request.negative.strip() else NEGATIVE_BASE
        steps = request.steps or entry.steps
        cfg = request.cfg if request.cfg is not None else entry.cfg

        if use_ip:
            pipe.set_ip_adapter_scale(0.25 + 0.65 * similarity if mode == "inspiracion" else 0.5)
        cond = self._conditioning(prompt, negative, cfg, reference if use_ip else None)
        generator = torch.Generator("cpu").manual_seed(int(request.seed))

        init_latents = mask_latents = None
        strength = 1.0
        if mode == "variacion":
            progress(0.02, "Preparando la referencia…")
            init_latents = self._encode(fit_equirect(reference, base_w))
            strength = 1.0 - 0.75 * similarity
        elif mode == "extender":
            progress(0.02, "Proyectando la foto en la esfera 360°…")
            partial, mask = photo_to_equirect(reference, base_w, request.photo_fov)
            init_latents = self._encode(partial)
            mask_array = np.asarray(mask.resize((base_w // 8, base_h // 8), Image.Resampling.BILINEAR), dtype=np.float32)
            mask_latents = torch.from_numpy(mask_array / 255.0)[None, None].to(self.device)

        latents = self._denoise(
            entry=entry, shape=(base_h // 8, base_w // 8), steps=steps, cond=cond, generator=generator,
            strength=strength, init_latents=init_latents, mask=mask_latents,
            progress=lambda f: progress(0.03 + base_share * f, f"Generando panorámica base ({int(f * 100)}%)"),
            should_cancel=should_cancel,
        )
        progress(base_share + 0.04, "Decodificando…")
        image = self._decode(latents, lambda msg: progress(base_share + 0.04, msg))
        del latents

        if refine:
            self._free_cache()
            image = self.upscaler.upscale(
                image, work_w, status=lambda msg: progress(base_share + 0.06, msg), should_cancel=should_cancel
            )
            progress(base_share + 0.08, "Añadiendo detalle…")
            work_latents = self._encode(image)
            refine_steps = max(steps, int(round(10 / max(request.refine_strength, 0.05))))
            refine_steps = min(refine_steps, steps * 2)
            latents = self._denoise(
                entry=entry, shape=tuple(work_latents.shape[-2:]), steps=refine_steps, cond=cond,
                generator=generator, strength=request.refine_strength, init_latents=work_latents, tiled=True,
                progress=lambda f: progress(base_share + 0.08 + 0.27 * f, f"Añadiendo detalle ({int(f * 100)}%)"),
                should_cancel=should_cancel,
            )
            image = self._decode(latents, lambda msg: progress(0.92, msg))
            del latents, work_latents

        self._free_cache()
        if image.width < request.final_width:
            image = self.upscaler.upscale(
                image, request.final_width, status=lambda msg: progress(0.95, msg), should_cancel=should_cancel
            )
        elif image.width > request.final_width:
            image = image.resize((request.final_width, request.final_width // 2), Image.Resampling.LANCZOS)
        if request.clean_poles:
            progress(0.98, "Limpiando cenit y nadir…")
            image = clean_poles(image)

        info = {
            "model": entry.name,
            "model_source": entry.source,
            "prompt": request.prompt,
            "full_prompt": prompt,
            "negative": negative,
            "seed": request.seed,
            "steps": steps,
            "cfg": cfg,
            "scheduler": entry.scheduler,
            "lora_360": self.lora_loaded,
            "profile": self.profile.key,
            "size": [image.width, image.height],
            "seconds": round(time.time() - started, 1),
            "warnings": list(self.warnings),
            "request": request.as_dict(),
        }
        return image, info

    def _free_cache(self) -> None:
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
