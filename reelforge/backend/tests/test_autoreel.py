import subprocess

from reelforge import autoreel, config, ffmpeg, render
from reelforge.jobs import Job, JobContext
from reelforge.project import load_project, media_output_path, register_media


def _fake_tts(ctx, text, engine, voice, speed, pitch=0, name=None, lang="es"):
    out = media_output_path(".wav", "voz")
    dur = max(1.0, len(text.split()) * 0.35)
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i", f"sine=f=300:d={dur}", str(out)],
                   check=True, capture_output=True)
    words = []
    if engine == "edge":
        t = 0.0
        for w in text.split():
            words.append({"w": w, "s": round(t, 3), "e": round(t + 0.3, 3)})
            t += 0.35
    return register_media(out, source="tts", meta={"words": words}).model_dump()


def _image(tmp_path, name):
    p = tmp_path / name
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc2=s=800x1200", "-frames:v", "1",
                    str(p)], check=True, capture_output=True)
    return register_media(p)


def test_autoreel_builds_synced_editable_project(tmp_path, monkeypatch):
    monkeypatch.setattr(autoreel.tts, "synthesize", _fake_tts)
    imgs = [_image(tmp_path, f"s{i}.png") for i in range(3)]
    req = autoreel.AutoReelRequest(
        title="Prueba",
        hook="¿Lo sabías?",
        scenes=[autoreel.Scene(narration=f"escena número {i} con varias palabras", media_id=imgs[i].id) for i in range(3)],
        tts_engine="edge",
        visual_mode="library",
        transition="fade",
        transition_duration=0.3,
    )
    ctx = JobContext(Job(id="t", kind="autoreel", title="t", lane="gpu"))
    res = autoreel.build(ctx, req)
    p = load_project(res["project_id"])
    assert len(p.clips) == 3 and p.audio[0].role == "voice"
    # Las palabras de cada escena se desplazan al inicio de su escena.
    assert p.captions.words[0].s == 0 and p.captions.words[6].s > 2.0
    out = render.render_project(p, render.ExportOptions(resolution="540p", quality="draft"), config.EXPORTS_DIR / "auto.mp4")
    # Duración = voz total + 0,3 s de cola: las transiciones no desincronizan la voz.
    assert abs(out["duration"] - (res["duration"] + 0.3)) < 0.05
