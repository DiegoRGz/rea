# ReelForge Studio

Estudio de escritorio **100 % local** para crear reels virales (TikTok, Instagram Reels, YouTube Shorts) con IA:
guion → voz → imágenes/vídeo → subtítulos animados → edición con transiciones → exportación.

Pensado y dimensionado para: **Intel i5-13420H · NVIDIA RTX 5050 Laptop 8 GB · 48 GB RAM · Windows 10/11**.

---

## Qué incluye

| Módulo | Qué hace | Motor |
| --- | --- | --- |
| **Reel automático** | Asistente en 5 pasos: idea → guion con gancho y CTA → voz → visuales por escena → estilo. Crea un proyecto editable. | Ollama/Gemini + Kokoro/Edge + SDXL/Wan/Veo + Whisper |
| **Editor tipo CapCut** | Línea de tiempo con pistas de vídeo, texto, subtítulos, voz y música; arrastrar y soltar, reordenar, recortar con tiradores, dividir (S), duplicar, deshacer/rehacer, zoom, vista previa en vivo y «vista previa real» renderizada. | HTML5 + FFmpeg |
| **Transiciones** | 26 transiciones (fundidos, barridos, deslizamientos, zoom, círculo, flash, desenfoque, pixelado…). | FFmpeg `xfade` / `acrossfade` |
| **Efectos** | Ken Burns (acercar, alejar, paneos), fondo difuminado para vídeos horizontales, 8 filtros de color, velocidad, volumen. | FFmpeg |
| **Voz IA / narración** | Voces naturales en español y otros idiomas, velocidad/tono, clonación de voz opcional. | Kokoro-82M (local), Edge TTS (en línea, gratis), XTTS-v2 (opcional) |
| **Transcripción** | Tiempos por palabra, exportación SRT/VTT/TXT, subtítulos automáticos para tus propios vídeos. | faster-whisper large-v3-turbo (GPU con respaldo a CPU) |
| **Subtítulos virales** | 7 estilos animados palabra a palabra: Viral (Hormozi), Beast, Resaltado, Karaoke, Una palabra, Neón, Minimalista. Posición, tamaño, mayúsculas, edición del texto. | ASS + libass |
| **Generar** | Imágenes 9:16 en segundos, vídeo de texto o de imagen, música de fondo. | SDXL Lightning/Turbo, Wan 2.1 1.3B, LTX-Video, MusicGen |
| **Google** | Ventana de **Google Flow** con tu cuenta (importa automáticamente lo que descargues) + **Imagen 4 / Veo 3** por API. | Gemini API |
| **Exportación** | Preajustes TikTok / Reels / Shorts / Borrador / Máster 4K o personalizado: 540p–2160p, 24/30/60 fps, H.264 / H.265 / AV1, 4 niveles de calidad, NVENC, SRT y portada JPG, sólo audio MP3. | FFmpeg (NVENC en RTX) |
| **Modelos** | Descarga con progreso, estado de VRAM, perfil recomendado, fuentes OFL para subtítulos, instalación de extras. | Hugging Face Hub |

Interfaz oscura minimalista con animaciones en botones (ripple, brillo, resortes), transiciones entre páginas,
barra de trabajos en segundo plano con cancelación, y una **pantalla de carga animada** (logo que se dibuja,
aurora giratoria, partículas, progreso real del arranque).

## Instalación (Windows)

### Requisitos que instalas tú

