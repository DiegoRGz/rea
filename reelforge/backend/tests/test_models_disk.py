import json
import os
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from reelforge import catalog, config
from reelforge.ai import hub, image
from reelforge.jobs import Job, JobContext


def _fake_repo(repo: str, mb: int) -> Path:
    d = catalog._repo_dir(repo)
    (d / "snapshots" / "abc").mkdir(parents=True, exist_ok=True)
    (d / "blobs").mkdir(exist_ok=True)
    (d / "blobs" / "w").write_bytes(b"\0" * mb * 1024 * 1024)
    os.chmod(d / "blobs" / "w", 0o444)  # la caché de HF deja archivos de sólo lectura
    (d / "snapshots" / "abc" / "model.safetensors").write_text("x")
    return d


def test_delete_model_frees_disk_but_keeps_shared_repos():
    os.environ["HF_HOME"] = str(config.MODELS_DIR / "huggingface")
    lightning = _fake_repo("stabilityai/stable-diffusion-xl-base-1.0", 2)
    vae = _fake_repo("madebyollin/sdxl-vae-fp16-fix", 1)
    _fake_repo("ByteDance/SDXL-Lightning", 1)
    turbo = _fake_repo("stabilityai/sdxl-turbo", 1)  # sdxl-turbo comparte el VAE
    entry = next(e for e in catalog.entries() if e["id"] == "image:sdxl-lightning")
    assert entry["downloaded"] and entry["disk_gb"] > 0
    res = catalog.delete_model("image:sdxl-lightning")
    assert not lightning.exists() and vae.exists() and turbo.exists()
    assert res["kept_shared"] == ["madebyollin/sdxl-vae-fp16-fix"] and res["freed_gb"] > 0


def test_clear_render_cache():
    seg = config.CACHE_DIR / "segments"
    seg.mkdir(parents=True, exist_ok=True)
    (seg / "x.mkv").write_bytes(b"\0" * 2048)
    assert catalog.cache_usage()["segments"] >= 0
    catalog.clear_cache()
    assert not seg.exists()


def test_settings_migrate_old_sdxl_default():
    config.SETTINGS_FILE.write_text(json.dumps({"image_model": "sdxl-lightning", "language": "es"}), "utf-8")
    assert config.load_settings()["image_model"] == "flux2-klein"
    config.SETTINGS_FILE.write_text(json.dumps({"image_model": "sdxl-lightning", "settings_version": 2}), "utf-8")
    assert config.load_settings()["image_model"] == "sdxl-lightning"  # elección explícita posterior
    config.SETTINGS_FILE.unlink()


def test_flux2_klein_uses_recommended_steps(monkeypatch):
    seen = {}

    class FakePipe:
        def __call__(self, prompt, width=1024, height=1024, num_inference_steps=50, guidance_scale=3.5,
                     callback_on_step_end=None):
            seen.update(steps=num_inference_steps, guidance=guidance_scale, size=(width, height))
            return SimpleNamespace(images=[Image.new("RGB", (64, 112), "teal")])

    monkeypatch.setattr(image.gpu, "acquire", lambda key, loader, *a: FakePipe())
    ctx = JobContext(Job(id="f", kind="image", title="t", lane="gpu"))
    items = image.generate(ctx, "una ciudad flotante", "flux2-klein", "9:16", 1, 1, "cinematic")
    assert items and seen == {"steps": 4, "guidance": 1.0, "size": (768, 1344)}
    assert hub.QUANT_CANDIDATES[0] == "transformer"
