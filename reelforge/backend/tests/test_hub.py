from types import SimpleNamespace

from PIL import Image

from reelforge.ai import hub, image
from reelforge.jobs import Job, JobContext


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def test_search_queries_trending_diffusers_models(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(url=url, params=params)
        return FakeResponse([{"id": "org/new-model", "likes": 1200, "downloads": 50000, "trendingScore": 88,
                              "createdAt": "2026-10-01T00:00:00Z", "tags": ["license:apache-2.0"]}])

    monkeypatch.setattr(hub.httpx, "get", fake_get)
    res = hub.search("video", "trending", "wan")
    assert seen["params"]["pipeline_tag"] == "text-to-video" and seen["params"]["sort"] == "trendingScore"
    assert seen["params"]["library"] == "diffusers" and seen["params"]["search"] == "wan"
    assert res[0]["repo"] == "org/new-model" and res[0]["license"] == "apache-2.0"


def test_weight_size_ignores_duplicate_variants():
    gb = 1024**3
    files = [
        {"type": "file", "path": "unet/diffusion_pytorch_model.safetensors", "size": 10 * gb},
        {"type": "file", "path": "unet/diffusion_pytorch_model.fp16.safetensors", "size": 5 * gb},
        {"type": "file", "path": "vae/diffusion_pytorch_model.safetensors", "size": gb},
        {"type": "file", "path": "model_index.json", "size": 100},
    ]
    assert hub._weights_size(files) == 6.0
    assert hub.compatibility(6.0, 8.0, 48)["level"] == "ok"
    assert hub.compatibility(20.0, 8.0, 48)["level"] == "slow"
    assert hub.compatibility(60.0, 8.0, 48)["level"] == "no"


def test_added_model_generates_through_generic_loader(monkeypatch):
    hub.add_model("org/cool-image", "image", name="Cool", size_gb=4.0)
    assert "hf:org/cool-image" in hub.models("image")
    calls = {}

    class FakePipe:
        def __call__(self, prompt, width=1024, height=1024, num_inference_steps=50, guidance_scale=3.5,
                     callback_on_step_end=None):
            calls.update(prompt=prompt, width=width, height=height, steps=num_inference_steps)
            callback_on_step_end(self, 0, 0, {})
            return SimpleNamespace(images=[Image.new("RGB", (width // 8, height // 8), "purple")])

    monkeypatch.setattr(hub.gpu, "acquire", lambda key, loader: FakePipe())
    ctx = JobContext(Job(id="h", kind="image", title="t", lane="gpu"))
    items = image.generate(ctx, "a neon city", "hf:org/cool-image", "9:16", 1, 7, "none", steps=6)
    assert items[0]["kind"] == "image"
    # negative_prompt no está en la firma del pipeline: no se envía.
    assert calls == {"prompt": "a neon city", "width": 768, "height": 1344, "steps": 6}
    assert hub.remove_model("org/cool-image") and "hf:org/cool-image" not in hub.models("image")
