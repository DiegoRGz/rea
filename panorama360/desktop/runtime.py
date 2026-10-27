"""Instalación del entorno y control del servidor local, sin interfaz gráfica.

El ejecutable es pequeño: en el primer arranque crea (con ``uv``) un Python propio con
PyTorch para tu GPU dentro de %LOCALAPPDATA%\\Panorama360 y copia allí la aplicación.
Los arranques siguientes solo encienden el servidor local y abren la ventana.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

PYTHON_VERSION = "3.12"
TORCH_INDEX = {
    "cuda": "https://download.pytorch.org/whl/cu128",
    "cpu": "https://download.pytorch.org/whl/cpu",
    "mac": None,  # PyPI ya trae soporte Metal (MPS)
}
# Tamaño aproximado de la descarga de PyTorch, solo para estimar el progreso.
TORCH_DOWNLOAD_GB = {"cuda": 3.2, "cpu": 0.4, "mac": 0.4}
ALREADY_RUNNING_EXIT = 3
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Lo que no forma parte de la aplicación instalada (pruebas, empaquetado, datos de desarrollo).
IGNORED = {"__pycache__", "tests", "desktop", ".venv", "salidas", "muestras", "datos", "build", "dist"}

STEPS = [
    ("app", "Copiando la aplicación"),
    ("python", "Preparando Python"),
    ("torch", "Instalando el motor de IA (PyTorch)"),
    ("deps", "Instalando componentes"),
]


def bundle_dir() -> Path:
    """Carpeta con los recursos empaquetados (PyInstaller) o el código fuente en desarrollo."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def default_base() -> Path:
    if override := os.environ.get("PANORAMA360_INSTALL_DIR"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Panorama360"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Panorama360"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "Panorama360"


def default_home() -> Path:
    """Carpeta visible para el usuario con sus panorámicas (Imágenes\\Panorama360)."""
    if override := os.environ.get("PANORAMA360_HOME"):
        return Path(override)
    return Path.home() / "Pictures" / "Panorama360"


@dataclass
class Gpu:
    vendor: str  # "nvidia", "apple" o "none"
    name: str = ""
    vram_gb: float = 0.0

    @property
    def variant(self) -> str:
        return {"nvidia": "cuda", "apple": "mac"}.get(self.vendor, "cpu")


def detect_gpu() -> Gpu:
    if sys.platform == "darwin" and os.uname().machine == "arm64":
        return Gpu("apple", "Apple Silicon")
    exe = shutil.which("nvidia-smi")
    if exe is None and sys.platform == "win32":
        candidate = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        exe = str(candidate) if candidate.exists() else None
    if exe:
        try:
            out = subprocess.run(
                [exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW,
            )
            first = out.stdout.strip().splitlines()[0]
            name, memory = [part.strip() for part in first.split(",")[:2]]
            return Gpu("nvidia", name, round(float(memory) / 1024, 1))
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            return Gpu("nvidia", "NVIDIA")
    return Gpu("none", "Sin GPU compatible")


@dataclass
class State:
    phase: str = "checking"  # checking | welcome | installing | starting | ready | error | busy
    step: str = ""
    steps: list = field(default_factory=lambda: [{"key": k, "label": label, "status": "pending"} for k, label in STEPS])
    progress: float = 0.0
    detail: str = ""
    log: str = ""
    error: str = ""
    url: str = ""
    gpu: dict = field(default_factory=dict)
    install_dir: str = ""
    home_dir: str = ""
    variant: str = ""


class InstallError(RuntimeError):
    pass


class Runtime:
    def __init__(self, base: Path | None = None, home: Path | None = None, uv: str | None = None):
        self.base = base or default_base()
        self.home = home or default_home()
        self.uv = uv or self._find_uv()
        self.state = State(install_dir=str(self.base), home_dir=str(self.home))
        self.lock = threading.Lock()
        self.server: subprocess.Popen | None = None
        self.cancelled = False

    # ------------------------------------------------------------- rutas

    @property
    def env_dir(self) -> Path:
        return self.base / "env"

    @property
    def app_dir(self) -> Path:
        return self.base / "app"

    @property
    def logs_dir(self) -> Path:
        return self.base / "logs"

    @property
    def state_file(self) -> Path:
        return self.base / "instalacion.json"

    def env_python(self, windowless: bool = False) -> Path:
        if sys.platform == "win32":
            return self.env_dir / "Scripts" / ("pythonw.exe" if windowless else "python.exe")
        return self.env_dir / "bin" / "python"

    @staticmethod
    def source_dir() -> Path:
        bundled = bundle_dir() / "app_src"
        return bundled if bundled.exists() else Path(__file__).resolve().parent.parent

    @staticmethod
    def _find_uv() -> str | None:
        name = "uv.exe" if sys.platform == "win32" else "uv"
        bundled = bundle_dir() / name
        return str(bundled) if bundled.exists() else shutil.which("uv")

    # ------------------------------------------------------------- estado

    def update(self, **changes) -> None:
        with self.lock:
            for key, value in changes.items():
                setattr(self.state, key, value)

    def snapshot(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(asdict(self.state)))

    def _set_step(self, key: str, status: str) -> None:
        with self.lock:
            for step in self.state.steps:
                if step["key"] == key:
                    step["status"] = status
            if status == "running":
                self.state.step = key

    # ------------------------------------------------------- instalación

    def _fingerprint(self) -> dict:
        source = self.source_dir()
        requirements = (source / "requirements.txt").read_bytes()
        digest = hashlib.sha256()
        for path in _app_files(source):
            digest.update(path.relative_to(source).as_posix().encode())
            digest.update(path.read_bytes())
        return {
            "app": digest.hexdigest()[:16],
            "requirements": hashlib.sha256(requirements).hexdigest()[:16],
            "python": PYTHON_VERSION,
        }

    def installed(self) -> dict:
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def pending_steps(self, variant: str) -> list[str]:
        current, wanted = self.installed(), self._fingerprint()
        pending = []
        if current.get("app") != wanted["app"] or not (self.app_dir / "app.py").exists():
            pending.append("app")
        if current.get("python") != wanted["python"] or not self.env_python().exists():
            pending += ["python", "torch", "deps"]
        else:
            if current.get("torch") != variant:
                pending.append("torch")
            if current.get("requirements") != wanted["requirements"]:
                pending.append("deps")
        return pending

    def needs_first_install(self, variant: str) -> bool:
        """El primer arranque (o una reparación) descarga varios GB: se pide confirmación."""
        pending = self.pending_steps(variant)
        return "python" in pending or "torch" in pending

    def install(self, variant: str) -> None:
        if self.uv is None:
            raise InstallError("No se encontró el instalador interno (uv). Vuelve a descargar Panorama 360.")
        pending = self.pending_steps(variant)
        record = self.installed()
        wanted = self._fingerprint()
        self.base.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.update(phase="installing", variant=variant, error="")
        for key, _ in STEPS:
            if key not in pending:
                self._set_step(key, "done")
        total = len(pending) or 1
        for position, key in enumerate(pending):
            if self.cancelled:
                raise InstallError("Instalación cancelada.")
            self._set_step(key, "running")
            span = (position / total, (position + 1) / total)
            getattr(self, f"_step_{key}")(variant, span)
            if key == "app":
                record["app"] = wanted["app"]
            elif key == "python":
                record["python"] = wanted["python"]
                record.pop("torch", None)
                record.pop("requirements", None)
            elif key == "torch":
                record["torch"] = variant
            elif key == "deps":
                record["requirements"] = wanted["requirements"]
            self.state_file.write_text(json.dumps(record, indent=2), encoding="utf-8")
            self._set_step(key, "done")
            self.update(progress=span[1])

    def _uv_env(self) -> dict:
        env = os.environ.copy()
        env.update({
            "UV_CACHE_DIR": str(self.base / "cache"),
            "UV_PYTHON_INSTALL_DIR": str(self.base / "python"),
            "UV_LINK_MODE": "copy",
            "UV_NO_PROGRESS": "1",
            "PYTHONUTF8": "1",
        })
        return env

    def _run(self, args: list[str], span: tuple[float, float], detail: str, expected_gb: float | None = None) -> None:
        self.update(detail=detail, progress=span[0])
        log_path = self.logs_dir / "instalacion.log"
        cache = self.base / "cache"
        start_size = _folder_size(cache) if expected_gb else 0
        with open(log_path, "a", encoding="utf-8") as log:
            log.write(f"\n$ {' '.join(args)}\n")
            log.flush()
            process = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                errors="replace", env=self._uv_env(), creationflags=NO_WINDOW,
            )
            reader = threading.Thread(target=self._pump, args=(process, log), daemon=True)
            reader.start()
            while process.poll() is None:
                if self.cancelled:
                    process.kill()
                    break
                if expected_gb:
                    downloaded = (_folder_size(cache) - start_size) / 1024**3
                    fraction = min(downloaded / expected_gb, 0.97)
                    self.update(
                        progress=span[0] + (span[1] - span[0]) * fraction,
                        detail=f"{detail} · {downloaded:.2f} de ~{expected_gb:.1f} GB",
                    )
                time.sleep(1.0)
            reader.join(timeout=5)
        if self.cancelled:
            raise InstallError("Instalación cancelada.")
        if process.returncode != 0:
            raise InstallError(f"Falló: {detail}.\n{self.snapshot()['log']}")

    def _pump(self, process: subprocess.Popen, log) -> None:
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            text = line.strip()
            if text:
                self.update(log=text[-160:])

    def _step_app(self, variant: str, span) -> None:
        self.update(detail="Copiando la aplicación…", progress=span[0])
        staging = self.base / "app.nuevo"
        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(self.source_dir(), staging, ignore=shutil.ignore_patterns(*IGNORED))
        old = self.base / "app.anterior"
        shutil.rmtree(old, ignore_errors=True)
        if self.app_dir.exists():
            self.app_dir.rename(old)
        staging.rename(self.app_dir)
        shutil.rmtree(old, ignore_errors=True)

    def _step_python(self, variant: str, span) -> None:
        shutil.rmtree(self.env_dir, ignore_errors=True)
        self._run([self.uv, "venv", "--python", PYTHON_VERSION, "--python-preference", "only-managed",
                   str(self.env_dir)], span, "Descargando Python " + PYTHON_VERSION)

    def _step_torch(self, variant: str, span) -> None:
        args = [self.uv, "pip", "install", "--python", str(self.env_python()), "torch", "torchvision"]
        if TORCH_INDEX[variant]:
            args += ["--index-url", TORCH_INDEX[variant]]
        label = {"cuda": "PyTorch para GPU NVIDIA", "cpu": "PyTorch para CPU", "mac": "PyTorch para Mac"}[variant]
        self._run(args, span, f"Descargando {label}", expected_gb=TORCH_DOWNLOAD_GB[variant])

    def _step_deps(self, variant: str, span) -> None:
        self._run([self.uv, "pip", "install", "--python", str(self.env_python()), "-r",
                   str(self.app_dir / "requirements.txt")], span, "Instalando diffusers, Gradio y demás", expected_gb=0.6)

    def reset(self) -> None:
        """Borra el entorno (no las panorámicas) para reinstalar desde cero."""
        for name in ("env", "app", "instalacion.json"):
            target = self.base / name
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            elif target.exists():
                target.unlink()

    # ------------------------------------------------------------ servidor

    def start_server(self, timeout: float = 300.0) -> str:
        port = _free_port()
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env.update({"PANORAMA360_HOME": str(self.home), "PYTHONUTF8": "1", "GRADIO_ANALYTICS_ENABLED": "False"})
        log = open(self.logs_dir / "servidor.log", "w", encoding="utf-8")
        self.server = subprocess.Popen(
            [str(self.env_python(windowless=True)), str(self.app_dir / "app.py"), "--no-browser", "--port", str(port)],
            cwd=self.app_dir, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
        )
        log.close()
        url = f"http://127.0.0.1:{port}/"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.cancelled:
                self.stop_server()
                raise InstallError("Cancelado.")
            code = self.server.poll()
            if code is not None:
                self.server = None
                if code == ALREADY_RUNNING_EXIT:
                    raise AlreadyRunning()
                raise InstallError("El motor se cerró al iniciar.\n" + self.server_log_tail())
            try:
                with urllib.request.urlopen(url, timeout=2) as response:
                    if response.status == 200:
                        return url
            except OSError:
                pass
            time.sleep(0.5)
        self.stop_server()
        raise InstallError("El motor tardó demasiado en iniciar.\n" + self.server_log_tail())

    def server_log_tail(self, lines: int = 12) -> str:
        try:
            text = (self.logs_dir / "servidor.log").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.strip().splitlines()[-lines:])

    def stop_server(self) -> None:
        process, self.server = self.server, None
        if process is None or process.poll() is not None:
            return
        if sys.platform == "win32":
            # /T cierra también los procesos hijos del servidor.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
        else:
            process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class AlreadyRunning(InstallError):
    def __init__(self):
        super().__init__("Panorama 360 ya está abierto en otra ventana.")


def _app_files(source: Path) -> list[Path]:
    files = []
    for root, dirs, names in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED)
        files += [Path(root) / name for name in sorted(names)]
    return files


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _folder_size(folder: Path) -> int:
    total = 0
    for root, _, files in os.walk(folder):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total
