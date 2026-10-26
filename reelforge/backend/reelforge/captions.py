"""Subtítulos animados estilo TikTok (ASS/libass) y exportación SRT/VTT."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from . import config

# Fuentes OFL descargables (Google Fonts). family -> archivo
FONT_FILES = {
    "Poppins Black": "Poppins-Black.ttf",
    "Poppins ExtraBold": "Poppins-ExtraBold.ttf",
    "Anton": "Anton-Regular.ttf",
    "Bangers": "Bangers-Regular.ttf",
    "Bebas Neue": "BebasNeue-Regular.ttf",
    "Archivo Black": "ArchivoBlack-Regular.ttf",
    "Noto Color Emoji": "NotoColorEmoji.ttf",
}

FONT_URLS = {
    "Poppins-Black.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Black.ttf",
    "Poppins-ExtraBold.ttf": "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-ExtraBold.ttf",
    "Anton-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "Bangers-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/bangers/Bangers-Regular.ttf",
    "BebasNeue-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf",
    "ArchivoBlack-Regular.ttf": "https://github.com/google/fonts/raw/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
    "NotoColorEmoji.ttf": "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji.ttf",
}

STYLES: dict[str, dict] = {
    "viral": {
        "emph": "#39FF6A",
        "name": "Viral (Hormozi)",
        "font": "Poppins Black",
        "fallback": "Arial Black",
        "size": 86,
        "primary": "#FFFFFF",
        "active": "#FFE600",
        "outline": "#000000",
        "outline_w": 7,
        "shadow": 3,
        "effect": "pop",
        "max_words": 3,
        "uppercase": True,
    },
    "beast": {
        "emph": "#FFE600",
        "name": "Beast",
        "font": "Bangers",
        "fallback": "Impact",
        "size": 104,
        "primary": "#FFFFFF",
        "active": "#2BFF5E",
        "outline": "#000000",
        "outline_w": 9,
        "shadow": 5,
        "effect": "pop",
        "max_words": 2,
        "uppercase": True,
    },
    "highlight": {
        "emph": "#FFE600",
        "name": "Resaltado",
        "font": "Poppins ExtraBold",
        "fallback": "Arial Black",
        "size": 78,
        "primary": "#FFFFFF",
        "active": "#8B5CF6",
        "outline": "#000000",
        "outline_w": 5,
        "shadow": 0,
        "effect": "box",
        "max_words": 3,
        "uppercase": False,
    },
    "karaoke": {
        "emph": "#FFE600",
        "name": "Karaoke",
        "font": "Archivo Black",
        "fallback": "Arial Black",
        "size": 72,
        "primary": "#FFFFFF",
        "active": "#00E5FF",
        "outline": "#000000",
        "outline_w": 6,
        "shadow": 2,
        "effect": "karaoke",
        "max_words": 5,
        "uppercase": True,
    },
    "oneword": {
        "emph": "#FFE600",
        "name": "Una palabra",
        "font": "Anton",
        "fallback": "Impact",
        "size": 140,
        "primary": "#FFFFFF",
        "active": "#FFFFFF",
        "outline": "#000000",
        "outline_w": 8,
        "shadow": 4,
        "effect": "bounce",
        "max_words": 1,
        "uppercase": True,
    },
    "neon": {
        "emph": "#00E5FF",
        "name": "Neón",
        "font": "Bebas Neue",
        "fallback": "Impact",
        "size": 120,
        "primary": "#FFFFFF",
        "active": "#FF2BD6",
        "outline": "#FF2BD6",
        "outline_w": 3,
        "shadow": 0,
        "effect": "neon",
        "max_words": 3,
        "uppercase": True,
    },
    "minimal": {
        "emph": "#FFD54A",
        "name": "Minimalista",
        "font": "Poppins ExtraBold",
        "fallback": "Segoe UI Semibold",
        "size": 64,
        "primary": "#FFFFFF",
        "active": "#FFFFFF",
        "outline": "#000000",
        "outline_w": 0,
        "shadow": 3,
        "effect": "fade",
        "max_words": 6,
        "uppercase": False,
    },
}

OVERLAY_STYLES = {
    "handle": {"size": 40, "primary": "#FFFFFF", "back": "#000000", "box": False},
    "title": {"size": 96, "primary": "#FFFFFF", "back": "#000000", "box": True},
    "label": {"size": 70, "primary": "#000000", "back": "#FFE600", "box": True},
    "outline": {"size": 92, "primary": "#FFFFFF", "back": "#000000", "box": False},
}


@dataclass
class W:
    w: str
    s: float
    e: float
    emph: bool = False


def ass_color(hex_color: str, alpha: int = 0) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        h = "FFFFFF"
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def clean(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


def font_available(family: str) -> bool:
    f = FONT_FILES.get(family)
    return bool(f and (config.FONTS_DIR / f).is_file())


def resolve_font(style: dict) -> str:
    return style["font"] if font_available(style["font"]) else style["fallback"]


def group_words(words: Iterable[W], max_words: int = 3, max_chars: int = 20, gap: float = 0.5) -> list[list[W]]:
    groups: list[list[W]] = []
    cur: list[W] = []
    for word in words:
        if not word.w.strip():
            continue
        if cur:
            chars = sum(len(x.w) + 1 for x in cur) + len(word.w)
            prev = cur[-1]
            if (
                len(cur) >= max_words
                or chars > max_chars
                or word.s - prev.e > gap
                or re.search(r"[.!?;:,…]$", prev.w)
            ):
                groups.append(cur)
                cur = []
        cur.append(word)
    if cur:
        groups.append(cur)
    return groups


def _header(width: int, height: int, styles: list[str]) -> str:
    return "\n".join(
        [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {width}",
            f"PlayResY: {height}",
            "WrapStyle: 0",
            "ScaledBorderAndShadow: yes",
            "YCbCr Matrix: TV.709",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            *styles,
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]
    )


def _style_line(name: str, font: str, size: float, primary: str, secondary: str, outline: str, back: str,
                border_style: int, outline_w: float, shadow: float, margin: int) -> str:
    return (
        f"Style: {name},{font},{size:.0f},{primary},{secondary},{outline},{back},"
        f"-1,0,0,0,100,100,0,0,{border_style},{outline_w:.1f},{shadow:.1f},5,{margin},{margin},10,1"
    )


def _caption_events(groups: list[list[W]], st: dict, k: float, cx: int, cy: int, uppercase: bool,
                    emph_color: str | None = None) -> list[str]:
    effect = st["effect"]
    active = ass_color(st["active"])
    primary = ass_color(st["primary"])
    emph = ass_color(emph_color or st.get("emph", st["active"]))
    events: list[str] = []

    def txt(word: W) -> str:
        t = clean(word.w)
        return t.upper() if uppercase else t

    def plain(word: W) -> str:
        # Palabra no activa: las palabras clave conservan su color de énfasis.
        return f"{{\\c{emph}}}{txt(word)}{{\\c{primary}}}" if word.emph else txt(word)

    pos = f"\\an5\\pos({cx},{cy})"
    for gi, group in enumerate(groups):
        g_start = group[0].s
        nxt = groups[gi + 1][0].s if gi + 1 < len(groups) else None
        g_end = group[-1].e + 0.25
        if nxt is not None:
            g_end = nxt if nxt - group[-1].e < 0.7 else min(g_end, nxt)
        if effect == "fade":
            text = " ".join(plain(w) for w in group)
            events.append(f"Dialogue: 0,{ass_time(g_start)},{ass_time(g_end)},Caption,,0,0,0,,{{{pos}\\fad(120,120)}}{text}")
            continue
        if effect == "karaoke":
            parts = []
            for i, w in enumerate(group):
                end = group[i + 1].s if i + 1 < len(group) else w.e
                parts.append(f"{{\\kf{max(1, int(round((end - w.s) * 100)))}}}{txt(w)}")
            events.append(f"Dialogue: 0,{ass_time(g_start)},{ass_time(g_end)},Caption,,0,0,0,,{{{pos}\\fad(60,60)}}{' '.join(parts)}")
            continue
        for i, w in enumerate(group):
            start = g_start if i == 0 else w.s
            end = group[i + 1].s if i + 1 < len(group) else g_end
            if end - start < 0.03:
                continue
            words = []
            for j, other in enumerate(group):
                t = txt(other)
                if j != i:
                    words.append(plain(other))
                    continue
                if effect == "box":
                    pad = max(8, int(14 * k))
                    words.append(f"{{\\3c{active}\\bord{pad}\\shad0}}{t}{{\\3c{ass_color(st['outline'])}\\bord{st['outline_w'] * k:.1f}}}")
                elif effect == "bounce":
                    words.append(
                        f"{{\\fscx55\\fscy55\\t(0,90,\\fscx118\\fscy118)\\t(90,170,\\fscx100\\fscy100)}}{t}"
                    )
                else:  # pop / neon
                    words.append(
                        f"{{\\c{emph if other.emph else active}\\t(0,70,\\fscx{132 if other.emph else 120}\\fscy{132 if other.emph else 120})"
                        f"\\t(70,160,\\fscx108\\fscy108)}}{t}"
                        f"{{\\c{primary}\\fscx100\\fscy100}}"
                    )
            line = " ".join(words)
            intro = "\\fad(60,0)" if i == 0 else ""
            if effect == "neon":
                glow = ass_color(st["active"])
                events.append(
                    f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,"
                    f"{{{pos}{intro}\\blur10\\bord{8 * k:.1f}\\3c{glow}\\1a&H60&}}{line}"
                )
                events.append(f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{{{pos}{intro}}}{line}")
            else:
                events.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{{{pos}{intro}}}{line}")
    return events


def build_ass(
    width: int,
    height: int,
    words: list[dict] | list[W],
    style_id: str = "viral",
    max_words: int | None = None,
    uppercase: bool | None = None,
    position: float = 0.68,
    scale: float = 1.0,
    overlays: list[dict] | None = None,
    captions_enabled: bool = True,
    emph_color: str | None = None,
    handle: str | None = None,
    total: float | None = None,
) -> str:
    st = STYLES.get(style_id, STYLES["viral"])
    k = width / 1080 * scale
    font = resolve_font(st)
    upper = st["uppercase"] if uppercase is None else uppercase
    styles = [
        _style_line(
            "Caption",
            font,
            st["size"] * k,
            ass_color(st["primary"]) if st["effect"] != "karaoke" else ass_color(st["active"]),
            ass_color(st["primary"]),
            ass_color(st["outline"]),
            ass_color("#000000", 0x80),
            1,
            st["outline_w"] * k,
            st["shadow"] * k,
            int(60 * width / 1080),
        )
    ]
    ok = width / 1080
    for name, ost in OVERLAY_STYLES.items():
        title_font = "Poppins Black" if font_available("Poppins Black") else "Arial Black"
        styles.append(
            _style_line(
                f"Ov_{name}",
                title_font,
                ost["size"] * ok,
                ass_color(ost["primary"]),
                ass_color(ost["primary"]),
                ass_color(ost["back"]) if ost["box"] else ass_color("#000000"),
                ass_color(ost["back"]),
                3 if ost["box"] else 1,
                (16 if ost["box"] else 7) * ok,
                0 if ost["box"] else 3 * ok,
                int(70 * ok),
            )
        )
    events: list[str] = []
    if captions_enabled and words:
        ws = [w if isinstance(w, W) else W(str(w["w"]), float(w["s"]), float(w["e"]), bool(w.get("emph")))
              for w in words]
        ws.sort(key=lambda w: w.s)
        groups = group_words(ws, max_words or st["max_words"], max_chars=max(10, int(22 / max(0.6, scale))))
        events += _caption_events(groups, st, k, width // 2, int(height * position), upper, emph_color)
    for ov in overlays or []:
        name = ov.get("style", "title")
        if name not in OVERLAY_STYLES:
            name = "title"
        y = int(height * float(ov.get("position", 0.18)))
        sc = int(100 * float(ov.get("scale", 1.0)))
        text = clean(str(ov.get("text", ""))).replace("|", "\\N")
        anim = f"\\an5\\pos({width // 2},{y})\\fad(150,150)\\fscx{sc * 0.8:.0f}\\fscy{sc * 0.8:.0f}\\t(0,180,\\fscx{sc}\\fscy{sc})"
        events.append(
            f"Dialogue: 5,{ass_time(float(ov.get('start', 0)))},{ass_time(float(ov.get('end', 3)))},Ov_{name},,0,0,0,,{{{anim}}}{text}"
        )
    if handle and total:
        # Marca de agua con el @usuario: discreta, abajo a la derecha, siempre visible.
        pos = f"\\an3\\pos({width - int(40 * ok)},{height - int(150 * ok)})\\1a&H40&\\3a&H60&"
        events.append(f"Dialogue: 6,{ass_time(0)},{ass_time(total)},Ov_handle,,0,0,0,,{{{pos}}}{clean(handle)}")
    return _header(width, height, styles) + "\n" + "\n".join(events) + "\n"


def _srt_time(t: float, sep: str = ",") -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def build_srt(words: list[dict], vtt: bool = False) -> str:
    ws = [W(str(w["w"]), float(w["s"]), float(w["e"])) for w in words]
    groups = group_words(ws, max_words=8, max_chars=42, gap=0.8)
    lines = ["WEBVTT", ""] if vtt else []
    for i, g in enumerate(groups, 1):
        if not vtt:
            lines.append(str(i))
        sep = "." if vtt else ","
        lines.append(f"{_srt_time(g[0].s, sep)} --> {_srt_time(g[-1].e, sep)}")
        lines.append(" ".join(w.w.strip() for w in g))
        lines.append("")
    return "\n".join(lines)


def write_ass(path: Path, **kwargs) -> Path:
    path.write_text(build_ass(**kwargs), "utf-8")
    return path


def words_from_text(text: str, duration: float) -> list[dict]:
    """Reparte palabras proporcionalmente al número de letras (si no hay transcripción)."""
    tokens = text.split()
    if not tokens or duration <= 0:
        return []
    weights = [max(2, len(t)) for t in tokens]
    total = sum(weights)
    out, t = [], 0.0
    for tok, wgt in zip(tokens, weights):
        d = duration * wgt / total
        out.append({"w": tok, "s": round(t, 3), "e": round(t + d * 0.92, 3)})
        t += d
    return out