1. **Driver NVIDIA reciente** (serie 570 o superior: la RTX 5050 necesita CUDA 12.8).
2. **Python 3.12** desde [python.org](https://www.python.org/downloads/windows/) marcando *Add python.exe to PATH*.
3. Para compilar el `.exe`: **Node.js 20+**.
4. Opcional: **[Ollama](https://ollama.com/download)** para escribir guiones con un LLM local (`ollama pull qwen3:8b`).

### Compilar el instalador

```bat
cd reelforge
scripts\build-windows.bat
```

Genera en `reelforge\release\` el instalador `ReelForge Studio Setup 1.0.0.exe` y una versión portable.
Para probar sin empaquetar: `scripts\run-dev.bat`.

### Primer arranque

La pantalla de carga detecta que falta el entorno y **muestra el plan antes de tocar nada**:

- entorno Python aislado en `%APPDATA%\ReelForge Studio\python-env`;
- PyTorch con CUDA 12.8 (~3 GB) o CPU si no hay GPU NVIDIA;
- motor de ReelForge y, opcionalmente, paquetes de IA local (~2 GB), FFmpeg y fuentes OFL
  (en `Documentos\ReelForge`).

Pulsa **Instalar** y espera (10-25 min según conexión). No se instala Python, drivers ni otro software del sistema.
Los pesos de cada modelo se descargan después desde la página **Modelos** (o automáticamente al usarlos por primera vez).

## Rendimiento orientativo en tu portátil

Estimaciones (no medidas en tu equipo), con el modo *VRAM baja* activado:

| Tarea | Modelo | VRAM | Tiempo aprox. |
| --- | --- | --- | --- |
| Guion de 30 s | Ollama qwen3:8b | ~5,5 GB (se libera al terminar) | 10-30 s |
| Voz de 30 s | Kokoro 82M | ~1 GB | 3-8 s |
| Imagen 768×1344 | SDXL Lightning 4 pasos | ~6-7 GB con offload | 5-15 s |
| Transcripción de 60 s | Whisper large-v3-turbo | ~2,5 GB | 5-15 s (CPU int8: ~1 min) |
| Clip de 3 s 480×832 | Wan 2.1 1.3B | ~7-8 GB + RAM | 4-10 min |
| Exportar reel 1080p de 30 s | FFmpeg + NVENC | — | 20-60 s |

Los modelos se cargan **de uno en uno** (la app descarga el anterior de la VRAM). Con 48 GB de RAM el codificador
de texto de los modelos de vídeo (T5, ~10 GB) se ejecuta en CPU y sólo el transformer ocupa la GPU.

**Consejo viral:** para publicar rápido, usa *Imágenes IA* con movimiento Ken Burns + transiciones + subtítulos
«Viral»; reserva Wan/Veo para 1-2 planos clave.

## Google Flow

Google Flow **no tiene una API pública**, así que no se puede «conectar» una cuenta para que otra aplicación genere
en tu nombre. ReelForge ofrece las dos vías legítimas:

1. **Google → Abrir Google Flow**: abre Flow en una ventana de la app con una sesión persistente propia. Inicias
   sesión con tu cuenta y generas allí con tus créditos; **cada descarga se importa automáticamente** a la
   biblioteca, lista para el editor. ReelForge no lee ni automatiza tu sesión. Si Google bloquea el inicio de
   sesión en la ventana integrada, usa Flow en tu navegador e importa los archivos con *Importar*.
2. **API de Gemini** (Ajustes → Google): con una clave de [Google AI Studio](https://aistudio.google.com/apikey)
   generas con **Imagen 4** y **Veo 3** (los modelos de Flow) desde *Generar* y desde el *Reel automático*.
   Tiene coste según la tarifa de Google; los nombres de modelo son editables en Ajustes.

## ¿Y el repositorio REA?

Se evaluó y **no fue necesario**: las funciones de edición (cortes, recortes, velocidad, mezcla, transiciones)
se implementan directamente con FFmpeg, cuyo filtro `xfade` ya aporta las transiciones típicas de los editores
comerciales con documentación abierta. Hacer ingeniería inversa de CapCut sería innecesario y sus términos de
uso lo prohíben. ReelForge vive en su propia carpeta y no modifica el código de REA.

## Licencias de modelos (revisa antes de monetizar)

| Modelo | Licencia |
| --- | --- |
| Kokoro-82M, Wan 2.1, faster-whisper | Apache-2.0 / MIT |
| SDXL / SDXL-Lightning / SDXL-Turbo | CreativeML OpenRAIL++-M / Stability AI Community |
| LTX-Video | LTX OpenRAIL-M |
| MusicGen | **CC-BY-NC 4.0 (no comercial)** |
| XTTS-v2 | **Coqui Public Model License (no comercial)** |
| Edge TTS | Servicio en línea de Microsoft |
| Fuentes de subtítulos | SIL Open Font License |

## Arquitectura

```
Electron (electron/)                    Motor Python (backend/reelforge/)
├─ splash.html  pantalla de carga        ├─ app.py        API REST local (127.0.0.1 + token)
├─ setup.js     instalación guiada       ├─ jobs.py       cola GPU/render/E-S con progreso y cancelación
├─ main.js      ventanas, motor, Flow    ├─ gpu.py        un modelo en VRAM a la vez, perfil de hardware
└─ preload.js   puente seguro            ├─ render.py     línea de tiempo → FFmpeg (xfade, Ken Burns, ducking, NVENC)
                                         ├─ captions.py   subtítulos ASS animados, SRT/VTT
Interfaz (ui/)  HTML/CSS/JS sin build    ├─ autoreel.py   flujo Reel automático
├─ js/pages/    páginas                  ├─ catalog.py    descargas de modelos, fuentes, extras
└─ js/editor/   línea de tiempo y player └─ ai/           llm, tts, stt, image, video, music, google
```

Datos del usuario en `Documentos\ReelForge` (proyectos, biblioteca, exportaciones, modelos, registros).

## Desarrollo

```bash
# Motor + interfaz en el navegador (Linux/macOS/Windows)
scripts/run-browser.sh            # abre la URL con token que imprime

# Pruebas del motor de render (necesitan ffmpeg con libass)
cd backend && python -m pytest -q
```

## Estado de verificación

- **Probado** (Linux, sin GPU): render de la línea de tiempo con las 26 transiciones, los 7 estilos de subtítulos,
  Ken Burns, fondo difuminado, filtros, ducking, sólo audio, SRT y portada (`backend/tests`); todas las páginas
  de la interfaz en Chromium sin errores de consola; dividir/deshacer en el editor y exportación 1080p desde la UI;
  pantalla de carga y pantalla de configuración.
- **No probado aquí**: modelos de IA reales en GPU (Kokoro, Whisper, SDXL, Wan, LTX, MusicGen), Edge TTS, API de
  Google, la ventana de Google Flow, el empaquetado `.exe` y el arranque de Electron en Windows. El código sigue
  las APIs documentadas de cada biblioteca, pero la primera ejecución en tu equipo es la verificación real:
  si algo falla, el registro está en `Documentos\ReelForge\logs\engine.log`.
