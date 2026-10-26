"""Edición viral automática: cortes de silencios y muletillas, palabras clave
con color y emojis, zooms de impacto, efectos de sonido, B-roll, ajuste al
ritmo de la música y puntuación de retención."""

from __future__ import annotations

import itertools
import re
from typing import Any, Optional

from pydantic import BaseModel

from . import analysis, assets, gpu
from .ai import llm, stt
from .jobs import JobContext
from .project import (AudioItem, BRoll, Clip, Effect, Project, Word, clip_lengths, effective_transitions,
                      get_media, list_media, new_id, timeline_duration)


class AutoEditOptions(BaseModel):
    cut_silences: bool = True
    min_gap: float = 0.4
    pad: float = 0.08
    remove_fillers: bool = True
    jump_zoom: bool = True
    keywords: bool = True
    emojis: bool = True
    punch_zooms: bool = True
    hook_effects: bool = True
    sfx: bool = True
    sfx_volume: float = 0.55
    broll: str = "none"  # none | library | generate
    broll_every: float = 5.0
    broll_duration: float = 1.8
    image_model: Optional[str] = None
    beat_sync: bool = True
    whisper_model: str = "large-v3-turbo"
    lang: str = "es"


FILLERS = {"eh", "ehh", "ehm", "em", "emm", "mm", "mmm", "hmm", "uh", "um", "uhm", "ah", "aah", "este…", "eeh"}

STOPWORDS = set("""a al algo alguien ante antes aquí así aun aunque bien cada como con contra cual cuando de del desde
donde dos el ella ellas ellos en entre era eres es esa ese eso esta este esto estos estas fue ha hay hasta la las le
les lo los más me mi mis mucho muy nada ni no nos o os otra otro para pero poco por porque que qué se sea ser si sí
sin sobre solo son su sus también te tu tus un una uno unos y ya yo the and for that this with you your are was have
from but not what all can just like""".split())

EMOJI_MAP = {
    "dinero": "💰", "plata": "💰", "money": "💰", "rico": "🤑", "millón": "💸", "millones": "💸", "gratis": "🆓",
    "fuego": "🔥", "brutal": "🔥", "increíble": "🤯", "loco": "🤯", "secreto": "🤫", "idea": "💡", "truco": "💡",
    "cerebro": "🧠", "mente": "🧠", "amor": "❤️", "corazón": "❤️", "tiempo": "⏰", "rápido": "⚡", "energía": "⚡",
    "éxito": "🏆", "ganar": "🏆", "mejor": "🏆", "peligro": "⚠️", "cuidado": "⚠️", "error": "❌", "nunca": "🚫",
    "nadie": "🤐", "verdad": "✅", "correcto": "✅", "crecer": "📈", "crecimiento": "📈", "mundo": "🌍",
    "comida": "🍔", "salud": "💪", "fuerza": "💪", "dormir": "😴", "risa": "😂", "gracioso": "😂", "miedo": "😱",
    "sorpresa": "😮", "música": "🎵", "foto": "📸", "vídeo": "🎬", "video": "🎬", "casa": "🏠", "coche": "🚗",
    "viaje": "✈️", "trabajo": "💼", "estudiar": "📚", "libro": "📚", "teléfono": "📱", "móvil": "📱", "ia": "🤖",
    "robot": "🤖", "futuro": "🚀", "cohete": "🚀", "estrella": "⭐", "top": "🔝", "pregunta": "❓",
}


def _norm(w: str) -> str:
    return re.sub(r"[^\wáéíóúüñ]", "", w.lower())


# ------------------------------------------------------------- transcripción


def _media_words(ctx: JobContext, media_id: str, opts: AutoEditOptions) -> list[dict]:
    media = get_media(media_id)
    if not media:
        return []
    if media.meta.get("words"):
        return media.meta["words"]
    if not media.has_audio and media.kind != "audio":
        return []
    return stt.transcribe_media(ctx, media_id, opts.whisper_model, opts.lang)["words"]


def ensure_captions(ctx: JobContext, project: Project, opts: AutoEditOptions) -> None:
    """Garantiza que el proyecto tiene palabras con tiempos (de la voz o del audio de los clips)."""
    if project.captions.words:
        return
    words: list[dict] = []
    voice = next((a for a in project.audio if a.role == "voice"), None)
    if voice:
        media = get_media(voice.media_id)
        end = voice.src_out if voice.src_out is not None else (media.duration if media else 1e9) or 1e9
        for w in _media_words(ctx, voice.media_id, opts):
            if voice.src_in <= w["s"] < end:
                words.append({"w": w["w"], "s": w["s"] - voice.src_in + voice.start,
                              "e": w["e"] - voice.src_in + voice.start})
    else:
        words = _clip_timeline_words(ctx, project, opts)
    project.captions.words = [Word(w=w["w"], s=round(w["s"], 3), e=round(w["e"], 3)) for w in words]
    project.captions.enabled = True


