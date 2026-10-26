"""Producción en lote: una lista de temas → reels terminados y exportados,
uno tras otro (ideal para dejarlo trabajando de noche)."""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from pydantic import BaseModel

from . import autoreel, config, render
from .ai import llm
from .autoreel import AutoReelRequest, Scene, _Sub
from .jobs import JobCancelled, JobContext
from .project import load_project, new_id


class BatchRequest(BaseModel):
    topics: list[str]
    template: str = "auto"
    tone: str = "intrigante"
    seconds: int = 30
    platform: str = "TikTok"
    lang: str = "es"
    tts_engine: str = "kokoro"
    voice: str = "ef_dora"
    speed: float = 1.08
    visual_mode: str = "image"
    image_model: str = "sdxl-lightning"
    image_style: str = "cinematic"
    caption_style: Optional[str] = None
    transition: Optional[str] = None
    music_media_id: Optional[str] = None
    music_volume: float = 0.16
    auto_edit: bool = True
    export: bool = True
    export_preset: str = "tiktok"


def _file(batch_id: str):
    return config.DATA_DIR / "batches" / f"{batch_id}.json"


def list_batches() -> list[dict]:
    folder = config.DATA_DIR / "batches"
    out = []
    for f in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20] if folder.is_dir() else []:
        try:
            out.append(json.loads(f.read_text("utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


def run(ctx: JobContext, req: BatchRequest) -> dict[str, Any]:
    topics = [t.strip() for t in req.topics if t.strip()][:50]
    if not topics:
        raise ValueError("Escribe al menos un tema")
    tpl = llm.TEMPLATES.get(req.template, llm.TEMPLATES["auto"])
    state: dict[str, Any] = {"id": new_id(), "created": time.time(), "template": req.template, "items": []}
    path = _file(state["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(topics)
    for i, topic in enumerate(topics):
        item: dict[str, Any] = {"topic": topic, "status": "running"}
        state["items"].append(item)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
        base, span = i / n, 1 / n
        try:
            ctx.progress(base, f"[{i + 1}/{n}] Guion: {topic[:40]}")
            script = llm.write_script(topic, req.tone, req.seconds, req.platform, req.lang, template=req.template)
            areq = AutoReelRequest(
                title=script["title"], hook=script.get("hook", ""),
                scenes=[Scene(**s) for s in script["scenes"]],
                tts_engine=req.tts_engine, voice=req.voice, speed=req.speed, lang=req.lang,
                visual_mode=req.visual_mode, image_model=req.image_model, image_style=req.image_style,
                caption_style=req.caption_style or tpl.get("caption_style") or config.load_settings()["caption_style"],
                transition=req.transition or tpl.get("transition") or "smoothup",
                music_media_id=req.music_media_id, music_volume=req.music_volume, auto_edit=req.auto_edit,
                extra={"caption": script.get("caption", ""), "hashtags": script.get("hashtags", []), "batch": state["id"]},
            )
            res = autoreel.build(_Sub(ctx, base + span * 0.02, base + span * (0.8 if req.export else 1.0)), areq)
            item.update(project_id=res["project_id"], title=script["title"], caption=script.get("caption", ""),
                        hashtags=script.get("hashtags", []))
            if req.export:
                project = load_project(res["project_id"])
                preset = render.PRESETS.get(req.export_preset, render.PRESETS["tiktok"])
                opts = render.ExportOptions(**{k: preset[k] for k in ("resolution", "fps", "codec", "quality")},
                                            thumbnail=True, subtitles_file=True, filename=script["title"])
                sub = _Sub(ctx, base + span * 0.8, base + span)
                out = render.render_project(project, opts, render.export_filename(project, opts),
                                            lambda p, m: sub.progress(p, f"[{i + 1}/{n}] {m}"), ctx.track)
                item["export"] = out["path"]
            item["status"] = "done"
        except JobCancelled:
            item["status"] = "cancelled"
            path.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
            raise
        except Exception as exc:  # noqa: BLE001 - un tema fallido no detiene el lote
            item.update(status="error", error=f"{type(exc).__name__}: {exc}")
        path.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
    state["finished"] = time.time()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
    return state
