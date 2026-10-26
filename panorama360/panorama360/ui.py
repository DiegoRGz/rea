"""Interfaz web local (Gradio) + visor 360° (Pannellum)."""

from __future__ import annotations

import html
import json
import shutil
import time
from pathlib import Path

import gradio as gr
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from . import hardware as hw
from .engine import Engine, Request
from .jobs import CANCELLED, DONE, FAILED, PENDING, RUNNING, JobQueue
from .library import list_outputs, metadata, public_relative, resolve_public, thumbnail
from .models import SAMPLE_PROMPTS, SAMPLE_SEED, SCHEDULERS, Catalog, model_card, samples_for
from .paths import OUTPUT_DIR, REFS_DIR, SAMPLES_DIR, DATA_DIR

QUALITY = {
    "rapida": ("⚡ Rápida", False),
    "alta": ("✨ Alta", True),
}
RESOLUTIONS = [
    ("3072 × 1536", 3072),
    ("4096 × 2048 · recomendada para Facebook", 4096),
    ("6144 × 3072 · máxima nitidez", 6144),
]
STATUS_ICON = {PENDING: "⏳", RUNNING: "🎨", DONE: "✅", FAILED: "⚠️", CANCELLED: "✖️"}
EXAMPLES = [
    "snow covered baseball stadium with green seats, overcast winter sky, distant plains",
    "inside a cozy wooden mountain cabin, fireplace, large windows with snowy peaks",
    "rooftop terrace in Mexico City at night, city lights, warm string lights",
    "ancient mayan ruins in the jungle at sunrise, mist, lush vegetation",
    "futuristic neon city street after rain, reflections, cyberpunk",
]

CSS = """
#header {padding: 4px 0 0}
#header h1 {margin: 0; font-size: 1.6rem}
#header p {margin: 2px 0 0; opacity: .75}
.pano-progress {border-radius: 10px; padding: 10px 12px; background: var(--block-background-fill);
  border: 1px solid var(--border-color-primary)}
.pano-bar {height: 8px; border-radius: 4px; background: var(--border-color-primary); overflow: hidden; margin-top: 6px}
.pano-bar > div {height: 100%; background: var(--color-accent); transition: width .4s}
.pano-link a {display: inline-block; padding: 8px 14px; border-radius: 8px; background: var(--color-accent);
  color: white !important; text-decoration: none; font-weight: 600}
footer {display: none !important}
"""

