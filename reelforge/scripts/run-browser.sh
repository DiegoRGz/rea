#!/usr/bin/env bash
# Ejecuta sólo el motor y abre la interfaz en el navegador (útil en Linux/macOS).
set -euo pipefail
cd "$(dirname "$0")/../backend"
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi
export REELFORGE_TOKEN="${REELFORGE_TOKEN:-$(head -c 12 /dev/urandom | od -An -tx1 | tr -d ' \n')}"
echo "Abre http://127.0.0.1:8765/?token=$REELFORGE_TOKEN"
exec .venv/bin/python -m reelforge --port 8765
