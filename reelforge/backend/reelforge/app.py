"""API HTTP local (127.0.0.1) que usa la interfaz de ReelForge Studio."""

from __future__ import annotations

import os
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import (analysis, assets, autoreel, batch, brand, captions, catalog, clipper, config, ffmpeg, gpu, project,
               render, retention, updater)
from .ai import google, hub, image, llm, music, stt, tts, video
from .jobs import jobs

TOKEN = os.environ.get("REELFORGE_TOKEN") or secrets.token_urlsafe(18)

app = FastAPI(title=config.APP_NAME, version=config.VERSION, docs_url=None, redoc_url=None)


@app.middleware("http")
async def auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") or path.startswith("/files/"):
        token = request.headers.get("x-reelforge-token") or request.query_params.get("t")
        if not token or not secrets.compare_digest(token, TOKEN):
            return JSONResponse({"detail": "Token no válido"}, status_code=401)
    return await call_next(request)


def _job(kind: str, title: str, fn, lane: str = "gpu") -> dict:
    return jobs.submit(kind, title, fn, lane).public()


def _media_or_404(media_id: str) -> project.MediaItem:
    m = project.get_media(media_id)
    if not m:
        raise HTTPException(404, "Medio no encontrado")
    return m


def _project_or_404(project_id: str) -> project.Project:
    p = project.load_project(project_id)
    if not p:
        raise HTTPException(404, "Proyecto no encontrado")
    return p


# ------------------------------------------------------------------ sistema


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "app": config.APP_NAME,
        "version": config.VERSION,
        "ffmpeg": ffmpeg.capabilities(),
        "modules": {m: gpu.has_module(m) for m in ("torch", "diffusers", "transformers", "faster_whisper",
                                                     "kokoro", "edge_tts", "google.genai", "TTS")},
        "data_dir": str(config.DATA_DIR),
    }


@app.get("/api/system")
def system() -> dict:
    return {**gpu.system_info(), "torch": gpu.torch_info(), "recommend": gpu.recommendations()}


@app.get("/api/settings")
def get_settings() -> dict:
    return config.public_settings()


@app.post("/api/settings")
def set_settings(patch: dict[str, Any]) -> dict:
    config.save_settings(patch)
    if "ffmpeg_path" in patch:
        ffmpeg.reset_cache()
    return config.public_settings()


@app.get("/api/meta")
def meta() -> dict:
    return {
        "transitions": render.TRANSITIONS,
        "motions": render.MOTIONS,
        "filters": {k: v[0] for k, v in render.COLOR_FILTERS.items()},
        "caption_styles": captions.STYLES,
        "overlay_styles": list(captions.OVERLAY_STYLES),
        "export_presets": render.PRESETS,
        "resolutions": list(render.RESOLUTIONS),
        "qualities": {"draft": "Borrador", "standard": "Estándar", "high": "Alta", "max": "Máxima"},
        "tts": tts.catalog(),
        "image": {"models": {**image.MODELS, **hub.models("image")}, "aspects": list(image.ASPECTS),
                  "styles": list(image.STYLE_PRESETS)},
        "video": {"models": {**video.MODELS, **{k: {**v, "mode": "t2v", "i2v_optional": bool(v.get("i2v"))}
                                                for k, v in hub.models("video").items()}}},
        "music": {"models": music.MODELS, "license": music.LICENSE},
        "whisper": stt.MODELS,
        "fonts": catalog.fonts_status(),
        "templates": {k: {kk: vv for kk, vv in v.items() if kk != "instructions"} for k, v in llm.TEMPLATES.items()},
        "sfx": {k: v[0] for k, v in assets.SFX.items()},
    }


# ------------------------------------------------------------------- medios


class ImportBody(BaseModel):
    paths: list[str]
    source: str = "import"


@app.get("/api/media")
def media_list(kind: Optional[str] = None) -> list[dict]:
    items = project.list_media()
    if kind:
        items = [m for m in items if m.kind == kind]
    return [m.model_dump() for m in items]


@app.post("/api/media/import")
def media_import(body: ImportBody) -> list[dict]:
    out, errors = [], []
    for p in body.paths:
        try:
            out.append(project.register_media(p, source=body.source).model_dump())
        except (OSError, ValueError) as exc:
            errors.append(f"{Path(p).name}: {exc}")
    if errors and not out:
        raise HTTPException(400, "; ".join(errors))
    return out


