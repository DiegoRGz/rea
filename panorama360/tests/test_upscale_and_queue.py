import time

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from panorama360.engine import Cancelled, Request
from panorama360.jobs import CANCELLED, DONE, FAILED, PENDING, JobQueue
from panorama360.upscale import Upscaler


class FakeDescriptor:
    dtype = torch.float32

    def __call__(self, x):
        return F.interpolate(x, scale_factor=4, mode="nearest")


def test_upscaler_tiles_wrap_without_seams():
    up = Upscaler({"file": "x.pth", "scale": 4, "name": "x", "url": ""}, "cpu", tile=32)
    up._model = FakeDescriptor()
    rng = np.random.default_rng(1)
    image = Image.fromarray(rng.integers(0, 255, (48, 96, 3), dtype=np.uint8))
    result = up.upscale(image, 384)
    expected = image.resize((384, 192), Image.Resampling.NEAREST)
    assert result.size == (384, 192)
    assert np.abs(np.asarray(result, dtype=int) - np.asarray(expected, dtype=int)).max() <= 1


def test_upscaler_falls_back_to_lanczos():
    up = Upscaler({"file": "x.pth", "scale": 4, "name": "x", "url": ""}, "cpu", tile=32)
    up._failed = "sin red"
    assert up.upscale(Image.new("RGB", (64, 32)), 256).size == (256, 128)


class FakeEngine:
    model_key = None

    def __init__(self, fail_on=None, delay=0.0):
        self.fail_on, self.delay, self.calls = fail_on, delay, []

    def unload(self):
        pass

    def generate(self, request, progress, should_cancel):
        self.calls.append(request.seed)
        progress(0.5, "mitad")
        end = time.time() + self.delay
        while time.time() < end:
            if should_cancel():
                raise Cancelled()
            time.sleep(0.01)
        if request.seed == self.fail_on:
            raise RuntimeError("CUDA out of memory")
        return Image.new("RGB", (64, 32), (10, 20, 30)), {"seconds": 0.1, "warnings": [], "seed": request.seed}


def _wait(queue, predicate, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        if predicate(queue.snapshot()):
            return
        time.sleep(0.05)
    raise AssertionError([(j.status, j.message) for j in queue.snapshot()])


def test_batch_runs_in_order_and_saves_files(tmp_path):
    engine = FakeEngine(fail_on=12)
    queue = JobQueue(engine, queue_file=tmp_path / "cola.json")
    jobs = queue.add_batch(Request(model_key="sdxl-base", prompt="x", seed=10), 3, random_seeds=False)
    assert [j.request["seed"] for j in jobs] == [10, 11, 12]
    _wait(queue, lambda js: all(j.status in (DONE, FAILED) for j in js))
    statuses = {j.request["seed"]: j for j in queue.snapshot()}
    assert statuses[10].status == DONE and statuses[11].status == DONE
    assert statuses[12].status == FAILED and "Memoria de video" in statuses[12].message
    saved = Image.open(statuses[10].result)
    assert saved.size == (64, 32)
    assert engine.calls == [10, 11, 12]


def test_pending_jobs_survive_restart_and_can_be_cancelled(tmp_path):
    file = tmp_path / "cola.json"
    queue = JobQueue(FakeEngine(delay=5), queue_file=file, paused=True)
    queue.add_batch(Request(model_key="sdxl-base", prompt="x", seed=-1), 4, random_seeds=True)
    seeds = [j.request["seed"] for j in queue.snapshot()]
    assert len(set(seeds)) == 4 and all(s >= 0 for s in seeds)

    restored = JobQueue(FakeEngine(), queue_file=file, paused=True)
    assert [j.request["seed"] for j in restored.snapshot()] == seeds
    assert all(j.status == PENDING for j in restored.snapshot())
    assert restored.cancel_pending() == 4
    assert all(j.status == CANCELLED for j in restored.snapshot())


def test_cancel_running_job(tmp_path):
    queue = JobQueue(FakeEngine(delay=5), queue_file=tmp_path / "cola.json")
    queue.add_batch(Request(model_key="sdxl-base", prompt="x", seed=1), 1, random_seeds=False)
    _wait(queue, lambda js: js[0].status == "generando")
    queue.cancel_current()
    _wait(queue, lambda js: js[0].status == CANCELLED)
