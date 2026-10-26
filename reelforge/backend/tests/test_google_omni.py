import base64
import subprocess
from types import SimpleNamespace

import pytest

from reelforge import config, ffmpeg
from reelforge.ai import google
from reelforge.jobs import Job, JobContext


@pytest.fixture
def mp4(tmp_path):
    p = tmp_path / "clip.mp4"
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc=s=320x568:d=1", "-pix_fmt",
                    "yuv420p", str(p)], check=True, capture_output=True)
    return p


def test_omni_flash_uses_interactions_api(mp4, tmp_path, monkeypatch):
    from google.genai._gaos.types.interactions.createmodelinteraction import CreateModelInteraction

    config.save_settings({"gemini_api_key": "test-key", "google_video_model": "gemini-omni-1.1-flash"})
    calls = {}

    class FakeInteractions:
        def create(self, **kwargs):
            calls.update(kwargs)
            video = SimpleNamespace(data=base64.b64encode(mp4.read_bytes()).decode(), uri=None)
            return SimpleNamespace(output_video=video, status="completed", errors=None)

    monkeypatch.setattr(google, "_client", lambda: SimpleNamespace(interactions=FakeInteractions()))
    img = tmp_path / "start.png"
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x568", "-frames:v", "1",
                    str(img)], check=True, capture_output=True)
    ctx = JobContext(Job(id="g", kind="google-video", title="t", lane="io"))
    item = google.generate_video(ctx, "a cat surfing", "9:16", str(img), duration=8, resolution="1080p")

    assert item["kind"] == "video" and item["name"].startswith("Omni")
    assert calls["model"] == "gemini-omni-1.1-flash"
    assert calls["response_format"] == {"type": "video", "aspect_ratio": "9:16", "duration": "8s", "resolution": "1080p"}
    # La petición encaja con el esquema oficial del SDK.
    req = {k: v for k, v in calls.items() if k != "timeout"}
    CreateModelInteraction.model_validate(req)
