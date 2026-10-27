"""Panorama360.exe: ventana de escritorio con instalación guiada y la aplicación dentro.

Uso normal: doble clic. Opciones para soporte y pruebas:
  --reparar                 borra el entorno instalado y lo vuelve a crear
  --self-test INFORME.json  instala y arranca sin ventana (lo usa la compilación automática)
  --variante cuda|cpu|mac   fuerza la variante de PyTorch
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path

from runtime import AlreadyRunning, InstallError, Runtime, bundle_dir, detect_gpu


class Controller:
    def __init__(self, runtime: Runtime, variant: str | None):
        self.runtime = runtime
        self.forced_variant = variant
        self.window = None
        self.closed = False
        self.install_requested = threading.Event()
        self.worker: threading.Thread | None = None

    # ---------------------------------------------------------------- flujo

    def run(self, window) -> None:
        """Se ejecuta en un hilo aparte cuando la ventana ya existe."""
        self.window = window
        window.events.closed += self.on_closed
        gpu = detect_gpu()
        variant = self.forced_variant or gpu.variant
        self.runtime.update(gpu=asdict(gpu), variant=variant)
        if self.runtime.needs_first_install(variant):
            self.runtime.update(phase="welcome")
            self.install_requested.wait()
            if self.closed:
                return
        self._install_and_start()

    def _install_and_start(self) -> None:
        runtime = self.runtime
        try:
            variant = runtime.state.variant
            if runtime.pending_steps(variant):
                runtime.install(variant)
            runtime.update(phase="starting", detail="")
            url = runtime.start_server()
            runtime.update(phase="ready", url=url)
            time.sleep(0.7)  # deja terminar la animación de salida
            if not self.closed and self.window is not None:
                self.window.load_url(url)
        except AlreadyRunning:
            runtime.update(phase="busy")
        except InstallError as exc:
            if not self.closed:
                runtime.update(phase="error", error=str(exc))
        except Exception as exc:  # cualquier fallo debe verse en pantalla, no cerrar la ventana
            if not self.closed:
                runtime.update(phase="error", error=f"{type(exc).__name__}: {exc}")

    def _restart(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            return
        self.runtime.cancelled = False
        self.worker = threading.Thread(target=self._install_and_start, daemon=True)
        self.worker.start()

    def on_closed(self) -> None:
        self.closed = True
        self.runtime.cancelled = True
        self.install_requested.set()
        self.runtime.stop_server()


class Api:
    """Métodos que llama la pantalla de inicio (splash.html) desde JavaScript."""

    def __init__(self, controller: Controller):
        self._controller = controller

    def state(self) -> dict:
        return self._controller.runtime.snapshot()

    def install(self) -> None:
        self._controller.runtime.update(phase="installing")
        self._controller.install_requested.set()

    def cancel(self) -> None:
        self._controller.runtime.cancelled = True

    def retry(self) -> None:
        self._controller.runtime.update(phase="starting", error="")
        self._controller._restart()

    def repair(self) -> None:
        controller = self._controller
        controller.runtime.stop_server()
        controller.runtime.reset()
        controller.runtime.update(phase="installing", error="")
        controller._restart()

    def open_logs(self) -> None:
        folder = self._controller.runtime.logs_dir
        folder.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 - abre el Explorador en la carpeta de registros
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])

    def quit(self) -> None:
        if self._controller.window is not None:
            self._controller.window.destroy()


def run_gui(runtime: Runtime, variant: str | None) -> None:
    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    controller = Controller(runtime, variant)
    splash = (bundle_dir() / "splash.html").read_text(encoding="utf-8")
    window = webview.create_window(
        "Panorama 360°", html=splash, js_api=Api(controller), width=1440, height=920, min_size=(1000, 680),
        background_color="#0b1020", text_select=False,
    )
    runtime.base.mkdir(parents=True, exist_ok=True)
    webview.start(controller.run, window, private_mode=False, storage_path=str(runtime.base / "webview"))
    runtime.cancelled = True
    runtime.stop_server()


def self_test(runtime: Runtime, variant: str | None, report: Path) -> int:
    started = time.time()
    result: dict = {"ok": False}
    try:
        gpu = detect_gpu()
        variant = variant or gpu.variant
        result.update(gpu=asdict(gpu), variant=variant, pending=runtime.pending_steps(variant))
        runtime.install(variant)
        url = runtime.start_server()
        with urllib.request.urlopen(url, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
        result.update(ok=response.status == 200 and "gradio" in body.lower(), url=url, status=response.status)
        result["pending_after"] = runtime.pending_steps(variant)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        runtime.stop_server()
        result["seconds"] = round(time.time() - started, 1)
        result["server_log"] = runtime.server_log_tail(40)
        report.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if result["ok"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="Panorama360")
    parser.add_argument("--reparar", action="store_true")
    parser.add_argument("--self-test", type=Path, metavar="INFORME")
    parser.add_argument("--variante", choices=["cuda", "cpu", "mac"])
    args = parser.parse_args()
    runtime = Runtime()
    if args.reparar:
        runtime.reset()
    if args.self_test:
        return self_test(runtime, args.variante, args.self_test)
    run_gui(runtime, args.variante)
    return 0


if __name__ == "__main__":
    sys.exit(main())