def _clip_timeline_words(ctx: JobContext, project: Project, opts: AutoEditOptions) -> list[dict]:
    lengths = clip_lengths(project)
    trans = effective_transitions(project, lengths)
    start, out = 0.0, []
    for i, c in enumerate(project.clips):
        if c.kind == "video":
            end = c.src_out if c.src_out is not None else 1e9
            for w in _media_words(ctx, c.media_id, opts):
                if c.src_in <= w["s"] < end:
                    out.append({"w": w["w"], "s": start + (w["s"] - c.src_in) / c.speed,
                                "e": start + (min(w["e"], end) - c.src_in) / c.speed})
        start += lengths[i] - (trans[i] if i < len(trans) else 0)
    return out


# --------------------------------------------------------- cortes de silencio


def cut_silences(ctx: JobContext, project: Project, opts: AutoEditOptions) -> int:
    """Divide los clips de vídeo hablados quitando silencios y muletillas. Devuelve los cortes hechos."""
    if any(a.role == "voice" for a in project.audio):
        return 0  # la narración sintética ya no tiene silencios largos
    new_clips: list[Clip] = []
    removed = 0
    for clip in project.clips:
        media = get_media(clip.media_id)
        if clip.kind != "video" or not media or not media.has_audio:
            new_clips.append(clip)
            continue
        end = clip.src_out if clip.src_out is not None else (media.duration or 0)
        words = [w for w in _media_words(ctx, clip.media_id, opts) if clip.src_in <= w["s"] < end]
        if opts.remove_fillers:
            words = [w for w in words if _norm(w["w"]) not in FILLERS]
        if not words:
            new_clips.append(clip)
            continue
        ranges: list[list[float]] = []
        for w in words:
            s, e = max(clip.src_in, w["s"] - opts.pad), min(end, w["e"] + opts.pad)
            if ranges and s - ranges[-1][1] <= opts.min_gap:
                ranges[-1][1] = max(ranges[-1][1], e)
            else:
                ranges.append([s, e])
        ranges[0][0] = clip.src_in if ranges[0][0] - clip.src_in <= opts.min_gap else ranges[0][0]
        ranges = [r for r in ranges if r[1] - r[0] >= 0.25]
        removed += max(0, len(ranges) - 1)
        for k, (s, e) in enumerate(ranges):
            part = clip.model_copy(deep=True, update={"id": new_id(), "src_in": round(s, 3), "src_out": round(e, 3)})
            if k < len(ranges) - 1:
                part.transition.type = "none"
            new_clips.append(part)
    project.clips = new_clips
    if removed:
        # Las palabras cambian de posición: se recalculan desde el audio de los clips.
        mapped = _clip_timeline_words(ctx, project, opts)
        project.captions.words = [Word(w=w["w"], s=round(w["s"], 3), e=round(w["e"], 3)) for w in mapped]
    return removed


def apply_jump_zoom(project: Project) -> None:
    """Alterna encuadre 100 % / 112 % entre cortes consecutivos del mismo vídeo (estilo jump-cut)."""
    prev_media, flip = None, False
    for clip in project.clips:
        if clip.kind != "video":
            prev_media = None
            continue
        flip = not flip if clip.media_id == prev_media else False
        clip.zoom = 1.12 if flip else 1.0
        prev_media = clip.media_id


# ---------------------------------------------------------- palabras clave


def _heuristic_keywords(words: list[Word], total: float) -> list[tuple[int, Optional[str]]]:
    scored = []
    for i, w in enumerate(words):
        n = _norm(w.w)
        if not n or n in STOPWORDS:
            continue
        score = len(n) / 4
        if any(ch.isdigit() for ch in n):
            score += 3
        if n in EMOJI_MAP:
            score += 2.5
        if w.w.isupper() and len(n) > 2:
            score += 1.5
        if re.search(r"[!?¡¿]", w.w):
            score += 1
        scored.append((score, i))
    want = max(1, int(total / 3.5))
    chosen: list[int] = []
    for score, i in sorted(scored, reverse=True):
        if all(abs(words[i].s - words[j].s) >= 2.0 for j in chosen):
            chosen.append(i)
        if len(chosen) >= want:
            break
    return [(i, EMOJI_MAP.get(_norm(words[i].w))) for i in sorted(chosen)]