@app.post("/api/media/upload")
async def media_upload(files: list[UploadFile] = File(...)) -> list[dict]:
    out = []
    tmp_dir = config.CACHE_DIR / "uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for f in files:
        name = Path(f.filename or "archivo").name
        if not project.kind_for(Path(name)):
            raise HTTPException(400, f"Formato no compatible: {name}")
        tmp = tmp_dir / f"{project.new_id()}-{name}"
        with tmp.open("wb") as fh:
            shutil.copyfileobj(f.file, fh)
        dest = tmp.with_name(name) if not tmp.with_name(name).exists() else tmp
        tmp.replace(dest)
        out.append(project.register_media(dest).model_dump())
        dest.unlink(missing_ok=True)
    return out


class MediaPatch(BaseModel):
    name: Optional[str] = None


@app.patch("/api/media/{media_id}")
def media_patch(media_id: str, body: MediaPatch) -> dict:
    _media_or_404(media_id)
    item = project.update_media(media_id, **body.model_dump(exclude_none=True))
    return item.model_dump() if item else {}


@app.delete("/api/media/{media_id}")
def media_delete(media_id: str) -> dict:
    return {"deleted": project.delete_media(media_id)}


@app.get("/files/media/{media_id}")
def media_file(media_id: str):
    m = _media_or_404(media_id)
    return FileResponse(m.path)


@app.get("/files/thumb/{media_id}")
def media_thumb(media_id: str):
    m = _media_or_404(media_id)
    if not m.thumb or not Path(m.thumb).is_file():
        raise HTTPException(404, "Sin miniatura")
    return FileResponse(m.thumb)


@app.get("/files/fonts/{name}")
def font_file(name: str):
    path = config.FONTS_DIR / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "Fuente no instalada")
    return FileResponse(path)


# ---------------------------------------------------------------- proyectos


class NewProject(BaseModel):
    name: str = "Nuevo reel"
    aspect: str = "9:16"
    fps: int = 30


ASPECT_SIZES = {"9:16": (1080, 1920), "1:1": (1080, 1080), "4:5": (1080, 1350), "16:9": (1920, 1080)}


@app.get("/api/projects")
def projects() -> list[dict]:
    return project.list_projects()


@app.post("/api/projects")
def project_create(body: NewProject) -> dict:
    p = project.Project(name=body.name)
    p.format.width, p.format.height = ASPECT_SIZES.get(body.aspect, (1080, 1920))
    p.format.fps = body.fps
    p.captions.style = config.load_settings().get("caption_style", "viral")
    return project.save_project(p).model_dump()


@app.get("/api/projects/{project_id}")
def project_get(project_id: str) -> dict:
    p = _project_or_404(project_id)
    return {**p.model_dump(), "duration": project.timeline_duration(p),
            "transitions_effective": project.effective_transitions(p)}


@app.put("/api/projects/{project_id}")
def project_put(project_id: str, body: project.Project) -> dict:
    if body.id != project_id:
        raise HTTPException(400, "Id inconsistente")
    p = project.save_project(body)
    return {"updated": p.updated, "duration": project.timeline_duration(p),
            "transitions_effective": project.effective_transitions(p)}


@app.post("/api/projects/{project_id}/duplicate")
def project_duplicate(project_id: str) -> dict:
    p = _project_or_404(project_id)
    copy = p.model_copy(update={"id": project.new_id(), "name": f"{p.name} (copia)", "created": time.time()})
    return project.save_project(copy).model_dump()


@app.delete("/api/projects/{project_id}")
def project_delete(project_id: str) -> dict:
    return {"deleted": project.delete_project(project_id)}


@app.get("/api/projects/{project_id}/subtitles.{fmt}")
def project_subtitles(project_id: str, fmt: str):
    p = _project_or_404(project_id)
    words = [w.model_dump() for w in p.captions.words]
    if fmt == "srt":
        return PlainTextResponse(captions.build_srt(words))
    if fmt == "vtt":
        return PlainTextResponse(captions.build_srt(words, vtt=True), media_type="text/vtt")
    if fmt == "ass":
        return PlainTextResponse(captions.build_ass(p.format.width, p.format.height, words, p.captions.style,
                                                    p.captions.max_words, p.captions.uppercase, p.captions.position,
                                                    p.captions.scale, [t.model_dump() for t in p.texts]))
    raise HTTPException(400, "Formato no válido")


