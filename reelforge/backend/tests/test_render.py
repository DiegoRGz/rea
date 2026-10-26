import subprocess
from pathlib import Path

import pytest

from reelforge import captions, config, ffmpeg, render
from reelforge.project import AudioItem, Captions, Clip, Project, TextOverlay, Transition, Word, register_media


def _make(tmp: Path, name: str, args: list[str]) -> Path:
    out = tmp / name
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", *args, str(out)], check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("src")
    img = _make(tmp, "photo.png", ["-f", "lavfi", "-i", "testsrc2=s=1200x800", "-frames:v", "1"])
    vid = _make(tmp, "clip.mp4", ["-f", "lavfi", "-i", "testsrc=s=1280x720:r=25:d=4", "-f", "lavfi", "-i",
                                  "sine=f=330:d=4", "-shortest", "-pix_fmt", "yuv420p"])
    voice = _make(tmp, "voice.wav", ["-f", "lavfi", "-i", "sine=f=440:d=6"])
    music = _make(tmp, "music.mp3", ["-f", "lavfi", "-i", "sine=f=220:d=3"])
    return {k: register_media(v) for k, v in {"img": img, "vid": vid, "voice": voice, "music": music}.items()}


def _duration(path: str) -> float:
    return ffmpeg.probe(path)["duration"]


def test_render_with_transitions_captions_and_ducking(media):
    words = captions.words_from_text("Esto es un reel viral de prueba con subtítulos animados", 5.5)
    p = Project(
        name="test",
        clips=[
            Clip(media_id=media["img"].id, kind="image", duration=3, motion="zoom_in",
                 transition=Transition(type="slideup", duration=0.5)),
            Clip(media_id=media["vid"].id, kind="video", src_in=0.5, src_out=3.5, fit="blur", filter="cinematic",
                 transition=Transition(type="none")),
            Clip(media_id=media["img"].id, kind="image", duration=2, motion="pan_left", filter="bw"),
        ],
        audio=[
            AudioItem(media_id=media["voice"].id, role="voice"),
            AudioItem(media_id=media["music"].id, role="music", volume=0.3, loop=True, fade_out=1),
        ],
        captions=Captions(words=[Word(**w) for w in words], style="viral"),
        texts=[TextOverlay(text="¿SABÍAS ESTO?", start=0, end=2)],
    )
    out = config.EXPORTS_DIR / "t1.mp4"
    res = render.render_project(p, render.ExportOptions(resolution="540p", quality="draft", subtitles_file=True,
                                                        thumbnail=True), out)
    assert Path(res["path"]).is_file()
    # 3 + 3 + 2 - 0.5 (xfade) = 7.5
    assert abs(_duration(res["path"]) - 7.5) < 0.15
    info = ffmpeg.probe(res["path"])
    assert info["width"] == 540 and info["height"] == 960
    assert Path(res["extras"]["srt"]).read_text().startswith("1\n")
    assert Path(res["extras"]["thumbnail"]).is_file()


@pytest.mark.parametrize("style", list(captions.STYLES))
def test_every_caption_style_renders(media, style):
    words = captions.words_from_text("Hola mundo, este estilo funciona perfecto!", 2.5)
    p = Project(clips=[Clip(media_id=media["img"].id, kind="image", duration=2.5, motion="none")],
                captions=Captions(words=[Word(**w) for w in words], style=style))
    res = render.render_project(p, render.ExportOptions(resolution="540p", quality="draft"),
                                config.EXPORTS_DIR / f"style-{style}.mp4")
    assert abs(res["duration"] - 2.5) < 0.05


def test_audio_only_and_no_clips(media):
    p = Project(audio=[AudioItem(media_id=media["voice"].id)])
    res = render.render_project(p, render.ExportOptions(resolution="540p", quality="draft", audio_only=True),
                                config.EXPORTS_DIR / "a.mp3")
    assert abs(_duration(res["path"]) - 6.0) < 0.2


def test_every_transition_builds(media):
    clips = []
    for t in render.TRANSITIONS:
        clips.append(Clip(media_id=media["img"].id, kind="image", duration=1.0, motion="none",
                          transition=Transition(type=t, duration=0.3)))
    p = Project(clips=clips)
    res = render.render_project(p, render.ExportOptions(resolution="540p", quality="draft"),
                                config.EXPORTS_DIR / "all-transitions.mp4")
    expected = len(clips) - 0.3 * (len(clips) - 2)  # "none" es corte; el último clip no tiene salida
    assert abs(_duration(res["path"]) - expected) < 0.25


def test_ass_structure():
    ass = captions.build_ass(1080, 1920, [{"w": "hola", "s": 0, "e": 0.4}, {"w": "mundo", "s": 0.4, "e": 0.9}],
                             overlays=[{"text": "TITULO", "start": 0, "end": 1}])
    assert "PlayResX: 1080" in ass
    assert ass.count("Dialogue:") == 3
    assert "HOLA" in ass and "\\t(" in ass
    assert captions.ass_color("#FFE600") == "&H0000E6FF"