def _llm_keywords(words: list[Word], total: float, lang: str) -> list[tuple[int, Optional[str]]]:
    numbered = " ".join(f"{i}:{w.w}" for i, w in enumerate(words[:900]))
    want = max(1, int(total / 3.5))
    system = ("Eres editor de reels virales. Eliges las palabras que deben resaltarse en los subtítulos: "
              "conceptos clave, cifras, emociones fuertes y palabras que generan curiosidad. Nunca artículos, "
              "preposiciones ni pronombres. Responde SOLO JSON: {\"keywords\": [{\"i\": int, \"emoji\": str|null}]}. "
              "Añade emoji sólo si encaja de forma evidente (como mucho 1 de cada 2 palabras).")
    user = f"Idioma: {lang}. Elige unas {want} palabras repartidas por todo el texto (índice:palabra):\n{numbered}"
    data = llm.chat_json(system, user)
    out = []
    for item in data.get("keywords", []):
        try:
            i = int(item["i"])
        except (KeyError, TypeError, ValueError):
            continue
        if 0 <= i < len(words):
            emoji = item.get("emoji")
            out.append((i, emoji if isinstance(emoji, str) and 0 < len(emoji) <= 4 else None))
    return out


def apply_keywords(project: Project, opts: AutoEditOptions) -> int:
    words = project.captions.words
    for w in words:
        w.emph, w.emoji = False, None
    if not words:
        return 0
    total = timeline_duration(project)
    try:
        picks = _llm_keywords(words, total, opts.lang)
    except Exception:  # noqa: BLE001 - sin LLM: heurística local
        picks = []
    if not picks:
        picks = _heuristic_keywords(words, total)
    last_emoji = -10.0
    for i, emoji in picks:
        words[i].emph = True
        if opts.emojis and emoji and words[i].s - last_emoji >= 2.5:
            words[i].emoji = emoji
            last_emoji = words[i].s
    return len(picks)


# ------------------------------------------------------- zooms y efectos


def apply_effects(project: Project, opts: AutoEditOptions) -> int:
    project.effects = [e for e in project.effects if not e.auto]
    total = timeline_duration(project)
    added: list[Effect] = []
    if opts.hook_effects and total > 1:
        added.append(Effect(type="flash", start=0.0, duration=0.08, auto=True))
    if opts.punch_zooms:
        last = -10.0
        emph = [w for w in project.captions.words if w.emph]
        for idx, w in enumerate(emph):
            if w.s - last < 1.6 or w.s > total - 0.3:
                continue
            kind = "shake" if (idx == 0 and opts.hook_effects) else "punch"
            added.append(Effect(type=kind, start=round(w.s, 3), duration=round(min(0.5, max(0.25, w.e - w.s + 0.15)), 3),
                                strength=1.0, auto=True))
            last = w.s
    project.effects += added
    return len(added)


def apply_sfx(project: Project, opts: AutoEditOptions) -> int:
    project.audio = [a for a in project.audio if not a.auto]
    if not opts.sfx:
        return 0
    total = timeline_duration(project)
    lengths = clip_lengths(project)
    trans = effective_transitions(project, lengths)
    items: list[AudioItem] = []
    vol = opts.sfx_volume

    def add(name: str, t: float, v: float) -> None:
        if 0 <= t < total - 0.05:
            items.append(AudioItem(media_id=assets.sfx_media(name), role="sfx", start=round(max(0.0, t), 3),
                                   volume=round(v, 2), auto=True))

    if opts.hook_effects:
        add("boom", 0.0, vol * 0.9)
    t = 0.0
    for i, ln in enumerate(lengths[:-1]):
        t += ln - trans[i]
        if trans[i] > 0:
            add("whoosh", t - trans[i] - 0.15, vol)
    for b in project.broll:
        add("whoosh", b.start - 0.18, vol * 0.8)
    for w in project.captions.words:
        if w.emoji:
            add("pop", w.s, vol * 0.8)
        elif w.emph and any(ch.isdigit() for ch in w.w):
            add("ding", w.s, vol * 0.5)
    project.audio += items
    return len(items)


# ----------------------------------------------------------------- B-roll


def _talking_windows(project: Project, every: float, dur: float) -> list[tuple[float, float]]:
    """Momentos para B-roll sobre clips de vídeo (no sobre imágenes), alineados a palabras."""
    total = timeline_duration(project)
    lengths = clip_lengths(project)
    trans = effective_transitions(project, lengths)
    spans, t = [], 0.0
    for i, c in enumerate(project.clips):
        end = t + lengths[i] - (trans[i] if i < len(trans) else 0)
        if c.kind == "video":
            spans.append((t, end))
        t = end
    starts = [w.s for w in project.captions.words] or [x * 0.5 for x in range(int(total * 2))]
    out, cursor = [], 2.0
    while cursor < total - dur - 0.8:
        s = min(starts, key=lambda x: abs(x - cursor))
        if any(a <= s and s + dur <= b + 0.5 for a, b in spans) and (not out or s - out[-1][0] >= every * 0.6):
            out.append((round(s, 3), dur))
        cursor += every
    return out