class ExportBody(render.ExportOptions):
    preset: Optional[str] = None


@app.post("/api/projects/{project_id}/export")
def project_export(project_id: str, body: ExportBody) -> dict:
    p = _project_or_404(project_id)
    opts = render.ExportOptions(**body.model_dump(exclude={"preset"}))
    if body.preset in render.PRESETS:
        pr = render.PRESETS[body.preset]
        opts = opts.model_copy(update={k: pr[k] for k in ("resolution", "fps", "codec", "quality")})
    out = render.export_filename(p, opts)

    def run(ctx):
        return render.render_project(p, opts, out, ctx.progress, ctx.track)

    return _job("export", f"Exportando «{p.name}»", run, lane="render")


@app.post("/api/projects/{project_id}/preview")
def project_preview(project_id: str) -> dict:
    p = _project_or_404(project_id)
    out = config.CACHE_DIR / "previews" / f"{p.id}.mp4"
    opts = render.ExportOptions(resolution="540p", quality="draft", hardware=True)

    def run(ctx):
        tmp = out.with_name(f"{p.id}-{project.new_id()}.mp4")
        res = render.render_project(p, opts, tmp, ctx.progress, ctx.track)
        tmp.replace(out)
        return {**res, "path": str(out), "url": f"/files/preview/{p.id}?v={int(time.time())}"}

    return _job("preview", f"Vista previa «{p.name}»", run, lane="render")


@app.get("/files/preview/{project_id}")
def preview_file(project_id: str):
    path = config.CACHE_DIR / "previews" / f"{Path(project_id).name}.mp4"
    if not path.is_file():
        raise HTTPException(404, "Sin vista previa")
    return FileResponse(path)


@app.get("/api/exports")
def exports() -> list[dict]:
    out = []
    for f in sorted(config.EXPORTS_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix.lower() in (".mp4", ".mp3", ".wav"):
            out.append({"name": f.name, "path": str(f), "bytes": f.stat().st_size, "modified": f.stat().st_mtime})
    return out[:100]


@app.get("/files/export/{name}")
def export_file(name: str):
    path = config.EXPORTS_DIR / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "No existe")
    return FileResponse(path)


# ---------------------------------------------------------- edición viral


@app.post("/api/projects/{project_id}/auto-edit")
def project_auto_edit(project_id: str, opts: retention.AutoEditOptions) -> dict:
    _project_or_404(project_id)

    def run(ctx):
        p = project.load_project(project_id)
        report = retention.auto_edit(ctx, p, opts)
        project.save_project(p)
        return report

    return _job("auto-edit", "Edición viral automática", run)


@app.get("/api/projects/{project_id}/score")
def project_score(project_id: str) -> dict:
    p = _project_or_404(project_id)
    p.score = analysis.retention_score(p)
    project.save_project(p)
    return p.score


@app.post("/api/projects/{project_id}/brand")
def project_brand(project_id: str) -> dict:
    p = _project_or_404(project_id)
    brand.apply_brand(p)
    project.save_project(p)
    return {"ok": True}


@app.post("/api/sfx/{name}")
def sfx_media(name: str) -> dict:
    if name not in assets.SFX:
        raise HTTPException(404, "Efecto desconocido")
    return project.get_media(assets.sfx_media(name)).model_dump()


@app.post("/api/clipper")
def clipper_run(b: clipper.ClipperRequest) -> dict:
    _media_or_404(b.media_id)
    return _job("clipper", "Clips virales desde vídeo largo", lambda ctx: clipper.run(ctx, b))


@app.get("/api/clipper/{media_id}")
def clipper_results(media_id: str) -> list[dict]:
    return clipper.load_results(media_id)


@app.post("/api/batch")
def batch_run(b: batch.BatchRequest) -> dict:
    n = len([t for t in b.topics if t.strip()])
    return _job("batch", f"Lote de {n} reels", lambda ctx: batch.run(ctx, b))


@app.get("/api/batches")
def batches() -> list[dict]:
    return batch.list_batches()


# ------------------------------------------------------------------- trabajos


@app.get("/api/jobs")
def job_list() -> list[dict]:
    return jobs.list()


