import io
import json
import zipfile

from reelforge import updater
from reelforge.jobs import Job, JobContext


def _zip(sha: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        root = "rea-branch/"
        z.writestr(root, "")
        z.writestr(root + "reelforge/backend/reelforge/__main__.py", "print('hi')")
        z.writestr(root + "reelforge/backend/requirements.txt", "")
        z.writestr(root + "reelforge/backend/tests/test_x.py", "")
        z.writestr(root + "reelforge/ui/index.html", "<html></html>")
        z.writestr(root + "src/other.ts", "")
        z.comment = sha.encode()
    return buf.getvalue()


class FakeStream:
    def __init__(self, data):
        self.data, self.headers = data, {"content-length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_bytes(self, n):
        for i in range(0, len(self.data), n):
            yield self.data[i:i + n]


def test_apply_extracts_only_the_app_and_keeps_two_versions(monkeypatch):
    pip_calls = []
    monkeypatch.setattr(updater, "_pip", lambda ctx, req, label: pip_calls.append(req.name))
    for n, sha in enumerate(["a" * 40, "b" * 40, "c" * 40]):
        monkeypatch.setattr(updater, "check", lambda sha=sha: {"latest": {"sha": sha, "date": "2026-10-27T00:00:00Z"}})
        monkeypatch.setattr(updater.httpx, "stream", lambda *a, sha=sha, **k: FakeStream(_zip(sha)))
        res = updater.apply(JobContext(Job(id=f"u{n}", kind="update", title="t", lane="io")))
    dest = updater.app_dir() / ("c" * 12)
    assert res["dir"] == str(dest) and res["files"] == 3
    assert (dest / "backend" / "reelforge" / "__main__.py").is_file() and not (dest / "backend" / "tests").exists()
    assert json.loads((dest / "version.json").read_text())["sha"] == "c" * 40
    assert json.loads((updater.app_dir() / "current.json").read_text())["sha"] == "c" * 40
    assert sorted(p.name for p in updater.app_dir().iterdir() if p.is_dir()) == ["b" * 12, "c" * 12]
    assert "requirements.txt" in pip_calls