def apply_broll(ctx: JobContext, project: Project, opts: AutoEditOptions) -> int:
    project.broll = [b for b in project.broll if not b.auto]
    if opts.broll == "none":
        return 0
    windows = _talking_windows(project, opts.broll_every, opts.broll_duration)
    if not windows:
        return 0
    used = {c.media_id for c in project.clips}
    media_ids: list[str] = []
    if opts.broll == "library":
        pool = [m.id for m in list_media() if m.kind in ("image", "video") and m.id not in used]
        media_ids = list(itertools.islice(itertools.cycle(pool), len(windows))) if pool else []
    else:
        from .ai import image

        texts = [" ".join(w.w for w in project.captions.words if s - 0.5 <= w.s <= s + 3) for s, _ in windows]
        try:
            data = llm.chat_json(
                "You write prompts for an image generator to create B-roll for a vertical social video. "
                "Reply ONLY JSON {\"prompts\": [str]} with one vivid, literal, cinematic English prompt per line "
                "of narration (no text in the image).",
                "\n".join(f"{i}. {t}" for i, t in enumerate(texts)))
            prompts = [str(p) for p in data.get("prompts", [])]
        except Exception:  # noqa: BLE001
            prompts = []
        prompts = (prompts + [f"{t}, cinematic vertical photo, dramatic lighting" for t in texts])[: len(texts)]
        model = opts.image_model or "sdxl-lightning"
        for i, prompt in enumerate(prompts):
            ctx.progress(None, f"Generando B-roll {i + 1}/{len(prompts)}")
            media_ids.append(image.generate(ctx, prompt, model, "9:16", 1, None, "cinematic")[0]["id"])
        gpu.release()
    motions = itertools.cycle(["zoom_in", "pan_right", "zoom_out", "pan_left"])
    for (start, dur), mid in zip(windows, media_ids):
        media = get_media(mid)
        if media:
            project.broll.append(BRoll(media_id=mid, start=start, duration=min(dur, media.duration or dur) if media.kind == "video" else dur,
                                       motion=next(motions), auto=True))
    return len(project.broll)


# ------------------------------------------------------------------ ritmo


def beat_sync(project: Project, tolerance: float = 0.22) -> int:
    """Desplaza los cortes entre imágenes al beat más cercano de la música."""
    if not any(a.role == "music" for a in project.audio) or len(project.clips) < 2:
        return 0
    beats = analysis.music_beats(project)
    if not beats:
        return 0
    lengths = clip_lengths(project)
    trans = effective_transitions(project, lengths)
    moved, t = 0, 0.0
    for i, clip in enumerate(project.clips[:-1]):
        boundary = t + lengths[i] - trans[i]
        nearest = min(beats, key=lambda b: abs(b - boundary))
        delta = nearest - boundary
        nxt = project.clips[i + 1]
        if (0.02 < abs(delta) <= tolerance and clip.kind == "image" and nxt.kind == "image"
                and nxt.duration - delta > 0.6 and clip.duration + delta > 0.6):
            clip.duration = round(clip.duration + delta, 3)
            nxt.duration = round(nxt.duration - delta, 3)  # el siguiente corte no se mueve
            lengths[i] += delta
            lengths[i + 1] -= delta
            moved += 1
        t += lengths[i] - trans[i]
    return moved


# -------------------------------------------------------------- orquestador


def auto_edit(ctx: JobContext, project: Project, opts: AutoEditOptions) -> dict[str, Any]:
    report: dict[str, Any] = {}
    ctx.progress(0.03, "Analizando el audio…")
    ensure_captions(ctx, project, opts)
    if opts.cut_silences:
        ctx.progress(0.25, "Quitando silencios y muletillas…")
        report["cuts"] = cut_silences(ctx, project, opts)
    if opts.jump_zoom:
        apply_jump_zoom(project)
    if opts.keywords:
        ctx.progress(0.4, "Eligiendo palabras clave…")
        report["keywords"] = apply_keywords(project, opts)
    if opts.broll != "none":
        ctx.progress(0.5, "Preparando B-roll…")
        report["broll"] = apply_broll(ctx, project, opts)
    if opts.beat_sync:
        ctx.progress(0.85, "Ajustando cortes al ritmo…")
        try:
            report["beat_cuts"] = beat_sync(project)
        except Exception as exc:  # noqa: BLE001 - un fallo de análisis no debe tumbar la edición
            report["beat_error"] = str(exc)
    report["effects"] = apply_effects(project, opts)
    ctx.progress(0.92, "Añadiendo efectos de sonido…")
    report["sfx"] = apply_sfx(project, opts)
    project.score = analysis.retention_score(project)
    report["score"] = project.score["score"]
    return report