@app.get("/api/jobs/{job_id}")
def job_get(job_id: str) -> dict:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Trabajo no encontrado")
    return job.public()


@app.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict:
    return {"cancelled": jobs.cancel(job_id)}


# ------------------------------------------------------------------------ IA


class TTSBody(BaseModel):
    text: str
    engine: str = "kokoro"
    voice: str = "ef_dora"
    speed: float = 1.0
    pitch: int = 0
    lang: str = "es"
    name: Optional[str] = None


@app.post("/api/tts")
def tts_run(b: TTSBody) -> dict:
    lane = "io" if b.engine == "edge" else "gpu"
    return _job("tts", "Generando voz", lambda ctx: tts.synthesize(ctx, b.text, b.engine, b.voice, b.speed, b.pitch,
                                                                   b.name, b.lang), lane)


class CloneBody(BaseModel):
    media_id: str
    name: str


@app.post("/api/tts/clone-sample")
def tts_clone(b: CloneBody) -> dict:
    m = _media_or_404(b.media_id)
    return {"path": tts.save_clone_sample(m.path, b.name)}


class TranscribeBody(BaseModel):
    media_id: str
    model: str = "large-v3-turbo"
    language: Optional[str] = "es"
    prompt: Optional[str] = None


@app.post("/api/transcribe")
def transcribe(b: TranscribeBody) -> dict:
    _media_or_404(b.media_id)
    return _job("transcribe", "Transcribiendo", lambda ctx: stt.transcribe_media(ctx, b.media_id, b.model,
                                                                                  b.language, b.prompt))


class ImageBody(BaseModel):
    prompt: str
    model: str = "flux2-klein"
    aspect: str = "9:16"
    count: int = 1
    seed: Optional[int] = None
    style: str = "none"
    negative: str = ""
    steps: Optional[int] = None
    guidance: Optional[float] = None


@app.post("/api/image")
def image_run(b: ImageBody) -> dict:
    return _job("image", f"Imagen: {b.prompt[:40]}", lambda ctx: image.generate(ctx, b.prompt, b.model, b.aspect,
                                                                                b.count, b.seed, b.style, b.negative,
                                                                                b.steps, b.guidance))


class VideoBody(BaseModel):
    prompt: str
    model: str = "wan2.1-1.3b"
    seconds: float = 3.0
    image_media_id: Optional[str] = None
    steps: Optional[int] = None
    seed: Optional[int] = None
    landscape: bool = False


@app.post("/api/video")
def video_run(b: VideoBody) -> dict:
    return _job("video", f"Vídeo: {b.prompt[:40]}", lambda ctx: video.generate(ctx, b.prompt, b.model, b.seconds,
                                                                               b.image_media_id, b.steps, b.seed,
                                                                               b.landscape))


class MusicBody(BaseModel):
    prompt: str
    seconds: float = 20
    model: str = "musicgen-small"


@app.post("/api/music")
def music_run(b: MusicBody) -> dict:
    return _job("music", f"Música: {b.prompt[:40]}", lambda ctx: music.generate(ctx, b.prompt, b.seconds, b.model))


class ScriptBody(BaseModel):
    topic: str
    tone: str = "intrigante"
    seconds: int = 30
    platform: str = "TikTok"
    lang: str = "es"
    provider: Optional[str] = None
    extra: str = ""
    template: str = "auto"


@app.post("/api/script")
def script(b: ScriptBody) -> dict:
    return _job("script", "Escribiendo guion", lambda ctx: llm.write_script(b.topic, b.tone, b.seconds, b.platform,
                                                                            b.lang, b.provider, b.extra,
                                                                            b.template), "io")


class TextBody(BaseModel):
    text: str


@app.post("/api/prompt/improve")
def prompt_improve(b: TextBody) -> dict:
    return _job("prompt", "Mejorando prompt", lambda ctx: {"prompt": llm.improve_prompt(b.text)}, "io")


@app.get("/api/llm/status")
def llm_status() -> dict:
    s = config.load_settings()
    return {"provider": s["llm_provider"], "ollama": llm.ollama_status(), "model": s["ollama_model"],
            "gemini": bool(s.get("gemini_api_key"))}


class GoogleImageBody(BaseModel):
    prompt: str
    aspect: str = "9:16"
    count: int = 1


