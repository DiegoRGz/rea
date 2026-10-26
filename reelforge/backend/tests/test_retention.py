import subprocess
from pathlib import Path

from reelforge import analysis, config, ffmpeg, render, retention
from reelforge.jobs import Job, JobContext
from reelforge.project import AudioItem, Captions, Clip, Project, register_media, update_media


def _make(tmp: Path, name: str, args: list[str]) -> Path:
    out = tmp / name
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", *args, str(out)], check=True, capture_output=True)
    return out


def _ctx():
    return JobContext(Job(id="r", kind="t", title="t", lane="gpu"))


def test_beat_detection_finds_tempo(tmp_path):
    clicks = _make(tmp_path, "clicks.wav", ["-f", "lavfi", "-i",
                   "aevalsrc='if(lt(mod(t,0.5),0.03),sin(2*PI*1000*t),0)':d=8:s=44100"])
    res = analysis.detect_beats(str(clicks))
    assert abs(res["bpm"] - 120) < 4
    assert len(res["beats"]) >= 14


def test_auto_edit_talking_head(tmp_path):
    talk = register_media(_make(tmp_path, "talk.mp4", ["-f", "lavfi", "-i", "testsrc=s=1280x720:r=30:d=12", "-f",
                                                       "lavfi", "-i", "sine=f=200:d=12", "-shortest", "-pix_fmt", "yuv420p"]))
    # Habla con un silencio largo (4-7 s) y una muletilla.
    text = [("Hoy", 0.2), ("te", 0.6), ("cuento", 0.9), ("eh", 1.5), ("cómo", 2.0), ("ganar", 2.4), ("dinero", 2.9),
            ("rápido", 3.4), ("con", 7.2), ("inteligencia", 7.6), ("artificial", 8.3), ("gratis", 9.0),
            ("sígueme", 10.5)]
    words = [{"w": w, "s": s, "e": s + 0.35} for w, s in text]
    update_media(talk.id, meta={"words": words})
    for i in range(2):
        register_media(_make(tmp_path, f"b{i}.png", ["-f", "lavfi", "-i", "mandelbrot=s=600x900", "-frames:v", "1"]))
    music = register_media(_make(tmp_path, "music.wav", ["-f", "lavfi", "-i",
                                 "aevalsrc='if(lt(mod(t,0.5),0.03),sin(2*PI*900*t),0)':d=12:s=44100"]))
    p = Project(clips=[Clip(media_id=talk.id, kind="video", src_in=0, src_out=12, fit="blur")],
                audio=[AudioItem(media_id=music.id, role="music", volume=0.2, loop=True)], captions=Captions())
    opts = retention.AutoEditOptions(broll="library", broll_every=3.0, broll_duration=1.2)
    report = retention.auto_edit(_ctx(), p, opts)

    assert report["cuts"] >= 1 and len(p.clips) >= 2                       # silencio eliminado
    assert all(w.w != "eh" for w in p.captions.words)                       # muletilla eliminada
    assert p.clips[1].zoom > 1.0                                            # jump-zoom alterno
    assert report["keywords"] >= 1 and any(w.emph for w in p.captions.words)
    assert any(w.emoji for w in p.captions.words)                           # emojis del diccionario
    assert any(e.type in ("punch", "shake") for e in p.effects)
    assert any(a.role == "sfx" and a.auto for a in p.audio)
    assert p.broll and all(b.auto for b in p.broll)
    assert 0 <= p.score["score"] <= 100 and p.score["checks"]
    # Repetir la edición no duplica lo automático.
    n_sfx = sum(a.auto for a in p.audio)
    retention.auto_edit(_ctx(), p, opts)
    assert sum(a.auto for a in p.audio) == n_sfx

    out = render.render_project(p, render.ExportOptions(resolution="540p", quality="draft"),
                                config.EXPORTS_DIR / "auto-edit.mp4")
    assert out["duration"] < 10.5  # se quitaron ~3 s de silencio
