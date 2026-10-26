"""Guiones virales con un LLM local (Ollama) o Gemini, con plantilla de respaldo."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from .. import config

SYSTEM = """Eres un guionista experto en contenido viral para TikTok, Instagram Reels y YouTube Shorts.
Escribes guiones de narración en {lang} con:
- Un GANCHO en la primera frase (máx. 12 palabras) que genere curiosidad, polémica o promesa.
- Frases cortas, ritmo rápido, lenguaje oral y directo, sin emojis ni hashtags en la narración.
- Un cierre con llamada a la acción (seguir, comentar o guardar).
Divides el guion en escenas; cada escena tiene la narración y un prompt visual EN INGLÉS, muy descriptivo,
para un generador de imágenes/vídeo (sujeto, acción, entorno, luz, encuadre vertical 9:16).
Responde SOLO con JSON válido con esta forma exacta:
{{"title": str, "hook": str, "scenes": [{{"narration": str, "visual": str}}], "caption": str, "hashtags": [str]}}"""

USER = """Tema: {topic}
Tono: {tone}
Duración objetivo: {seconds} segundos (≈{words} palabras de narración en total)
Plataforma: {platform}
Número de escenas: {scenes}
{extra}"""

LANGS = {"es": "español neutro", "en": "inglés", "pt": "portugués", "fr": "francés", "it": "italiano"}


def _extract_json(text: str) -> dict[str, Any]:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        raise ValueError("El modelo no devolvió JSON")
    return json.loads(match.group(0))


def _normalize(data: dict[str, Any], topic: str) -> dict[str, Any]:
    scenes = []
    for s in data.get("scenes") or []:
        if isinstance(s, dict) and str(s.get("narration", "")).strip():
            scenes.append({"narration": str(s["narration"]).strip(), "visual": str(s.get("visual", topic)).strip()})
    if not scenes:
        raise ValueError("Guion sin escenas")
    tags = [t if str(t).startswith("#") else f"#{t}" for t in (data.get("hashtags") or [])][:10]
    return {
        "title": str(data.get("title") or topic)[:80],
        "hook": str(data.get("hook") or scenes[0]["narration"]),
        "scenes": scenes,
        "caption": str(data.get("caption") or ""),
        "hashtags": tags,
    }


def ollama_status() -> dict[str, Any]:
    url = config.load_settings()["ollama_url"].rstrip("/")
    try:
        r = httpx.get(f"{url}/api/tags", timeout=2.5)
        r.raise_for_status()
        return {"running": True, "models": [m["name"] for m in r.json().get("models", [])]}
    except Exception as exc:  # noqa: BLE001
        return {"running": False, "models": [], "error": str(exc)}


def _ollama(system: str, user: str) -> str:
    s = config.load_settings()
    r = httpx.post(
        f"{s['ollama_url'].rstrip('/')}/api/chat",
        json={
            "model": s["ollama_model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "format": "json",
            "stream": False,
            "think": False,
            "keep_alive": 0,  # libera la VRAM al terminar para los modelos de imagen/vídeo
            "options": {"temperature": 0.85, "num_ctx": 4096},
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _gemini(system: str, user: str) -> str:
    from google import genai
    from google.genai import types

    s = config.load_settings()
    if not s.get("gemini_api_key"):
        raise RuntimeError("Falta la clave de API de Gemini (Ajustes)")
    client = genai.Client(api_key=s["gemini_api_key"])
    resp = client.models.generate_content(
        model=s["gemini_text_model"],
        contents=user,
        config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                           temperature=0.9),
    )
    return resp.text or ""


def _template(topic: str, scenes: int) -> dict[str, Any]:
    lines = [
        f"Nadie te ha contado esto sobre {topic}.",
        f"La mayoría de la gente comete el mismo error con {topic}.",
        "Pero hay un detalle que lo cambia todo.",
        "Cuando lo entiendes, ya no hay vuelta atrás.",
        "Y lo mejor: puedes aplicarlo hoy mismo.",
        "Sígueme para más contenido como este.",
    ]
    picked = lines[: max(2, scenes - 1)] + [lines[-1]]
    return {
        "title": topic.capitalize(),
        "hook": picked[0],
        "scenes": [{"narration": n, "visual": f"{topic}, cinematic vertical shot, dramatic lighting"} for n in picked],
        "caption": f"{topic.capitalize()} 👀",
        "hashtags": ["#viral", "#parati", "#fyp"],
    }


def write_script(topic: str, tone: str = "intrigante", seconds: int = 30, platform: str = "TikTok",
                 lang: str = "es", provider: str | None = None, extra: str = "") -> dict[str, Any]:
    provider = provider or config.load_settings().get("llm_provider", "ollama")
    words = int(seconds * 2.6)
    scenes = max(3, min(10, round(seconds / 5)))
    system = SYSTEM.format(lang=LANGS.get(lang, lang))
    user = USER.format(topic=topic, tone=tone, seconds=seconds, words=words, platform=platform, scenes=scenes,
                       extra=f"Indicaciones extra: {extra}" if extra else "")
    errors = []
    for prov in [provider, "none"] if provider != "none" else ["none"]:
        try:
            if prov == "ollama":
                return {**_normalize(_extract_json(_ollama(system, user)), topic), "provider": "ollama"}
            if prov == "gemini":
                return {**_normalize(_extract_json(_gemini(system, user)), topic), "provider": "gemini"}
            return {**_template(topic, scenes), "provider": "plantilla", "warnings": errors}
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{prov}: {exc}")
    return {**_template(topic, scenes), "provider": "plantilla", "warnings": errors}


def improve_prompt(text: str) -> str:
    """Convierte una idea corta en un prompt visual detallado en inglés."""
    system = ("You write prompts for image/video diffusion models. Reply ONLY with JSON {\"prompt\": str}. "
              "The prompt is one vivid English sentence (max 60 words): subject, action, setting, lighting, "
              "camera, style, vertical 9:16 composition.")
    provider = config.load_settings().get("llm_provider", "ollama")
    try:
        raw = _gemini(system, text) if provider == "gemini" else _ollama(system, text)
        return str(_extract_json(raw).get("prompt") or text)
    except Exception:  # noqa: BLE001
        return f"{text}, cinematic lighting, highly detailed, vertical composition"