class GoogleVideoBody(BaseModel):
    prompt: str
    aspect: str = "9:16"
    image_media_id: Optional[str] = None
    negative: str = ""
    duration: Optional[int] = None
    resolution: Optional[str] = None


@app.post("/api/google/image")
def google_image(b: GoogleImageBody) -> dict:
    return _job("google-image", f"Imagen (Google): {b.prompt[:30]}",
                lambda ctx: google.generate_image(ctx, b.prompt, b.aspect, b.count), "io")


@app.post("/api/google/video")
def google_video(b: GoogleVideoBody) -> dict:
    img = _media_or_404(b.image_media_id).path if b.image_media_id else None
    return _job("google-video", f"Google vídeo: {b.prompt[:30]}",
                lambda ctx: google.generate_video(ctx, b.prompt, b.aspect, img, b.negative, b.duration,
                                                  b.resolution), "io")


@app.post("/api/autoreel")
def autoreel_run(b: autoreel.AutoReelRequest) -> dict:
    return _job("autoreel", f"Reel automático: {b.title[:30]}", lambda ctx: autoreel.build(ctx, b))


# ------------------------------------------------------------------ modelos


@app.get("/api/models")
def models() -> dict:
    return {"models": catalog.entries(), "fonts": catalog.fonts_status(), "extras": catalog.extras_status(),
            "llm": llm_status(), "cache": catalog.cache_usage()}


class IdBody(BaseModel):
    id: str


@app.post("/api/models/download")
def model_download(b: IdBody) -> dict:
    return _job("download", f"Descargando {b.id}", lambda ctx: catalog.download(ctx, b.id), "io")


@app.post("/api/models/delete")
def model_delete(b: IdBody) -> dict:
    try:
        return catalog.delete_model(b.id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/cache")
def cache_info() -> dict:
    return catalog.cache_usage()


@app.post("/api/cache/clear")
def cache_clear() -> dict:
    return catalog.clear_cache()


@app.post("/api/fonts/download")
def fonts_download() -> dict:
    return _job("fonts", "Descargando fuentes", catalog.download_fonts, "io")


@app.post("/api/extras/install")
def extras_install(b: IdBody) -> dict:
    return _job("extra", f"Instalando {b.id}", lambda ctx: catalog.install_extra(ctx, b.id), "io")


# ------------------------------------------------------- Hugging Face Hub


@app.get("/api/hub/search")
def hub_search(kind: str = "image", sort: str = "trending", q: str = "", limit: int = 30) -> list[dict]:
    try:
        return hub.search(kind, sort, q, limit)
    except Exception as exc:  # noqa: BLE001 - sin conexión, límite de peticiones…
        raise HTTPException(502, f"No se pudo consultar Hugging Face: {exc}") from exc


@app.get("/api/hub/info")
def hub_info(repo: str) -> dict:
    try:
        return hub.info(repo)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"No se pudo leer el modelo: {exc}") from exc


@app.get("/api/hub/featured")
def hub_featured() -> list[dict]:
    added = {m["repo"] for m in hub.custom_models()}
    return [{**f, "added": f["repo"] in added} for f in hub.FEATURED]


class HubAdd(BaseModel):
    repo: str
    kind: str
    name: Optional[str] = None
    size_gb: Optional[float] = None
    i2v: bool = False
    license: Optional[str] = None


@app.post("/api/hub/add")
def hub_add(b: HubAdd) -> dict:
    try:
        return hub.add_model(b.repo, b.kind, b.name, b.size_gb, b.i2v, b.license)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/hub/remove")
def hub_remove(b: IdBody) -> dict:
    gpu.release()
    return {"removed": hub.remove_model(b.id)}


@app.get("/api/update/check")
def update_check() -> dict:
    try:
        return updater.check()
    except Exception as exc:  # noqa: BLE001 - sin conexión o límite de la API de GitHub
        raise HTTPException(502, f"No se pudo comprobar si hay actualizaciones: {exc}") from exc


@app.post("/api/update/apply")
def update_apply() -> dict:
    return _job("update", "Actualizando ReelForge Studio", updater.apply, "io")


@app.post("/api/gpu/release")
def gpu_release() -> dict:
    gpu.release()
    return {"released": True}


# --------------------------------------------------------------- interfaz

if config.UI_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(config.UI_DIR), html=True), name="ui")
