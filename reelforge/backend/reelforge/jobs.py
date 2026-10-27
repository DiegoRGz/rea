"""Cola de trabajos en segundo plano con progreso y cancelación.

Los trabajos de GPU se ejecutan de uno en uno (8 GB de VRAM no admiten dos
modelos grandes a la vez). Los renders de FFmpeg usan su propia cola.
"""

from __future__ import annotations

import queue
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


class JobCancelled(Exception):
    pass


@dataclass
class Job:
    id: str
    kind: str
    title: str
    lane: str
    status: str = "queued"  # queued | running | done | error | cancelled
    progress: float = 0.0
    message: str = "En cola"
    result: Any = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _procs: list[subprocess.Popen] = field(default_factory=list, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "progress": round(self.progress, 4),
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created": self.created,
            "finished": self.finished,
        }


class JobContext:
    def __init__(self, job: Job):
        self.job = job

    def progress(self, value: float | None = None, message: str | None = None) -> None:
        if self.job._cancel.is_set():
            raise JobCancelled()
        if value is not None:
            self.job.progress = max(0.0, min(1.0, float(value)))
        if message is not None:
            self.job.message = message

    @property
    def cancelled(self) -> bool:
        return self.job._cancel.is_set()

    def check(self) -> None:
        if self.job._cancel.is_set():
            raise JobCancelled()

    def track(self, proc: subprocess.Popen) -> None:
        self.job._procs.append(proc)

    def untrack(self, proc: subprocess.Popen) -> None:
        if proc in self.job._procs:
            self.job._procs.remove(proc)


JobFn = Callable[[JobContext], Any]


class heartbeat:
    """Mantiene vivo el progreso durante un paso bloqueante (descargas, carga de
    modelos): muestra el tiempo transcurrido y avanza la barra suavemente."""

    def __init__(self, ctx: Any, message: str, start: float | None = None, end: float | None = None,
                 detail: Callable[[], str | None] | None = None, expected: float = 90.0):
        self.job: Job | None = getattr(ctx, "job", None)
        self.message, self.detail, self.expected = message, detail, expected
        self.prefix = getattr(ctx, "prefix", "")
        # start/end son relativos al contexto: un subcontexto (p. ej. una escena) los mapea a su tramo.
        lo, hi = getattr(ctx, "start", None), getattr(ctx, "end", None)
        to_abs = (lambda v: v) if lo is None or hi is None else (lambda v: lo + (hi - lo) * v)
        base = self.job.progress if self.job else 0.0
        self.start = base if start is None else to_abs(start)
        limit = 0.95 if hi is None else hi
        self.end = min(limit, self.start + 0.1) if end is None else to_abs(end)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _run(self) -> None:
        import math

        t0 = time.time()
        while not self._stop.wait(1.0):
            if not self.job:
                return
            elapsed = time.time() - t0
            frac = 1 - math.exp(-elapsed / self.expected)
            self.job.progress = self.start + (self.end - self.start) * frac * 0.95
            extra = None
            if self.detail:
                try:
                    extra = self.detail()
                except Exception:  # noqa: BLE001
                    extra = None
            self.job.message = f"{self.prefix}{self.message} · {int(elapsed)} s" + (f" · {extra}" if extra else "")

    def __enter__(self) -> "heartbeat":
        if self.job:
            self.job.progress = self.start
            self.job.message = self.prefix + self.message
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


class JobManager:
    LANES = ("gpu", "render", "io")

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._queues: dict[str, queue.Queue] = {lane: queue.Queue() for lane in self.LANES}
        self._lock = threading.Lock()
        for lane in self.LANES:
            t = threading.Thread(target=self._worker, args=(lane,), daemon=True, name=f"jobs-{lane}")
            t.start()

    def submit(self, kind: str, title: str, fn: JobFn, lane: str = "gpu") -> Job:
        job = Job(id=uuid.uuid4().hex[:12], kind=kind, title=title, lane=lane)
        with self._lock:
            self._jobs[job.id] = job
            self._prune()
        self._queues[lane].put((job, fn))
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)
        return [j.public() for j in jobs[:50]]

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status in ("done", "error", "cancelled"):
            return False
        job._cancel.set()
        for proc in list(job._procs):
            try:
                proc.kill()
            except OSError:
                pass
        if job.status == "queued":
            job.status = "cancelled"
            job.message = "Cancelado"
            job.finished = time.time()
        return True

    def _prune(self) -> None:
        finished = [j for j in self._jobs.values() if j.finished]
        if len(finished) > 100:
            for j in sorted(finished, key=lambda j: j.finished or 0)[: len(finished) - 100]:
                self._jobs.pop(j.id, None)

    def _worker(self, lane: str) -> None:
        q = self._queues[lane]
        while True:
            job, fn = q.get()
            if job._cancel.is_set():
                continue
            job.status = "running"
            job.message = "Iniciando…"
            ctx = JobContext(job)
            try:
                job.result = fn(ctx)
                if job._cancel.is_set():
                    raise JobCancelled()
                job.status = "done"
                job.progress = 1.0
                job.message = "Completado"
            except JobCancelled:
                job.status = "cancelled"
                job.message = "Cancelado"
            except ModuleNotFoundError as exc:
                job.status = "error"
                job.error = (
                    f"Falta el paquete Python «{exc.name}». Instálalo en Modelos → "
                    "«Paquete de IA local completo» y reinicia la app."
                )
                job.message = "Error"
            except Exception as exc:  # noqa: BLE001 - se informa al usuario
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                job.message = "Error"
                traceback.print_exc()
            finally:
                job.finished = time.time()


jobs = JobManager()
