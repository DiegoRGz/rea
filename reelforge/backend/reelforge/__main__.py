"""Arranque del motor: `python -m reelforge --port 8765`."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="reelforge")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    from . import config

    config.ensure_dirs()
    config.apply_environment()

    import uvicorn

    from .app import TOKEN, app

    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)

        @app.on_event("startup")
        async def ready() -> None:
            # Electron espera esta línea para saber que el motor está listo.
            print(f"REELFORGE_READY http://{args.host}:{args.port}/?token={TOKEN}", flush=True)

    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
