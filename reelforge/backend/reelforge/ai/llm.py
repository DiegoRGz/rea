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


TEMPLATES: dict[str, dict[str, Any]] = {
    "auto": {"name": "Libre", "emoji": "✨", "caption_style": None, "transition": None,
             "instructions": ""},
    "top": {"name": "Top N", "emoji": "🏆", "caption_style": "beast", "transition": "zoomin",
            "instructions": "Formato TOP: anuncia el número en el gancho (\"Top 5…\"), una escena por puesto contando "
                            "hacia atrás y deja el mejor para el final. Cada escena empieza con \"Número X:\"."},
    "sabias": {"name": "¿Sabías que…?", "emoji": "🤯", "caption_style": "viral", "transition": "smoothup",
               "instructions": "Formato DATO CURIOSO: el gancho es una pregunta sorprendente; cada escena revela un "
                               "dato más impactante que el anterior; termina con un giro inesperado."},
    "historia": {"name": "Historia en 3 actos", "emoji": "🎬", "caption_style": "minimal", "transition": "fadeblack",
                 "instructions": "Formato STORYTELLING: empieza en el momento de máxima tensión, luego contexto, "
                                 "conflicto y resolución con moraleja. Frases muy visuales."},
    "mitos": {"name": "Mitos vs. realidad", "emoji": "❌", "caption_style": "highlight", "transition": "slideleft",
              "instructions": "Formato MITO/REALIDAD: alterna escenas \"Mito: …\" y \"Realidad: …\". El gancho "
                              "promete desmontar una creencia muy extendida."},
    "antes": {"name": "Antes y después", "emoji": "🔁", "caption_style": "viral", "transition": "wipeleft",
              "instructions": "Formato TRANSFORMACIÓN: muestra el problema (antes), el proceso en pasos y el "
                              "resultado (después). El gancho enseña el resultado final primero."},
    "tutorial": {"name": "Tutorial rápido", "emoji": "⚡", "caption_style": "karaoke", "transition": "smoothleft",
                 "instructions": "Formato TUTORIAL: promete un resultado en X pasos; cada escena es un paso "
                                 "accionable que empieza con un verbo. Cierra con \"guárdalo para luego\"."},
    "polemica": {"name": "Opinión polémica", "emoji": "🔥", "caption_style": "beast", "transition": "fadewhite",
                 "instructions": "Formato OPINIÓN IMPOPULAR: el gancho es una afirmación contundente que divide; "
                                 "argumenta con 2-3 razones y termina invitando a comentar si están de acuerdo."},
}


def _ollama(system: str, user: str, num_ctx: int = 4096) -> str:
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
            "options": {"temperature": 0.85, "num_ctx": num_ctx},
        },
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["message"]["content"]


def _gemini(system: str, user: str) -> str:
    from google.genai import types

    s = config.load_settings()
    if not s.get("gemini_api_key"):
        raise RuntimeError("Falta la clave de API de Gemini (Ajustes)")
    from .google import _client

    client = _client()
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


def chat_json(system: str, user: str, num_ctx: int = 8192) -> dict[str, Any]:
    """Consulta al LLM configurado y devuelve JSON. Lanza excepción si no hay LLM disponible."""
    provider = config.load_settings().get("llm_provider", "ollama")
    if provider == "none":
        raise RuntimeError("Sin LLM configurado")
    raw = _gemini(system, user) if provider == "gemini" else _ollama(system, user, num_ctx)
    return _extract_json(raw)


def write_script(topic: str, tone: str = "intrigante", seconds: int = 30, platform: str = "TikTok",
                 lang: str = "es", provider: str | None = None, extra: str = "",
                 template: str = "auto") -> dict[str, Any]:
    provider = provider or config.load_settings().get("llm_provider", "ollama")
    tpl = TEMPLATES.get(template, TEMPLATES["auto"])["instructions"]
    if tpl:
        extra = f"{tpl} {extra}".strip()
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
