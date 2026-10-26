"""Modelo de proyecto (línea de tiempo) y biblioteca de medios."""

from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import config, ffmpeg

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus"}

MediaKind = Literal["video", "image", "audio"]


def new_id() -> str:
    return uuid.uuid4().hex[:10]


class Transition(BaseModel):
    type: str = "none"
    duration: float = 0.5


class Clip(BaseModel):
    id: str = Field(default_factory=new_id)
    media_id: str
    kind: Literal["video", "image"] = "image"
    src_in: float = 0.0
    src_out: Optional[float] = None
    duration: float = 3.0  # para imágenes; en vídeos se deriva de in/out/speed
    speed: float = 1.0
    volume: float = 1.0
    motion: str = "zoom_in"  # none|zoom_in|zoom_out|pan_left|pan_right|pan_up|pan_down
    fit: str = "cover"  # cover | blur | contain
    filter: str = "none"
    transition: Transition = Field(default_factory=Transition)

    def length(self, media_duration: float | None = None) -> float:
        if self.kind == "image":
            return max(0.2, self.duration)
        end = self.src_out if self.src_out is not None else (media_duration or self.duration)
        return max(0.1, (end - self.src_in) / max(0.1, self.speed))


class AudioItem(BaseModel):
    id: str = Field(default_factory=new_id)
    media_id: str
    role: Literal["voice", "music", "sfx"] = "voice"
    start: float = 0.0
    src_in: float = 0.0
    src_out: Optional[float] = None
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    loop: bool = False


class Word(BaseModel):
    w: str
    s: float
    e: float


class Captions(BaseModel):
    enabled: bool = True
    style: str = "viral"
    words: list[Word] = Field(default_factory=list)
    max_words: int = 3
    uppercase: bool = True
    position: float = 0.68  # fracción vertical (0 arriba, 1 abajo)
    scale: float = 1.0
    source_media_id: Optional[str] = None


class TextOverlay(BaseModel):
    id: str = Field(default_factory=new_id)
    text: str
    start: float = 0.0
    end: float = 3.0
    style: str = "title"  # title | label | outline
    position: float = 0.18
    scale: float = 1.0


class Format(BaseModel):
    width: int = 1080
    height: int = 1920
    fps: int = 30


