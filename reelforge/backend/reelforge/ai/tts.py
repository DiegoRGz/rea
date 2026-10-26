"""Síntesis de voz: Kokoro-82M (local), XTTS-v2 (local, clonación opcional) y
Edge TTS (en línea, gratuito)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from .. import config, gpu
from ..jobs import JobContext
from ..project import media_output_path, register_media

KOKORO_VOICES = [
    {"id": "ef_dora", "name": "Dora (ES, mujer)", "lang": "es"},
    {"id": "em_alex", "name": "Álex (ES, hombre)", "lang": "es"},
    {"id": "em_santa", "name": "Santa (ES, hombre grave)", "lang": "es"},
    {"id": "af_heart", "name": "Heart (EN-US, mujer)", "lang": "en"},
    {"id": "af_bella", "name": "Bella (EN-US, mujer)", "lang": "en"},
    {"id": "am_michael", "name": "Michael (EN-US, hombre)", "lang": "en"},
    {"id": "am_fenrir", "name": "Fenrir (EN-US, hombre)", "lang": "en"},
    {"id": "bf_emma", "name": "Emma (EN-UK, mujer)", "lang": "en"},
    {"id": "bm_george", "name": "George (EN-UK, hombre)", "lang": "en"},
    {"id": "pf_dora", "name": "Dora (PT-BR, mujer)", "lang": "pt"},
    {"id": "pm_alex", "name": "Alex (PT-BR, hombre)", "lang": "pt"},
    {"id": "ff_siwis", "name": "Siwis (FR, mujer)", "lang": "fr"},
    {"id": "if_sara", "name": "Sara (IT, mujer)", "lang": "it"},
]

EDGE_VOICES = [
    {"id": "es-MX-DaliaNeural", "name": "Dalia (México)", "lang": "es"},
    {"id": "es-MX-JorgeNeural", "name": "Jorge (México)", "lang": "es"},
    {"id": "es-ES-ElviraNeural", "name": "Elvira (España)", "lang": "es"},
    {"id": "es-ES-AlvaroNeural", "name": "Álvaro (España)", "lang": "es"},
    {"id": "es-AR-ElenaNeural", "name": "Elena (Argentina)", "lang": "es"},
    {"id": "es-AR-TomasNeural", "name": "Tomás (Argentina)", "lang": "es"},
    {"id": "es-CO-SalomeNeural", "name": "Salomé (Colombia)", "lang": "es"},
    {"id": "es-CO-GonzaloNeural", "name": "Gonzalo (Colombia)", "lang": "es"},
    {"id": "es-US-PalomaNeural", "name": "Paloma (EE. UU.)", "lang": "es"},
    {"id": "es-US-AlonsoNeural", "name": "Alonso (EE. UU.)", "lang": "es"},
    {"id": "en-US-AndrewNeural", "name": "Andrew (EN-US)", "lang": "en"},
    {"id": "en-US-EmmaNeural", "name": "Emma (EN-US)", "lang": "en"},
    {"id": "en-US-GuyNeural", "name": "Guy (EN-US)", "lang": "en"},
]

ENGINES = {
    "kokoro": {"name": "Kokoro 82M (local)", "local": True, "clone": False, "module": "kokoro"},
    "xtts": {"name": "XTTS-v2 (local, clonación de voz)", "local": True, "clone": True, "module": "TTS",
             "license": "Coqui Public Model License: sólo uso no comercial."},
    "edge": {"name": "Edge TTS (en línea, gratis)", "local": False, "clone": False, "module": "edge_tts"},
}


def catalog() -> dict[str, Any]:
    clones = []
    if config.VOICES_DIR.is_dir():
        clones = [{"id": str(p), "name": p.stem, "lang": "multi"} for p in sorted(config.VOICES_DIR.glob("*.wav"))]
    return {
        "engines": [{"id": k, **v, "installed": gpu.has_module(v["module"])} for k, v in ENGINES.items()],
        "voices": {"kokoro": KOKORO_VOICES, "edge": EDGE_VOICES, "xtts": clones},
    }


def _kokoro(text: str, voice: str, speed: float, out: Path, ctx: JobContext) -> None:
    import numpy as np
    import soundfile as sf

    lang = voice[0] if voice else "e"

    # El "modelo" de la ranura es un dict de pipelines por idioma (comparten pesos).
    pipelines = gpu.acquire("kokoro", dict)
    if lang not in pipelines:
        from kokoro import KPipeline

        pipelines[lang] = KPipeline(lang_code=lang, repo_id="hexgrad/Kokoro-82M", device=gpu.device())
    pipe = pipelines[lang]
    chunks = []
    paragraphs = [p for p in text.split("\n") if p.strip()] or [text]
    for i, para in enumerate(paragraphs):
        ctx.progress(0.1 + 0.8 * i / len(paragraphs), f"Sintetizando {i + 1}/{len(paragraphs)}")
        for _, _, audio in pipe(para, voice=voice, speed=speed, split_pattern=r"(?<=[.!?])\s+"):
            if audio is None:
                continue
            arr = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            chunks.append(arr)
            chunks.append(np.zeros(int(24000 * 0.12), dtype=arr.dtype))
    if not chunks:
        raise RuntimeError("Kokoro no devolvió audio")
    sf.write(str(out), np.concatenate(chunks[:-1]), 24000)


def _xtts(text: str, speaker_wav: str, lang: str, speed: float, out: Path, ctx: JobContext) -> None:
    def load():
        from TTS.api import TTS  # coqui-tts

        return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(gpu.device())

    tts = gpu.acquire("xtts", load)
    ctx.progress(0.3, "Clonando voz…")
    tts.tts_to_file(text=text, speaker_wav=speaker_wav, language=lang or "es", file_path=str(out), speed=speed)


async def _edge_async(text: str, voice: str, rate: int, pitch: int, out: Path) -> list[dict]:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%", pitch=f"{pitch:+d}Hz", boundary="WordBoundary")
    words: list[dict] = []
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 10_000_000
                e = s + chunk["duration"] / 10_000_000
                words.append({"w": chunk["text"], "s": round(s, 3), "e": round(e, 3)})
    return words


def synthesize(ctx: JobContext, text: str, engine: str = "kokoro", voice: str = "ef_dora",
               speed: float = 1.0, pitch: int = 0, name: str | None = None, lang: str = "es") -> dict:
    text = text.strip()
    if not text:
        raise ValueError("El texto está vacío")
    ctx.progress(0.05, "Cargando motor de voz…")
    words: list[dict] = []
    if engine == "edge":
        out = media_output_path(".mp3", "voz")
        words = asyncio.run(_edge_async(text, voice, int(round((speed - 1) * 100)), pitch, out))
    elif engine == "xtts":
        out = media_output_path(".wav", "voz")
        _xtts(text, voice, lang, speed, out, ctx)
    else:
        out = media_output_path(".wav", "voz")
        _kokoro(text, voice or "ef_dora", speed, out, ctx)
    ctx.progress(0.95, "Guardando…")
    item = register_media(out, source="tts", name=name or f"Voz · {text[:28]}",
                          meta={"text": text, "engine": engine, "voice": voice, "words": words})
    out.unlink(missing_ok=True)
    return item.model_dump()


def save_clone_sample(path: str, name: str) -> str:
    """Guarda una muestra de referencia (6-20 s) para XTTS como WAV 24 kHz mono."""
    from .. import ffmpeg

    safe = "".join(c for c in name if c.isalnum() or c in " -_").strip() or "voz"
    dest = config.VOICES_DIR / f"{safe}.wav"
    ffmpeg.run([ffmpeg.binary(), "-hide_banner", "-y", "-i", path, "-t", "25", "-ac", "1", "-ar", "24000",
                "-af", "highpass=f=70,loudnorm", str(dest)])
    return str(dest)
