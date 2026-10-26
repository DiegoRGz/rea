import subprocess

import numpy as np

from reelforge import clipper, config, ffmpeg, render
from reelforge.jobs import Job, JobContext
from reelforge.project import load_project, register_media, update_media


def test_smooth_track_is_stable_and_follows_cuts():
    samples = [(t / 3, 0.30 + (0.01 if t % 2 else 0), False) for t in range(12)]  # jitter pequeño
    samples += [(4 + t / 3, 0.75, t == 0) for t in range(9)]                    # corte de cámara
    keys = clipper.smooth_track(samples)
    early = [c for t, c in keys if t < 3.9]
    assert max(early) - min(early) < 0.02          # zona muerta: no tiembla
    assert keys[-1][1] == 0.75                      # tras el corte salta al nuevo sujeto
    assert len(keys) <= 6                           # simplificado


def test_clipper_pipeline_with_tracking(tmp_path, monkeypatch):
    src = tmp_path / "podcast.mp4"
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=25:d=70",
                    "-f", "lavfi", "-i", "sine=f=180:d=70", "-shortest", "-pix_fmt", "yuv420p", str(src)],
                   check=True, capture_output=True)
    media = register_media(src)
    words, t = [], 0.5
    for i in range(160):
        w = "¿Sabías" if i % 40 == 0 else ("secreto!" if i % 40 == 20 else f"palabra{i}")
        words.append({"w": w + ("." if i % 9 == 8 else ""), "s": round(t, 2), "e": round(t + 0.3, 2)})
        t += 0.42
    update_media(media.id, meta={"words": words})

    def fake_detector(frame):
        # Una "cara" que se desplaza de izquierda a derecha
        x = float(frame.mean()) % 1 * 0 + 0.3 + 0.4 * (fake_detector.n % 30) / 30
        fake_detector.n += 1
        return [(x, 0.4, 0.05)]

    fake_detector.n = 0
    monkeypatch.setattr(clipper, "_face_detector", lambda w, h: fake_detector)
    ctx = JobContext(Job(id="c", kind="clipper", title="t", lane="gpu"))
    req = clipper.ClipperRequest(media_id=media.id, count=2, min_len=15, max_len=30)
    out = clipper.run(ctx, req)
    assert out["method"] == "heurística" and len(out["clips"]) == 2
    first = out["clips"][0]
    assert first["tracked"] and 15 <= first["end"] - first["start"] <= 31
    p = load_project(first["project_id"])
    assert p.clips[0].fit == "track" and p.captions.words and p.texts
    res = render.render_project(p, render.ExportOptions(resolution="540p", quality="draft", thumbnail=True,
                                                        cover_text="El secreto"), config.EXPORTS_DIR / "clip.mp4")
    assert res["extras"]["thumbnail"].endswith(".jpg")
    assert np.isfinite(res["duration"])