class Project(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str = "Proyecto sin título"
    created: float = Field(default_factory=time.time)
    updated: float = Field(default_factory=time.time)
    format: Format = Field(default_factory=Format)
    clips: list[Clip] = Field(default_factory=list)
    audio: list[AudioItem] = Field(default_factory=list)
    captions: Captions = Field(default_factory=Captions)
    texts: list[TextOverlay] = Field(default_factory=list)
    ducking: bool = True
    loudnorm: bool = True
    script: Optional[dict] = None


class MediaItem(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    kind: MediaKind
    path: str
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    has_audio: bool = False
    thumb: Optional[str] = None
    source: str = "import"  # import | tts | image | video | music | google | flow | export
    meta: dict = Field(default_factory=dict)
    created: float = Field(default_factory=time.time)


_lock = threading.RLock()


# --------------------------------------------------------------------------- media


def _library_index() -> Path:
    return config.LIBRARY_DIR / "library.json"


def list_media() -> list[MediaItem]:
    with _lock:
        idx = _library_index()
        if not idx.exists():
            return []
        try:
            raw = json.loads(idx.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        items = []
        for entry in raw:
            try:
                items.append(MediaItem.model_validate(entry))
            except Exception:  # noqa: BLE001 - entrada corrupta: se omite
                continue
        return items


def _save_media(items: list[MediaItem]) -> None:
    idx = _library_index()
    idx.parent.mkdir(parents=True, exist_ok=True)
    tmp = idx.with_suffix(".tmp")
    tmp.write_text(json.dumps([m.model_dump() for m in items], ensure_ascii=False, indent=1), "utf-8")
    tmp.replace(idx)


def get_media(media_id: str) -> MediaItem | None:
    return next((m for m in list_media() if m.id == media_id), None)


def kind_for(path: Path) -> MediaKind | None:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    return None


def register_media(
    path: str | Path,
    source: str = "import",
    name: str | None = None,
    copy: bool = True,
    meta: dict | None = None,
) -> MediaItem:
    """Añade un archivo a la biblioteca (copiándolo a la carpeta de datos)."""
    src = Path(path)
    if not src.is_file():
        raise FileNotFoundError(str(src))
    kind = kind_for(src)
    if not kind:
        raise ValueError(f"Formato no compatible: {src.suffix}")
    media_id = new_id()
    folder = config.LIBRARY_DIR / media_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / src.name if copy else src
    if copy and src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    item = MediaItem(id=media_id, name=name or src.stem, kind=kind, path=str(dest), source=source, meta=meta or {})
    try:
        info = ffmpeg.probe(dest)
        item.duration = info.get("duration") if kind != "image" else None
        item.width = info.get("width")
        item.height = info.get("height")
        item.has_audio = bool(info.get("has_audio"))
        if kind in ("video", "image"):
            thumb = folder / "thumb.jpg"
            ffmpeg.thumbnail(dest, thumb, at=min(0.5, (item.duration or 1) / 2) if kind == "video" else 0)
            item.thumb = str(thumb)
        elif kind == "audio":
            wave = folder / "wave.png"
            ffmpeg.waveform(dest, wave)
            item.thumb = str(wave)
    except ffmpeg.FFmpegError:
        pass
    with _lock:
        items = list_media()
        items.insert(0, item)
        _save_media(items)
    return item


def update_media(media_id: str, **fields) -> MediaItem | None:
    with _lock:
        items = list_media()
        for i, m in enumerate(items):
            if m.id == media_id:
                items[i] = m.model_copy(update=fields)
                _save_media(items)
                return items[i]
    return None


def delete_media(media_id: str) -> bool:
    with _lock:
        items = list_media()
        keep = [m for m in items if m.id != media_id]
        if len(keep) == len(items):
            return False
        _save_media(keep)
    folder = config.LIBRARY_DIR / media_id
    if folder.is_dir() and folder.parent == config.LIBRARY_DIR:
        shutil.rmtree(folder, ignore_errors=True)
    return True


def media_output_path(suffix: str, stem: str = "output") -> Path:
    """Ruta temporal en caché para que un generador escriba su resultado."""
    folder = config.CACHE_DIR / "gen"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{stem}-{new_id()}{suffix}"


# ------------------------------------------------------------------------ projects


def _project_file(project_id: str) -> Path:
    safe = "".join(c for c in project_id if c.isalnum() or c in "-_")
    return config.PROJECTS_DIR / safe / "project.json"


def list_projects() -> list[dict]:
    out = []
    for f in config.PROJECTS_DIR.glob("*/project.json"):
        try:
            p = Project.model_validate_json(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        thumb = None
        for c in p.clips:
            m = get_media(c.media_id)
            if m and m.thumb:
                thumb = m.thumb
                break
        out.append(
            {
                "id": p.id,
                "name": p.name,
                "updated": p.updated,
                "clips": len(p.clips),
                "duration": round(timeline_duration(p), 2),
                "thumb": thumb,
            }
        )
    return sorted(out, key=lambda x: x["updated"], reverse=True)


def load_project(project_id: str) -> Project | None:
    f = _project_file(project_id)
    if not f.exists():
        return None
    return Project.model_validate_json(f.read_text("utf-8"))


def save_project(project: Project) -> Project:
    with _lock:
        project.updated = time.time()
        f = _project_file(project.id)
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.exists():
            shutil.copy2(f, f.with_suffix(".json.bak"))
        tmp = f.with_suffix(".tmp")
        tmp.write_text(project.model_dump_json(indent=1), "utf-8")
        tmp.replace(f)
    return project


def delete_project(project_id: str) -> bool:
    f = _project_file(project_id)
    if not f.exists():
        return False
    shutil.rmtree(f.parent, ignore_errors=True)
    return True


def clip_lengths(project: Project) -> list[float]:
    out = []
    for c in project.clips:
        m = get_media(c.media_id)
        out.append(c.length(m.duration if m else None))
    return out


def effective_transitions(project: Project, lengths: list[float] | None = None) -> list[float]:
    """Duración real de cada transición (0 = corte), limitada por los clips vecinos."""
    lengths = lengths or clip_lengths(project)
    out = []
    for i, c in enumerate(project.clips[:-1]):
        t = c.transition
        if t.type == "none" or t.duration <= 0:
            out.append(0.0)
            continue
        limit = min(lengths[i], lengths[i + 1]) * 0.45
        out.append(round(max(0.05, min(t.duration, limit)), 3))
    return out


def timeline_duration(project: Project) -> float:
    lengths = clip_lengths(project)
    if not lengths:
        audio_end = 0.0
        for a in project.audio:
            m = get_media(a.media_id)
            end = (a.src_out if a.src_out is not None else (m.duration if m else 0) or 0) - a.src_in
            audio_end = max(audio_end, a.start + max(0.0, end))
        return audio_end
    return sum(lengths) - sum(effective_transitions(project, lengths))
