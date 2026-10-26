"""Flujo "Reel automático": guion → voz por escena → visuales → subtítulos →
proyecto editable en la línea de tiempo."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from . import captions, ffmpeg, gpu
from .ai import google, image, stt, tts, video
from .jobs import JobContext
from .project import (
    AudioItem,
    Captions,
    Clip,
    Project,
    TextOverlay,
    Transition,
    Word,
    get_media,
    media_output_path,
    register_media,
    save_project,
)


class Scene(BaseModel):
    narration: str
    visual: str = ""
    media_id: Optional[str] = None


class AutoReelRequest(BaseModel):
    title: str = "Reel automático"
    hook: str = ""
    scenes: list[Scene]
    tts_engine: str = "kokoro"
    voice: str = "ef_dora"
    speed: float = 1.05
    lang: str = "es"
    visual_mode: str = "image"  # image | video | google-image | google-video | library
    image_model: str = "sdxl-lightning"
    image_style: str = "cinematic"
    video_model: str = "wan2.1-1.3b"
    caption_style: str = "viral"
    transition: str = "smoothup"
    transition_duration: float = 0.35
    music_media_id: Optional[str] = None
    music_volume: float = 0.16
    hook_overlay: bool = True
    align_with_whisper: bool = True
    whisper_model: str = "large-v3-turbo"
    width: int = 1080
    height: int = 1920
    fps: int = 30
    extra: dict[str, Any] = Field(default_factory=dict)


MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_left", "pan_up", "zoom_in", "pan_down"]


class _Sub(JobContext):
    """Contexto que mapea el progreso de un subpaso a un tramo del total."""

    def __init__(self, parent: JobContext, start: float, end: float):
        super().__init__(parent.job)
        self.start, self.end = start, end

    def progress(self, value: float | None = None, message: str | None = None) -> None:
        mapped = None if value is None else self.start + (self.end - self.start) * max(0.0, min(1.0, value))
        super().progress(mapped, message)


def _concat_voice(paths: list[str], gap: float) -> tuple[Path, list[float]]:
    durations = []
    args = [ffmpeg.binary(), "-hide_banner", "-y"]
    parts = []
    for i, p in enumerate(paths):
        d = (ffmpeg.probe(p).get("duration") or 0) + gap
        durations.append(d)
        args += ["-i", p]
        parts.append(f"[{i}:a]aresample=48000,aformat=channel_layouts=mono,apad=pad_dur={gap}[p{i}]")
    graph = ";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(paths))) + f"concat=n={len(paths)}:v=0:a=1[out]"
    out = media_output_path(".wav", "narracion")
    ffmpeg.run([*args, "-filter_complex", graph, "-map", "[out]", str(out)])
    return out, durations


def build(ctx: JobContext, req: AutoReelRequest) -> dict:
    scenes = [s for s in req.scenes if s.narration.strip()]
    if not scenes:
        raise ValueError("El guion no tiene escenas")
    n = len(scenes)

    # 1) Voz por escena -------------------------------------------------------
    voice_items, edge_words = [], []
    for i, sc in enumerate(scenes):
        sub = _Sub(ctx, 0.02 + 0.18 * i / n, 0.02 + 0.18 * (i + 1) / n)
        sub.progress(0, f"Voz escena {i + 1}/{n}")
        item = tts.synthesize(sub, sc.narration, req.tts_engine, req.voice, req.speed, name=f"Escena {i + 1}", lang=req.lang)
        voice_items.append(item)
        edge_words.append(item["meta"].get("words") or [])
    gap = 0.12
    narr_path, durations = _concat_voice([v["path"] for v in voice_items], gap)
    narration = register_media(narr_path, source="tts", name=f"Narración · {req.title[:30]}",
                               meta={"text": " ".join(s.narration for s in scenes)})
    narr_path.unlink(missing_ok=True)

    # 2) Visuales -------------------------------------------------------------
    media_ids: list[str] = []
    for i, sc in enumerate(scenes):
        sub = _Sub(ctx, 0.2 + 0.55 * i / n, 0.2 + 0.55 * (i + 1) / n)
        if sc.media_id and get_media(sc.media_id):
            media_ids.append(sc.media_id)
            continue
        prompt = sc.visual or sc.narration
        sub.progress(0, f"Visual escena {i + 1}/{n}")
        if req.visual_mode == "video":
            media_ids.append(video.generate(sub, prompt, req.video_model, seconds=min(5.0, durations[i]))["id"])
        elif req.visual_mode == "google-video":
            media_ids.append(google.generate_video(sub, prompt)["id"])
        elif req.visual_mode == "google-image":
            media_ids.append(google.generate_image(sub, prompt)[0]["id"])
        elif req.visual_mode == "image":
            media_ids.append(image.generate(sub, prompt, req.image_model, "9:16", 1, None, req.image_style)[0]["id"])
        else:
            raise ValueError(f"Escena {i + 1} sin medio asignado")
    gpu.release()

    # 3) Palabras con tiempos para subtítulos ---------------------------------
    words: list[dict] = []
    if req.tts_engine == "edge" and all(edge_words):
        offset = 0.0
        for d, ws in zip(durations, edge_words):
            words += [{"w": w["w"], "s": round(w["s"] + offset, 3), "e": round(w["e"] + offset, 3)} for w in ws]
            offset += d
    elif req.align_with_whisper and gpu.has_module("faster_whisper"):
        sub = _Sub(ctx, 0.76, 0.92)
        try:
            res = stt.transcribe_file(sub, narration.path, req.whisper_model, req.lang,
                                      prompt=" ".join(s.narration for s in scenes)[:800])
            words = res["words"]
        except Exception as exc:  # noqa: BLE001
            ctx.progress(None, f"Whisper no disponible ({exc}); tiempos estimados")
    if not words:
        offset = 0.0
        for sc, d in zip(scenes, durations):
            words += [{"w": w["w"], "s": w["s"] + offset, "e": w["e"] + offset}
                      for w in captions.words_from_text(sc.narration, d - gap)]
            offset += d
    gpu.release()

    # 4) Proyecto -------------------------------------------------------------
    ctx.progress(0.94, "Montando la línea de tiempo…")
    t = req.transition_duration if req.transition != "none" else 0.0
    clips = []
    motions = itertools.cycle(MOTIONS)
    for i, (mid, d) in enumerate(zip(media_ids, durations)):
        media = get_media(mid)
        # Cada transición solapa clips: se compensa para que imagen y voz sigan sincronizadas.
        length = d + (t if i < n - 1 else 0.3)
        clip = Clip(media_id=mid, kind="image" if media and media.kind == "image" else "video",
                    duration=length, motion=next(motions), fit="cover",
                    transition=Transition(type=req.transition if i < n - 1 else "none", duration=t))
        if clip.kind == "video" and media:
            src_len = media.duration or length
            clip.src_out = min(src_len, length)
            if src_len < length:  # vídeo corto: se ralentiza un poco para cubrir la escena
                clip.speed = max(0.5, src_len / length)
                clip.src_out = src_len
        clips.append(clip)
    audio = [AudioItem(media_id=narration.id, role="voice", volume=1.0)]
    if req.music_media_id and get_media(req.music_media_id):
        audio.append(AudioItem(media_id=req.music_media_id, role="music", volume=req.music_volume, loop=True,
                               fade_in=0.5, fade_out=1.5))
    style = captions.STYLES.get(req.caption_style, captions.STYLES["viral"])
    texts = []
    if req.hook_overlay and req.hook:
        texts.append(TextOverlay(text=req.hook.upper() if len(req.hook) < 40 else req.hook, start=0.0,
                                 end=min(2.8, durations[0]), style="title", position=0.2))
    project = Project(
        name=req.title,
        clips=clips,
        audio=audio,
        captions=Captions(words=[Word(**w) for w in words], style=req.caption_style,
                          max_words=style["max_words"], uppercase=style["uppercase"]),
        texts=texts,
        script={"title": req.title, "hook": req.hook, "scenes": [s.model_dump() for s in scenes], **req.extra},
    )
    project.format.width, project.format.height, project.format.fps = req.width, req.height, req.fps
    save_project(project)
    return {"project_id": project.id, "duration": round(sum(durations), 2)}
