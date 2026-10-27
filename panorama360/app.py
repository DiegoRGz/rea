"""Punto de entrada: python app.py  →  abre http://127.0.0.1:7860 en el navegador."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser
from pathlib import Path

ALREADY_RUNNING_EXIT = 3


def acquire_instance_lock(path: Path):
    """Evita dos servidores a la vez: compartirían la cola y repetirían trabajos."""
    handle = open(path, "a+")  # noqa: SIM115 - se mantiene abierto mientras viva el proceso
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def main() -> None:
    parser = argparse.ArgumentParser(description="Generador local de panorámicas 360°")
    parser.add_argument("--host", default="127.0.0.1", help="127.0.0.1 = solo este equipo")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--no-browser", action="store_true", help="no abrir el navegador al iniciar")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from panorama360.paths import DATA_DIR

    lock = acquire_instance_lock(DATA_DIR / ".instancia.lock")
    if lock is None:
        print("Panorama 360° ya está abierto en otra ventana.")
        sys.exit(ALREADY_RUNNING_EXIT)
    print("Cargando Panorama 360°…")
    import uvicorn

    from panorama360.ui import create_server

    server, app = create_server()
    url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"\n  Panorama 360° listo en {url}\n  Equipo: {app.hardware.gpu_name} · perfil {app.recommended.label}\n")
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(server, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
