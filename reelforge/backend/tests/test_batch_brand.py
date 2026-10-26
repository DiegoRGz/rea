import subprocess

from reelforge import batch, brand, config, ffmpeg
from reelforge.jobs import Job, JobContext
from reelforge.project import Captions, Clip, Project, Word, register_media, save_project, timeline_duration


def _img(tmp_path, name):
    p = tmp_path / name
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc2=s=600x900", "-frames:v", "1",
                    str(p)], check=True, capture_output=True)
    return register_media(p)


def test_brand_bookends_shift_everything(tmp_path):
    intro, outro, scene = _img(tmp_path, "intro.png"), _img(tmp_path, "outro.png"), _img(tmp_path, "scene.png")
    config.save_settings({"brand_intro_media_id": intro.id, "brand_outro_media_id": outro.id,
                          "brand_cta": "Sígueme", "brand_cta_enabled": True})
    p = Project(clips=[Clip(media_id=scene.id, kind="image", duration=4)],
                captions=Captions(words=[Word(w="hola", s=0.5, e=0.9)]))
    brand.apply_brand(p)
    brand.apply_brand(p)  # idempotente
    assert [c.media_id for c in p.clips] == [intro.id, scene.id, outro.id]
    assert p.captions.words[0].s == 2.0  # desplazado por la intro de 1,5 s
    cta = [t for t in p.texts if t.text == "Sígueme"]
    assert len(cta) == 1 and abs(cta[0].end - (timeline_duration(p) - 1.5)) < 0.01
    config.save_settings({"brand_intro_media_id": "", "brand_outro_media_id": "", "brand_cta_enabled": False})


def test_batch_continues_after_errors_and_exports(tmp_path, monkeypatch):
    scene = _img(tmp_path, "b.png")
    calls = []

    def fake_script(topic, *a, **k):
        if "falla" in topic:
            raise RuntimeError("LLM caído")
        return {"title": topic.title(), "hook": "", "scenes": [{"narration": topic, "visual": topic}], "caption": "",
                "hashtags": ["#x"]}

    def fake_build(ctx, req):
        calls.append(req)
        p = save_project(Project(name=req.title, clips=[Clip(media_id=scene.id, kind="image", duration=2)]))
        return {"project_id": p.id, "duration": 2}

    monkeypatch.setattr(batch.llm, "write_script", fake_script)
    monkeypatch.setattr(batch.autoreel, "build", fake_build)
    ctx = JobContext(Job(id="b", kind="batch", title="t", lane="gpu"))
    res = batch.run(ctx, batch.BatchRequest(topics=["uno", "esto falla", "dos"], template="top", export_preset="draft"))
    status = [i["status"] for i in res["items"]]
    assert status == ["done", "error", "done"]
    assert all(i.get("export", "").endswith(".mp4") for i in res["items"] if i["status"] == "done")
    assert calls[0].caption_style == "beast" and calls[0].transition == "zoomin"  # plantilla Top N
    assert batch.list_batches()[0]["id"] == res["id"]
