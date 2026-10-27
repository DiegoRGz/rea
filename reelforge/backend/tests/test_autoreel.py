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


def test_hybrid_mode_uses_video_only_for_the_hook(tmp_path, monkeypatch):
    monkeypatch.setattr(autoreel.tts, "synthesize", _fake_tts)
    clip = tmp_path / "hook.mp4"
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc=s=480x832:r=16:d=3",
                    "-pix_fmt", "yuv420p", str(clip)], check=True, capture_output=True)
    calls, messages = [], []

    def fake_video(ctx, prompt, model, seconds=3.0, **k):
        calls.append(("video", seconds))
        ctx.progress(0.5, "Generando vídeo · paso 10/20")
        messages.append(ctx.job.message)
        return register_media(clip).model_dump()

    def fake_image(ctx, prompt, model, *a, **k):
        calls.append(("image", model))
        return [_image(tmp_path, f"i{len(calls)}.png").model_dump()]

    monkeypatch.setattr(autoreel.video, "generate", fake_video)
    monkeypatch.setattr(autoreel.image, "generate", fake_image)
    req = autoreel.AutoReelRequest(scenes=[autoreel.Scene(narration=f"escena {i} con bastantes palabras para durar") for i in range(3)],
                                   tts_engine="edge", visual_mode="hybrid", auto_edit=False, brand=False)
    res = autoreel.build(JobContext(Job(id="h", kind="autoreel", title="t", lane="gpu")), req)
    assert [c[0] for c in calls] == ["video", "image", "image"]
    assert calls[0][1] <= 3.5
    assert messages[0].startswith("Escena 1/3 · ")
    p = load_project(res["project_id"])
    assert p.clips[0].kind == "video" and p.clips[1].kind == "image"


def test_heartbeat_maps_progress_inside_a_scene():
    import time

    from reelforge.jobs import heartbeat

    job = Job(id="hb", kind="t", title="t", lane="gpu")
    sub = autoreel._Sub(JobContext(job), 0.5, 0.6, "Escena 2/3 · ")
    with heartbeat(sub, "Codificando", 0.0, 1.0, expected=1):
        time.sleep(1.2)
    assert 0.5 <= job.progress <= 0.6 and job.message.startswith("Escena 2/3 · Codificando")
