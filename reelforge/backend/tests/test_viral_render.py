import subprocess
from pathlib import Path

import pytest

from reelforge import assets, config, ffmpeg, render
from reelforge.project import (AudioItem, BRoll, Captions, Clip, Effect, Project, TextOverlay, Word,
                               register_media)


def _make(tmp: Path, name: str, args: list[str]) -> Path:
    out = tmp / name
    subprocess.run([ffmpeg.binary(), "-hide_banner", "-y", *args, str(out)], check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("viral")
    wide = _make(tmp, "talk.mp4", ["-f", "lavfi", "-i", "testsrc=s=1280x720:r=30:d=6", "-f", "lavfi", "-i",
                                   "sine=f=220:d=6", "-shortest", "-pix_fmt", "yuv420p"])
    img = _make(tmp, "broll.png", ["-f", "lavfi", "-i", "mandelbrot=s=800x1200", "-frames:v", "1"])
    logo = _make(tmp, "logo.png", ["-f", "lavfi", "-i", "color=c=0xff4d9d:s=200x200", "-frames:v", "1"])
    return {k: register_media(v) for k, v in {"talk": wide, "img": img, "logo": logo}.items()}


def test_viral_edit_features_render(media):
    config.save_settings({"brand_logo_media_id": media["logo"].id, "brand_handle": "@reelforge",
                          "brand_keyword_color": "#39FF6A"})
    words = [Word(w=w, s=0.3 + i * 0.5, e=0.3 + i * 0.5 + 0.4) for i, w in enumerate("esto te hará ganar mucho dinero rápido hoy".split())]
    words[4].emph, words[5].emoji = True, "💰"
    p = Project(
        clips=[
            Clip(media_id=media["talk"].id, kind="video", src_in=0, src_out=3, fit="track",
                 track=[[0, 0.3], [1.5, 0.7], [3, 0.5]]),
            Clip(media_id=media["talk"].id, kind="video", src_in=3, src_out=6, fit="cover", zoom=1.15),
        ],
        captions=Captions(words=words, style="viral"),
        effects=[Effect(type="punch", start=1.0, duration=0.4), Effect(type="shake", start=2.2, duration=0.3),
                 Effect(type="flash", start=0.0, duration=0.08)],
        broll=[BRoll(media_id=media["img"].id, start=3.5, duration=1.5)],
        audio=[AudioItem(media_id=assets.sfx_media("whoosh"), role="sfx", start=2.8, volume=0.6),
               AudioItem(media_id=assets.sfx_media("pop"), role="sfx", start=2.8, volume=0.6)],
        texts=[TextOverlay(text="NADIE TE LO DICE", start=0, end=1.5)],
    )
    out = config.EXPORTS_DIR / "viral.mp4"
    res = render.render_project(p, render.ExportOptions(resolution="540p", quality="draft"), out)
    assert abs(ffmpeg.probe(res["path"])["duration"] - 6.0) < 0.15
    config.save_settings({"brand_logo_media_id": "", "brand_handle": ""})


def test_sfx_library_is_generated_once():
    a = assets.sfx_media("boom")
    assert assets.sfx_media("boom") == a
    for name in assets.SFX:
        assert assets.sfx_media(name)
