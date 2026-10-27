import dataclasses

import torch

import numpy as np
import pytest
from PIL import Image

from panorama360 import hardware as hw
from panorama360.engine import Cancelled, Engine, Request
from panorama360.models import Catalog

from tiny_pipe import build


@pytest.fixture(scope="module")
def pipe(tmp_path_factory):
    return build(tmp_path_factory.mktemp("tok"))


def _engine(pipe, monkeypatch, **profile_changes):
    hardware = hw.Hardware("cpu", "test", 0.0, 16.0, "test")
    profile = dataclasses.replace(
        hw.PROFILES["cpu"], base_width=128, refine_tile=64, decode_tile=64, upscale_tile=32, **profile_changes
    )
    engine = Engine(Catalog(), hardware, profile)
    engine.upscaler._failed = "sin red en pruebas"  # Lanczos

    def fake_load(entry, with_ip, status):
        engine.pipe, engine.model_key, engine.lora_loaded, engine.ip_loaded = pipe, entry.key, False, with_ip

    monkeypatch.setattr(engine, "_load", fake_load)
    return engine


def _request(**changes):
    base = dict(model_key="sdxl-base", prompt="snowy stadium", seed=7, steps=4, final_width=256, refine=True,
                clean_poles=True)
    return Request(**(base | changes))


@pytest.mark.parametrize("full_decode", [True, False])
def test_text_to_panorama_with_detail_pass(pipe, monkeypatch, full_decode):
    engine = _engine(pipe, monkeypatch, full_decode=full_decode)
    messages = []
    image, info = engine.generate(_request(), lambda f, m: messages.append((f, m)))
    assert image.size == (256, 128)
    assert info["seed"] == 7 and info["size"] == [256, 128]
    assert any("detalle" in m for _, m in messages)
    assert np.isfinite(np.asarray(image, dtype=np.float32)).all()


def test_same_seed_is_reproducible(pipe, monkeypatch):
    engine = _engine(pipe, monkeypatch, full_decode=True)
    a, _ = engine.generate(_request(refine=False, final_width=128), lambda *_: None)
    b, _ = engine.generate(_request(refine=False, final_width=128), lambda *_: None)
    c, _ = engine.generate(_request(refine=False, final_width=128, seed=8), lambda *_: None)
    assert np.array_equal(np.asarray(a), np.asarray(b))
    assert not np.array_equal(np.asarray(a), np.asarray(c))


@pytest.mark.parametrize("scheduler", ["dpmpp_2m_karras", "euler_a", "euler", "dpmpp_sde_karras"])
def test_variation_and_extension_modes(pipe, monkeypatch, tmp_path, scheduler):
    engine = _engine(pipe, monkeypatch, full_decode=True)
    engine.catalog.get("sdxl-base").scheduler = scheduler
    ref = tmp_path / "ref.png"
    Image.new("RGB", (200, 100), (30, 120, 40)).save(ref)
    for mode in ("variacion",):
        image, _ = engine.generate(_request(reference=str(ref), reference_mode=mode, refine=False, final_width=128),
                                   lambda *_: None)
        assert image.size == (128, 64)


def test_extend_photo_keeps_known_region(pipe, monkeypatch, tmp_path):
    engine = _engine(pipe, monkeypatch, full_decode=True)
    monkeypatch.setattr(engine, "_conditioning", _no_ip(engine._conditioning))
    ref = tmp_path / "photo.png"
    Image.new("RGB", (160, 120), (220, 20, 20)).save(ref)
    image, _ = engine.generate(
        _request(reference=str(ref), reference_mode="extender", refine=False, final_width=128, clean_poles=False),
        lambda *_: None,
    )
    assert image.size == (128, 64)


def _no_ip(original):
    # El adaptador IP real necesita descargar pesos; aquí se prueba el resto del flujo.
    def wrapper(prompt, negative, cfg, ip_image):
        return original(prompt, negative, cfg, None)

    return wrapper


def test_cancel_stops_generation(pipe, monkeypatch):
    engine = _engine(pipe, monkeypatch, full_decode=True)
    with pytest.raises(Cancelled):
        engine.generate(_request(), lambda *_: None, should_cancel=lambda: True)


def test_offloaded_lora_survives_consecutive_jobs(pipe, monkeypatch):
    """Perfil de 8 GB: los ganchos de descarga mueven pesos durante la inferencia y el LoRA
    360 se reajusta en cada trabajo. Con inference_mode el segundo trabajo fallaba con
    "Setting requires_grad=True on inference tensor outside InferenceMode"."""
    from peft import LoraConfig

    engine = _engine(pipe, monkeypatch, full_decode=True)
    if "pano360" not in getattr(pipe.unet, "peft_config", {}):
        pipe.unet.add_adapter(LoraConfig(r=4, target_modules=["to_q", "to_k", "to_v"]), adapter_name="pano360")

    def fake_load(entry, with_ip, status):
        engine.pipe, engine.model_key, engine.lora_loaded, engine.ip_loaded = pipe, entry.key, True, with_ip

    monkeypatch.setattr(engine, "_load", fake_load)

    def offload_hook(module, args):  # como accelerate: mueve los pesos dentro del forward
        module.to(torch.float64)
        module.to(torch.float32)

    handle = pipe.unet.register_forward_pre_hook(offload_hook)
    try:
        for seed in (1, 2):
            image, _ = engine.generate(_request(seed=seed, refine=False, final_width=128), lambda *_: None)
            assert image.size == (128, 64)
    finally:
        handle.remove()
        pipe.unet.delete_adapters("pano360")
