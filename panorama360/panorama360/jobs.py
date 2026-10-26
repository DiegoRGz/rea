"""Cola de trabajos por lotes con un único trabajador en segundo plano.

Los trabajos pendientes se guardan en disco, así que si cierras la aplicación (o
se apaga la laptop) la cola continúa donde se quedó al volver a abrirla.
"""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .engine import Cancelled, Request
from .paths import DATA_DIR, OUTPUT_DIR, SAMPLES_DIR
from .postprocess import save_panorama

log = logging.getLogger(__name__)
QUEUE_FILE = DATA_DIR / "cola.json"

PENDING, RUNNING, DONE, FAILED, CANCELLED = "pendiente", "generando", "lista", "error", "cancelada"


@dataclass
class Job:
    request: dict
    batch: str
    index: int
    total: int
    sample_name: str | None = None  # si es una muestra de modelo, se guarda en muestras/
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    status: str = PENDING
    progress: float = 0.0
    message: str = ""
    result: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None

    @property
    def is_sample(self) -> bool:
        return self.sample_name is not None


class JobQueue:
    def __init__(self, engine, queue_file: Path = QUEUE_FILE, paused: bool = False):
        self.engine = engine
        self.queue_file = queue_file
        self.jobs: list[Job] = []
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.paused = paused
        self._cancel_running = False
        self._restore()
        self.worker = threading.Thread(target=self._run, name="panorama-worker", daemon=True)
        self.worker.start()

    # ------------------------------------------------------------- añadir

    def add_batch(self, request: Request, count: int, random_seeds: bool, sample_name: str | None = None) -> list[Job]:
        batch = uuid.uuid4().hex[:6]
        base_seed = request.seed if request.seed >= 0 else random.randint(0, 2**31 - 1)
        jobs = []
        for index in range(count):
            if random_seeds:
                seed = base_seed if index == 0 else random.randint(0, 2**31 - 1)
            else:
                seed = base_seed + index
            data = request.as_dict() | {"seed": seed}
            jobs.append(Job(request=data, batch=batch, index=index + 1, total=count, sample_name=sample_name))
        with self.lock:
            self.jobs.extend(jobs)
            self._persist()
        self.wake.set()
        return jobs

    # ------------------------------------------------------------ control

    def cancel(self, job_id: str) -> None:
        with self.lock:
            for job in self.jobs:
                if job.id == job_id:
                    if job.status == PENDING:
                        job.status = CANCELLED
                    elif job.status == RUNNING:
                        self._cancel_running = True
            self._persist()

    def cancel_pending(self) -> int:
        with self.lock:
            count = 0
            for job in self.jobs:
                if job.status == PENDING:
                    job.status = CANCELLED
                    count += 1
            self._persist()
            return count

    def cancel_current(self) -> None:
        with self.lock:
            if any(job.status == RUNNING for job in self.jobs):
                self._cancel_running = True

    def clear_finished(self) -> None:
        with self.lock:
            self.jobs = [job for job in self.jobs if job.status in (PENDING, RUNNING)]
            self._persist()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if not paused:
            self.wake.set()

    def retry_failed(self) -> int:
        with self.lock:
            count = 0
            for job in self.jobs:
                if job.status in (FAILED, CANCELLED):
                    job.status, job.progress, job.message = PENDING, 0.0, ""
                    count += 1
            self._persist()
        self.wake.set()
        return count

    # ------------------------------------------------------------ consultas

    def snapshot(self) -> list[Job]:
        with self.lock:
            return [Job(**asdict(job)) for job in self.jobs]

    def counts(self) -> dict[str, int]:
        with self.lock:
            result: dict[str, int] = {}
            for job in self.jobs:
                result[job.status] = result.get(job.status, 0) + 1
            return result

    def current(self) -> Job | None:
        with self.lock:
            return next((Job(**asdict(j)) for j in self.jobs if j.status == RUNNING), None)

    # ----------------------------------------------------------- trabajador

    def _next(self) -> Job | None:
        with self.lock:
            if self.paused:
                return None
            pending = [job for job in self.jobs if job.status == PENDING]
            if not pending:
                return None
            job = pending[0]
            job.status, job.progress, job.message = RUNNING, 0.0, "Iniciando…"
            self._cancel_running = False
            return job

    def _run(self) -> None:
        while True:
            job = self._next()
            if job is None:
                self.wake.wait(timeout=1.0)
                self.wake.clear()
                continue
            self._execute(job)

    def _execute(self, job: Job) -> None:
        def progress(fraction: float, message: str) -> None:
            with self.lock:
                job.progress = max(job.progress, min(fraction, 1.0))
                job.message = message

        try:
            request = Request(**job.request)
            image, info = self.engine.generate(request, progress, should_cancel=lambda: self._cancel_running)
            stamp = datetime.now()
            if job.is_sample:
                folder = SAMPLES_DIR / request.model_key
                name = f"muestra_{stamp:%Y%m%d_%H%M%S}_{job.id}.jpg"
                info["sample_name"] = job.sample_name
            else:
                folder = OUTPUT_DIR / f"{stamp:%Y-%m-%d}"
                name = f"pano_{stamp:%H%M%S}_{request.seed}_{job.id}.jpg"
            info["created"] = stamp.isoformat(timespec="seconds")
            path = save_panorama(image, folder / name, metadata=info)
            with self.lock:
                job.status, job.progress, job.result, job.finished = DONE, 1.0, str(path), time.time()
                job.message = f"Lista en {info['seconds']:.0f} s" + (" · ⚠ " + " ".join(info["warnings"]) if info["warnings"] else "")
        except Cancelled:
            with self.lock:
                job.status, job.message, job.finished = CANCELLED, "Cancelada", time.time()
        except Exception as exc:
            log.error("Fallo en el trabajo %s:\n%s", job.id, traceback.format_exc())
            with self.lock:
                job.status, job.finished = FAILED, time.time()
                job.message = _friendly_error(exc)
            if "out of memory" in str(exc).lower():
                self.engine.unload()
        finally:
            with self.lock:
                self._cancel_running = False
                self._persist()

    # --------------------------------------------------------- persistencia

    def _persist(self) -> None:
        keep = [asdict(job) for job in self.jobs if job.status in (PENDING, RUNNING)]
        try:
            self.queue_file.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("No se pudo guardar la cola: %s", exc)

    def _restore(self) -> None:
        if not self.queue_file.exists():
            return
        try:
            for raw in json.loads(self.queue_file.read_text(encoding="utf-8")):
                job = Job(**raw)
                job.status, job.progress, job.message = PENDING, 0.0, "Recuperada de la sesión anterior"
                self.jobs.append(job)
        except (OSError, ValueError, TypeError) as exc:
            log.warning("No se pudo recuperar la cola anterior: %s", exc)


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    lowered = text.lower()
    if "out of memory" in lowered:
        return "Memoria de video insuficiente: elige un perfil más bajo en Sistema o una resolución menor."
    if any(word in lowered for word in ("connection", "resolve", "offline", "proxy", "timed out")):
        return "Sin conexión para descargar el modelo. Conéctate a internet la primera vez que uses cada modelo."
    if "401" in lowered or "gated" in lowered or "403" in lowered:
        return "El modelo requiere aceptar su licencia en Hugging Face o iniciar sesión (hf auth login)."
    return f"{type(exc).__name__}: {text[:300]}"
