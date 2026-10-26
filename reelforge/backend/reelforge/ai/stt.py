"""Transcripción con marcas de tiempo por palabra (faster-whisper, con
respaldo automático a CPU si la GPU no es compatible)."""

from __future__ import annotations

import os
from pathlib import Path

from .. import ffmpeg, gpu
from ..jobs import JobContext
from ..project import get_media, media_output_path, update_media

MODELS = ["tiny", "base", "small", "medium", "large-v3-turbo", "large-v3"]


def _prepare_cuda_dlls() -> None:
    """En Windows, las DLL de cuDNN/cuBLAS que trae PyTorch sirven a CTranslate2."""
    if os.name != "nt":
        return
    try:
        import torch

        lib = Path(torch.__file__).parent / "lib"
        if lib.is_dir():
            os.add_dll_directory(str(lib))  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass


def _load(model: str, device: str):
    from faster_whisper import WhisperModel

    if device == "cuda":
        _prepare_cuda_dlls()
        return WhisperModel(model, device="cuda", compute_type="float16")
    return WhisperModel(model, device="cpu", compute_type="int8", cpu_threads=max(2, (os.cpu_count() or 4) - 2))


def transcribe_file(ctx: JobContext, path: str, model: str = "large-v3-turbo", language: str | None = "es",
                    duration: float | None = None, prompt: str | None = None) -> dict:
    wav = media_output_path(".wav", "stt")
    ffmpeg.run([ffmpeg.binary(), "-hide_banner", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    duration = duration or ffmpeg.probe(wav).get("duration") or 0
    ctx.progress(0.08, "Cargando Whisper…")
    errors = []
    for device in (["cuda", "cpu"] if gpu.device() == "cuda" else ["cpu"]):
        try:
            whisper = gpu.acquire(f"whisper:{model}:{device}", lambda: _load(model, device))
            segments, info = whisper.transcribe(
                str(wav),
                language=language or None,
                word_timestamps=True,
                vad_filter=True,
                beam_size=5,
                initial_prompt=prompt or None,
            )
            words, text = [], []
            for seg in segments:
                ctx.progress(0.1 + 0.85 * min(1.0, seg.end / max(0.1, duration)), f"Transcribiendo ({device})…")
                text.append(seg.text.strip())
                for w in seg.words or []:
                    token = w.word.strip()
                    if token:
                        words.append({"w": token, "s": round(w.start, 3), "e": round(w.end, 3)})
            wav.unlink(missing_ok=True)
            return {"text": " ".join(text).strip(), "words": words, "language": info.language, "device": device}
        except Exception as exc:  # noqa: BLE001 - p.ej. CTranslate2 sin soporte para la GPU
            errors.append(f"{device}: {exc}")
            gpu.release()
            ctx.check()
    wav.unlink(missing_ok=True)
    raise RuntimeError("No se pudo transcribir. " + " | ".join(errors))


def transcribe_media(ctx: JobContext, media_id: str, model: str, language: str | None, prompt: str | None = None) -> dict:
    media = get_media(media_id)
    if not media:
        raise FileNotFoundError("Medio no encontrado")
    result = transcribe_file(ctx, media.path, model, language, media.duration, prompt)
    update_media(media_id, meta={**media.meta, "words": result["words"], "transcript": result["text"]})
    return {**result, "media_id": media_id}