VIEWER = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Visor 360°</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.css">
<script src="https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.js"></script>
<style>html,body,#pano{margin:0;height:100%;background:#111;color:#eee;font-family:system-ui}
#err{position:absolute;top:40%;width:100%;text-align:center}</style></head>
<body><div id="pano"></div><div id="err"></div>
<script>
if (window.pannellum) {
  pannellum.viewer('pano', {type: 'equirectangular', panorama: __SRC__, autoLoad: true,
    autoRotate: -2, showZoomCtrl: true, hfov: 100, title: __TITLE__});
} else {
  document.getElementById('err').textContent = 'El visor necesita internet para cargar Pannellum. La imagen está en: ' + __SRC__;
}
</script></body></html>"""


def _skip():
    return gr.skip() if hasattr(gr, "skip") else gr.update()


class App:
    def __init__(self):
        self.catalog = Catalog()
        self.hardware = hw.detect()
        self.recommended = hw.recommend(self.hardware)
        self.engine = Engine(self.catalog, self.hardware, self.recommended)
        self.queue = JobQueue(self.engine)

    # ------------------------------------------------------------ helpers

    def _version(self) -> str:
        """Cambia cada vez que termina un trabajo: evita refrescar galerías sin necesidad."""
        finished = [(j.id, j.status) for j in self.queue.snapshot() if j.status in (DONE, FAILED, CANCELLED)]
        return json.dumps(finished)

    def _store_reference(self, path: str | None) -> str | None:
        if not path:
            return None
        source = Path(path)
        target = REFS_DIR / f"{int(time.time() * 1000)}{source.suffix.lower() or '.png'}"
        shutil.copyfile(source, target)
        return str(target)

    def _request(self, model_key, prompt, negative, seed, steps, cfg, final_width, quality, refine_strength,
                 reference, reference_mode, similarity, fov, poles, lora_weight) -> Request:
        return Request(
            model_key=model_key, prompt=prompt, negative=negative or "", seed=int(seed),
            steps=int(steps) or None, cfg=float(cfg) or None, final_width=int(final_width),
            refine=QUALITY[quality][1], refine_strength=float(refine_strength),
            reference=self._store_reference(reference), reference_mode=reference_mode,
            reference_similarity=float(similarity), photo_fov=float(fov), clean_poles=bool(poles),
            lora_weight=float(lora_weight),
        )

    # ------------------------------------------------------------ acciones

    def enqueue(self, count, random_seeds, *fields):
        request = self._request(*fields)
        if not request.prompt.strip() and not request.reference:
            return "✋ Describe la escena o añade una imagen de referencia."
        jobs = self.queue.add_batch(request, int(count), bool(random_seeds))
        seeds = ", ".join(str(j.request["seed"]) for j in jobs[:4]) + ("…" if len(jobs) > 4 else "")
        return f"➕ {len(jobs)} panorámica(s) añadida(s) a la cola · semillas {seeds}"

    def enqueue_sample(self, model_key, sample_label):
        request = Request(model_key=model_key, prompt=SAMPLE_PROMPTS[sample_label], seed=SAMPLE_SEED,
                          final_width=3072, refine=False)
        self.queue.add_batch(request, 1, False, sample_name=sample_label)
        name = self.catalog.get(model_key).name
        return f"🧪 Muestra de **{name}** en la cola («{sample_label}», semilla {SAMPLE_SEED})."

    def enqueue_compare(self, model_keys, sample_label, custom_prompt, seed):
        if not model_keys:
            return "Elige al menos un modelo."
        prompt = custom_prompt.strip() or SAMPLE_PROMPTS[sample_label]
        label = sample_label if not custom_prompt.strip() else custom_prompt.strip()[:40]
        seed = int(seed) if int(seed) >= 0 else SAMPLE_SEED
        for key in model_keys:
            request = Request(model_key=key, prompt=prompt, seed=seed, final_width=3072, refine=False)
            self.queue.add_batch(request, 1, False, sample_name=label)
        return f"🧪 {len(model_keys)} muestras en la cola con la misma escena y semilla {seed}."

    # ------------------------------------------------------------ vistas

    def progress_html(self) -> str:
        current = self.queue.current()
        counts = self.queue.counts()
        pending = counts.get(PENDING, 0)
        paused = " · ⏸ en pausa" if self.queue.paused else ""
        if current is None:
            text = f"Sin trabajos en curso · {pending} pendiente(s){paused}" if pending else f"La cola está vacía{paused}"
            return f'<div class="pano-progress">{text}</div>'
        req = current.request
        model = self.catalog.models.get(req["model_key"])
        title = html.escape((current.sample_name and f"Muestra: {current.sample_name}") or req["prompt"][:90])
        return (
            f'<div class="pano-progress"><b>{title}</b> · {html.escape(model.name if model else req["model_key"])} '
            f'· {current.index}/{current.total} del lote · {pending} pendiente(s){paused}<br>'
            f'<small>{html.escape(current.message)}</small>'
            f'<div class="pano-bar"><div style="width:{current.progress * 100:.0f}%"></div></div></div>'
        )

    def queue_rows(self) -> list[list]:
        rows = []
        for job in reversed(self.queue.snapshot()[-60:]):
            req = job.request
            model = self.catalog.models.get(req["model_key"])
            rows.append([
                f"{STATUS_ICON.get(job.status, '')} {job.status}",
                f"{job.progress * 100:.0f}%",
                (f"🧪 {job.sample_name}" if job.sample_name else req["prompt"][:70]),
                model.name if model else req["model_key"],
                req["seed"],
                job.message,
            ])
        return rows or [["", "", "La cola está vacía", "", "", ""]]

    def recent_results(self):
        files = list_outputs(60)
        return [(thumbnail(p), p.stem) for p in files], [str(p) for p in files]

    def model_samples(self, key):
        items = samples_for(key)
        return [(thumbnail(path), caption) for path, caption in items], [path for path, _ in items]

    def compare_view(self):
        gallery, paths = [], []
        for entry in self.catalog.models.values():
            items = samples_for(entry.key)
            if items:
                path, caption = items[0]
                gallery.append((thumbnail(path), f"{entry.name} · {caption}"))
                paths.append(path)
        return gallery, paths

    def selection_view(self, path: str | None):
        if not path:
            return "", None, ""
        relative = public_relative(path)
        link = (
            f'<div class="pano-link"><a href="/visor?archivo={html.escape(relative)}" target="_blank">'
            "🌐 Ver en 360°</a></div>" if relative else ""
        )
        meta = metadata(path)
        details = ""
        if meta:
            details = (
                f"**Modelo:** {meta.get('model')} · **Semilla:** `{meta.get('seed')}` · "
                f"**Tamaño:** {meta.get('size', ['?', '?'])[0]}×{meta.get('size', ['?', '?'])[1]} · "
                f"**Tiempo:** {meta.get('seconds')} s\n\n**Prompt:** {meta.get('prompt')}"
            )
            if meta.get("warnings"):
                details += "\n\n⚠️ " + " ".join(meta["warnings"])
        return link, path, details


def build(app: App) -> gr.Blocks:
    catalog = app.catalog
    default_key = catalog.default_key()
    profile = app.recommended

    with gr.Blocks(title="Panorama 360°", **_blocks_style()) as demo:
        results_paths = gr.State([])
        samples_paths = gr.State([])
        compare_paths = gr.State([])
        gallery_paths = gr.State([])
        version = gr.State("")

        gr.HTML(
            "<div id='header'><h1>🌐 Panorama 360°</h1>"
            f"<p>Generador local de panorámicas equirectangulares listas para Facebook · {html.escape(hw.describe(app.hardware, profile))}</p></div>"
        )

        with gr.Tabs():
            # ---------------------------------------------------------------- Crear
            with gr.Tab("🎨 Crear"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=5, min_width=360):
                        with gr.Group():
                            model = gr.Dropdown(catalog.choices(), value=default_key, label="1 · Modelo")
                            card = gr.Markdown(model_card(catalog.get(default_key)))
                            samples = gr.Gallery(
                                label="Muestras de este modelo (se generan en tu equipo con «Generar muestra»)", columns=2, height=200,
                                object_fit="cover", allow_preview=True, show_label=True,
                            )
                            with gr.Row(equal_height=True):
                                sample_label = gr.Dropdown(list(SAMPLE_PROMPTS), value=next(iter(SAMPLE_PROMPTS)),
                                                           label="Escena de prueba", scale=3)
                                sample_btn = gr.Button("🧪 Generar muestra", scale=2, variant="secondary")
                        with gr.Group():
                            prompt = gr.Textbox(
                                label="2 · Describe la escena", lines=3,
                                placeholder="Ej.: snow covered baseball stadium, green seats, overcast sky… (en inglés da mejores resultados)",
                            )
                        gr.Examples(EXAMPLES, inputs=prompt, label="Ideas")
                        with gr.Accordion("3 · Imagen de referencia (opcional)", open=False):
                            reference = gr.Image(type="filepath", label="Referencia", height=220)
                            reference_mode = gr.Radio(
                                [("Inspiración · mismo estilo y ambiente", "inspiracion"),
                                 ("Variación · misma composición (panorámica 2:1)", "variacion"),
                                 ("Extender foto normal a 360°", "extender")],
                                value="inspiracion", label="¿Cómo usarla?",
                            )
                            similarity = gr.Slider(0, 1, value=0.6, step=0.05, label="Parecido a la referencia")
                            fov = gr.Slider(50, 140, value=90, step=5, label="Campo de visión de la foto (°)", visible=False)
                        with gr.Group():
                            with gr.Row():
                                quality = gr.Radio([(v[0], k) for k, v in QUALITY.items()], value="alta", label="4 · Calidad",
                                                   info="Alta añade una pasada de detalle (más lenta).")
                                final_width = gr.Dropdown(RESOLUTIONS, value=profile.default_final_width, label="Resolución final")
                            with gr.Row():
                                count = gr.Slider(1, 50, value=4, step=1, label="¿Cuántas panorámicas?")
                                seed = gr.Number(value=-1, precision=0, label="Semilla (-1 = aleatoria)")
                            random_seeds = gr.Checkbox(True, label="Semilla distinta para cada una del lote")
                        with gr.Accordion("Ajustes avanzados", open=False):
                            negative = gr.Textbox(label="Evitar (prompt negativo)", lines=2,
                                                  placeholder="Se añade a una lista base contra marcos, texto y costuras.")
                            with gr.Row():
                                steps = gr.Slider(0, 60, value=0, step=1, label="Pasos (0 = recomendado del modelo)")
                                cfg = gr.Slider(0, 12, value=0, step=0.5, label="CFG (0 = recomendado del modelo)")
                            with gr.Row():
                                refine_strength = gr.Slider(0.15, 0.5, value=0.3, step=0.05, label="Fuerza del detalle",
                                                            info="Más alto = más detalle nuevo, menos fiel a la base.")
                                lora_weight = gr.Slider(0, 1.2, value=catalog.lora_360["weight"], step=0.05,
                                                        label="Peso del LoRA 360°")
                            poles = gr.Checkbox(True, label="Limpiar cenit y nadir (evita el 'remolino' arriba y abajo)")
                        add_btn = gr.Button("➕ Añadir a la cola", variant="primary", size="lg")
                        add_status = gr.Markdown()

                    with gr.Column(scale=7, min_width=420):
                        progress = gr.HTML(app.progress_html())
                        with gr.Row():
                            pause_btn = gr.Button("⏸ Pausar", size="sm")
                            resume_btn = gr.Button("▶ Reanudar", size="sm")
                            stop_btn = gr.Button("⏹ Cancelar actual", size="sm")
                            cancel_btn = gr.Button("✖ Cancelar pendientes", size="sm")
                            retry_btn = gr.Button("↻ Reintentar fallidas", size="sm")
                            clear_btn = gr.Button("🧹 Limpiar terminadas", size="sm")
                        queue_table = gr.Dataframe(
                            headers=["Estado", "%", "Escena", "Modelo", "Semilla", "Detalle"],
                            value=app.queue_rows(), interactive=False, wrap=True, max_height=260,
                        )
                        results = gr.Gallery(label="Resultados recientes", columns=3, height=420, object_fit="cover",
                                             allow_preview=True)
                        with gr.Row():
                            viewer_link = gr.HTML()
                            download = gr.File(label="Descargar (JPEG 360° con metadatos para Facebook)", height=70)
                        selection_info = gr.Markdown()

            # --------------------------------------------------------- Comparar
            with gr.Tab("🧪 Comparar modelos"):
                gr.Markdown(
                    "Genera la **misma escena con la misma semilla** en varios modelos para ver cuál te gusta más. "
                    "Las muestras se guardan y aparecen junto al selector de modelo en *Crear*."
                )
                with gr.Row():
                    compare_models = gr.CheckboxGroup(catalog.choices(), value=[default_key], label="Modelos")
                with gr.Row():
                    compare_label = gr.Dropdown(list(SAMPLE_PROMPTS), value=next(iter(SAMPLE_PROMPTS)), label="Escena de prueba")
                    compare_prompt = gr.Textbox(label="…o tu propia escena", placeholder="Opcional")
                    compare_seed = gr.Number(value=SAMPLE_SEED, precision=0, label="Semilla")
                compare_btn = gr.Button("🧪 Generar muestras", variant="primary")
                compare_status = gr.Markdown()
                compare_gallery = gr.Gallery(label="Última muestra de cada modelo", columns=3, height=520,
                                             object_fit="cover", allow_preview=True)
                with gr.Row():
                    compare_link = gr.HTML()
                    compare_file = gr.File(label="Descargar", height=70)
                    compare_refresh = gr.Button("🔄 Actualizar", size="sm")
                compare_info = gr.Markdown()

            # ----------------------------------------------------------- Galería
            with gr.Tab("🖼️ Galería"):
                gallery_refresh = gr.Button("🔄 Actualizar", size="sm")
                gallery = gr.Gallery(label=f"Todas tus panorámicas ({OUTPUT_DIR})", columns=4, height=620,
                                     object_fit="cover", allow_preview=True)
                with gr.Row():
                    gallery_link = gr.HTML()
                    gallery_file = gr.File(label="Descargar", height=70)
                gallery_info = gr.Markdown()

            # ----------------------------------------------------------- Modelos
            with gr.Tab("🧩 Modelos"):
                gr.Markdown(
                    "Añade cualquier modelo **SDXL**: un ID de Hugging Face (p. ej. `RunDiffusion/Juggernaut-XL-v9`) "
                    "o la ruta a un archivo `.safetensors` descargado de Civitai. Después genera una muestra para ver su calidad."
                )
                with gr.Row():
                    new_name = gr.Textbox(label="Nombre")
                    new_source = gr.Textbox(label="ID de Hugging Face o ruta .safetensors")
                    new_style = gr.Textbox(label="Estilo", placeholder="Fotorrealista, anime…")
                with gr.Row():
                    new_steps = gr.Slider(4, 60, value=30, step=1, label="Pasos")
                    new_cfg = gr.Slider(1, 12, value=6, step=0.5, label="CFG")
                    new_scheduler = gr.Dropdown([(v, k) for k, v in SCHEDULERS.items()], value="dpmpp_2m_karras", label="Sampler")
                    new_lora = gr.Checkbox(True, label="Usar LoRA 360°")
                with gr.Row():
                    add_model_btn = gr.Button("➕ Añadir modelo", variant="primary")
                    remove_model = gr.Dropdown([c for c in catalog.choices() if catalog.get(c[1]).user],
                                               label="Quitar un modelo tuyo")
                    remove_model_btn = gr.Button("🗑 Quitar")
                models_status = gr.Markdown()

            # ----------------------------------------------------------- Sistema
            with gr.Tab("⚙️ Sistema"):
                gr.Markdown(
                    f"**Equipo detectado:** {html.escape(hw.describe(app.hardware, profile))}  \n"
                    f"**Sistema:** {html.escape(app.hardware.system)}  \n"
                    f"**Carpetas:** salidas `{OUTPUT_DIR}` · muestras `{SAMPLES_DIR}` · datos `{DATA_DIR}`"
                )
                profile_choice = gr.Radio(
                    [(p.label + (" · recomendado" if p.key == profile.key else ""), p.key) for p in hw.PROFILES.values()],
                    value=profile.key, label="Perfil de rendimiento",
                )
                profile_desc = gr.Markdown(profile.description)
                with gr.Row():
                    apply_profile = gr.Button("Aplicar perfil", variant="primary")
                    unload_btn = gr.Button("Liberar memoria (descargar modelo)")
                system_status = gr.Markdown()

        # ================================================================ eventos

        request_fields = [model, prompt, negative, seed, steps, cfg, final_width, quality, refine_strength,
                          reference, reference_mode, similarity, fov, poles, lora_weight]

        def on_model(key):
            gallery_items, paths = app.model_samples(key)
            return model_card(catalog.get(key)), gallery_items, paths

        model.change(on_model, model, [card, samples, samples_paths])
        reference_mode.change(lambda m: gr.update(visible=m == "extender"), reference_mode, fov)
        sample_btn.click(app.enqueue_sample, [model, sample_label], add_status)
        add_btn.click(lambda c, r, *f: app.enqueue(c, r, *f), [count, random_seeds, *request_fields], add_status)

        pause_btn.click(lambda: app.queue.set_paused(True))
        resume_btn.click(lambda: app.queue.set_paused(False))
        stop_btn.click(app.queue.cancel_current)
        cancel_btn.click(lambda: f"✖ {app.queue.cancel_pending()} trabajo(s) cancelado(s).", None, add_status)
        retry_btn.click(lambda: f"↻ {app.queue.retry_failed()} trabajo(s) de nuevo en la cola.", None, add_status)
        clear_btn.click(app.queue.clear_finished)

        def pick(paths, evt: gr.SelectData):
            index = evt.index if isinstance(evt.index, int) else evt.index[0]
            return app.selection_view(paths[index] if 0 <= index < len(paths) else None)

        results.select(pick, results_paths, [viewer_link, download, selection_info])
        samples.select(pick, samples_paths, [viewer_link, download, selection_info])
        compare_gallery.select(pick, compare_paths, [compare_link, compare_file, compare_info])
        gallery.select(pick, gallery_paths, [gallery_link, gallery_file, gallery_info])

        def tick(last_version, key):
            current = app._version()
            if current == last_version:
                return app.progress_html(), app.queue_rows(), _skip(), _skip(), _skip(), _skip(), last_version
            items, paths = app.recent_results()
            sample_items, sample_paths = app.model_samples(key)
            return app.progress_html(), app.queue_rows(), items, paths, sample_items, sample_paths, current

        timer = gr.Timer(1.5)
        timer.tick(tick, [version, model], [progress, queue_table, results, results_paths, samples, samples_paths, version],
                   show_progress="hidden")

        compare_btn.click(app.enqueue_compare, [compare_models, compare_label, compare_prompt, compare_seed], compare_status)
        compare_refresh.click(app.compare_view, None, [compare_gallery, compare_paths])
        gallery_refresh.click(lambda: _gallery(app), None, [gallery, gallery_paths])

        def add_model(name, source, style, steps_, cfg_, scheduler, use_lora):
            try:
                entry = catalog.add_user_model(name, source, style, steps_, cfg_, scheduler, use_lora)
            except ValueError as exc:
                return f"✋ {exc}", gr.update(), gr.update(), gr.update()
            choices = catalog.choices()
            mine = [c for c in choices if catalog.get(c[1]).user]
            return (f"✅ **{entry.name}** añadido. Selecciónalo en *Crear* y genera una muestra.",
                    gr.update(choices=choices, value=entry.key), gr.update(choices=choices), gr.update(choices=mine))

        add_model_btn.click(add_model, [new_name, new_source, new_style, new_steps, new_cfg, new_scheduler, new_lora],
                            [models_status, model, compare_models, remove_model])

        def remove(key):
            if not key:
                return "Elige un modelo.", gr.update(), gr.update(), gr.update()
            try:
                catalog.remove_user_model(key)
            except ValueError as exc:
                return f"✋ {exc}", gr.update(), gr.update(), gr.update()
            choices = catalog.choices()
            mine = [c for c in choices if catalog.get(c[1]).user]
            return ("🗑 Modelo quitado (los archivos descargados siguen en la caché de Hugging Face).",
                    gr.update(choices=choices, value=catalog.default_key()), gr.update(choices=choices),
                    gr.update(choices=mine, value=None))

        remove_model_btn.click(remove, remove_model, [models_status, model, compare_models, remove_model])

        profile_choice.change(lambda k: hw.PROFILES[k].description, profile_choice, profile_desc)

        def set_profile(key):
            if app.queue.current() is not None:
                return "Espera a que termine el trabajo actual (o pausa la cola) para cambiar de perfil."
            app.engine.set_profile(hw.PROFILES[key])
            return f"✅ Perfil **{hw.PROFILES[key].label}** activo."

        apply_profile.click(set_profile, profile_choice, system_status)

        def unload():
            if app.queue.current() is not None:
                return "Hay un trabajo en curso; pausa la cola primero."
            app.engine.unload()
            return "✅ Memoria liberada."

        unload_btn.click(unload, None, system_status)

        def initial(key):
            items, paths = app.recent_results()
            sample_items, sample_paths = app.model_samples(key)
            compare_items, cpaths = app.compare_view()
            all_items, all_paths = _gallery(app)
            return items, paths, sample_items, sample_paths, compare_items, cpaths, all_items, all_paths, app._version()

        demo.load(initial, model, [results, results_paths, samples, samples_paths, compare_gallery, compare_paths,
                                   gallery, gallery_paths, version])
    return demo


def _gallery(app: App):
    files = list_outputs(300)
    return [(thumbnail(p), p.stem) for p in files], [str(p) for p in files]


def _blocks_style() -> dict:
    """Gradio 6 movió ``theme`` y ``css`` de Blocks a launch/mount; se pasan donde se acepten."""
    import inspect

    params = inspect.signature(gr.Blocks.__init__).parameters
    style = {"theme": gr.themes.Soft(primary_hue="emerald", neutral_hue="slate"), "css": CSS}
    return {k: v for k, v in style.items() if k in params}


def create_server() -> tuple[FastAPI, App]:
    app = App()
    server = FastAPI(title="Panorama 360°")

    @server.get("/visor", response_class=HTMLResponse)
    def viewer(archivo: str):
        if resolve_public(archivo) is None:
            raise HTTPException(404, "Panorámica no encontrada")
        source = f"/archivo/{archivo}"
        page = VIEWER.replace("__SRC__", json.dumps(source)).replace("__TITLE__", json.dumps(Path(archivo).stem))
        return HTMLResponse(page)

    @server.get("/archivo/{relative:path}")
    def file(relative: str):
        path = resolve_public(relative)
        if path is None:
            raise HTTPException(404, "Panorámica no encontrada")
        return FileResponse(path, media_type="image/jpeg")

    demo = build(app)
    import inspect

    mount_params = inspect.signature(gr.mount_gradio_app).parameters
    extra = {}
    if "allowed_paths" in mount_params:
        extra["allowed_paths"] = [str(OUTPUT_DIR), str(SAMPLES_DIR), str(DATA_DIR)]
    if "theme" in mount_params and "theme" not in inspect.signature(gr.Blocks.__init__).parameters:
        extra["theme"] = gr.themes.Soft(primary_hue="emerald", neutral_hue="slate")
    if "css" in mount_params and "css" not in inspect.signature(gr.Blocks.__init__).parameters:
        extra["css"] = CSS
    gr.mount_gradio_app(server, demo, path="/", **extra)
    return server, app
