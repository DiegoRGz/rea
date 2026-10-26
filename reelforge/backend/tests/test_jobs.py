import time

from reelforge import gpu
from reelforge.jobs import Job, JobContext


def test_model_loading_reports_live_progress():
    job = Job(id="k", kind="tts", title="t", lane="gpu")
    ctx = JobContext(job)
    seen = []

    def slow_loader():
        for _ in range(3):
            time.sleep(1.05)
            seen.append((job.progress, job.message))
        return object()

    gpu.release()
    gpu.acquire("slow-test-model", slow_loader, ctx, "Cargando prueba")
    gpu.release()
    progress = [p for p, _ in seen]
    assert progress == sorted(progress) and progress[-1] > progress[0]
    assert all(m.startswith("Cargando prueba") and " s" in m for _, m in seen[1:])
