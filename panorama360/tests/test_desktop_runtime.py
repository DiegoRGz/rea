"""Lanzador de escritorio: instalación por pasos, arranque del motor e instancia única.

Se usa un ``uv`` simulado: "venv" enlaza el entorno de pruebas actual (que ya tiene
todas las dependencias) y "pip" solo escribe en el registro.
"""

import os
import stat
import sys
import textwrap
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop"))

from runtime import AlreadyRunning, InstallError, Runtime  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="el uv simulado usa enlaces simbólicos POSIX")


def _fake_uv(folder: Path, fail_pip: bool = False) -> str:
    script = folder / "uv"
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import os, sys
        args = sys.argv[1:]
        if args[0] == "venv":
            os.symlink({sys.prefix!r}, args[-1])
            print("Using CPython")
        elif args[0] == "pip":
            print("Resolved packages:", " ".join(args[3:]))
            sys.exit(1 if {fail_pip!r} else 0)
    """))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


@pytest.fixture
def runtime(tmp_path):
    return Runtime(base=tmp_path / "base", home=tmp_path / "home", uv=_fake_uv(tmp_path))


def test_install_runs_every_step_once_then_nothing(runtime):
    assert runtime.needs_first_install("cpu")
    runtime.install("cpu")
    assert [s["status"] for s in runtime.snapshot()["steps"]] == ["done"] * 4
    assert (runtime.app_dir / "app.py").exists()
    assert not (runtime.app_dir / "tests").exists() and not (runtime.app_dir / "desktop").exists()
    assert runtime.pending_steps("cpu") == []
    # Cambiar de variante solo reinstala PyTorch.
    assert runtime.pending_steps("cuda") == ["torch"]
    log = (runtime.logs_dir / "instalacion.log").read_text()
    assert "--index-url https://download.pytorch.org/whl/cpu" in log


def test_failed_step_reports_the_tool_output(tmp_path):
    rt = Runtime(base=tmp_path / "base", home=tmp_path / "home", uv=_fake_uv(tmp_path, fail_pip=True))
    with pytest.raises(InstallError, match="PyTorch"):
        rt.install("cpu")
    assert rt.pending_steps("cpu") == ["torch", "deps"]  # lo ya hecho no se repite


def test_server_starts_serves_and_enforces_single_instance(runtime):
    runtime.install("cpu")
    url = runtime.start_server(timeout=180)
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            assert response.status == 200
        second = Runtime(base=runtime.base, home=runtime.home, uv=runtime.uv)
        with pytest.raises(AlreadyRunning):
            second.start_server(timeout=120)
    finally:
        process = runtime.server
        runtime.stop_server()
    assert process is not None and process.poll() is not None
    assert (runtime.home / "salidas").is_dir()


def test_reset_keeps_user_panoramas(runtime):
    runtime.install("cpu")
    (runtime.home / "salidas").mkdir(parents=True)
    (runtime.home / "salidas" / "mia.jpg").write_bytes(b"x")
    runtime.reset()
    assert runtime.needs_first_install("cpu")
    assert (runtime.home / "salidas" / "mia.jpg").exists()


def test_environment_uses_the_bundled_python_when_present(tmp_path, monkeypatch):
    import runtime as runtime_module

    bundle = tmp_path / "bundle"
    (bundle / "python" / "bin").mkdir(parents=True)
    (bundle / "python" / "bin" / "python3").symlink_to(sys.executable)
    monkeypatch.setattr(runtime_module, "bundle_dir", lambda: bundle)
    rt = Runtime(base=tmp_path / "base", home=tmp_path / "home", uv=_fake_uv(tmp_path))
    rt.install("cpu")
    log = (rt.logs_dir / "instalacion.log").read_text()
    venv_line = next(line for line in log.splitlines() if " venv " in line)
    assert str(bundle / "python" / "bin" / "python3") in venv_line
    assert "only-managed" not in venv_line  # sin descarga de Python ni junctions
