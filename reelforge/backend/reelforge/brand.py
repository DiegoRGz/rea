"""Kit de marca aplicado al crear proyectos: intro, outro y llamada a la acción.
(El logo y el @usuario se añaden al exportar, en render.py.)"""

from __future__ import annotations

from . import config
from .project import Clip, Project, TextOverlay, get_media, timeline_duration


def _shift(project: Project, dt: float) -> None:
    for a in project.audio:
        a.start = round(a.start + dt, 3)
    for w in project.captions.words:
        w.s, w.e = round(w.s + dt, 3), round(w.e + dt, 3)
    for t in project.texts:
        t.start, t.end = round(t.start + dt, 3), round(t.end + dt, 3)
    for e in project.effects:
        e.start = round(e.start + dt, 3)
    for b in project.broll:
        b.start = round(b.start + dt, 3)


def _bookend_clip(media_id: str) -> Clip | None:
    media = get_media(media_id) if media_id else None
    if not media or media.kind == "audio":
        return None
    if media.kind == "image":
        return Clip(media_id=media.id, kind="image", duration=1.5, motion="zoom_in")
    return Clip(media_id=media.id, kind="video", src_in=0, src_out=media.duration, fit="blur")


def apply_brand(project: Project) -> Project:
    """Añade intro/outro y el texto de llamada a la acción según Ajustes → Marca (idempotente)."""
    s = config.load_settings()
    if project.script and project.script.get("brand_applied"):
        return project
    intro = _bookend_clip(s.get("brand_intro_media_id") or "")
    if intro and project.clips:
        project.clips.insert(0, intro)
        _shift(project, intro.length(get_media(intro.media_id).duration))
    outro = _bookend_clip(s.get("brand_outro_media_id") or "")
    if outro and project.clips:
        project.clips.append(outro)
    cta = (s.get("brand_cta") or "").strip()
    if s.get("brand_cta_enabled") and cta:
        total = timeline_duration(project)
        end_ref = total - (outro.length(get_media(outro.media_id).duration) if outro else 0)
        project.texts.append(TextOverlay(text=cta, start=round(max(0.0, end_ref - 2.6), 3), end=round(end_ref, 3),
                                         style="label", position=0.42))
    project.script = {**(project.script or {}), "brand_applied": True}
    return project
