#!/usr/bin/env bash
# Instalación para Linux y macOS. Crea .venv junto a la aplicación.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
if [ -z "$PY" ]; then
  echo "No se encontró Python 3.11/3.12. Instálalo y vuelve a ejecutar este script." >&2
  exit 1
fi

[ -d .venv ] || "$PY" -m venv .venv
VPY=.venv/bin/python
"$VPY" -m pip install --upgrade pip

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "GPU NVIDIA detectada: instalando PyTorch con CUDA…"
  "$VPY" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
elif [ "$(uname -s)" = "Darwin" ]; then
  echo "macOS: instalando PyTorch con soporte Metal (MPS)…"
  "$VPY" -m pip install torch torchvision
else
  echo "Sin GPU NVIDIA: instalando PyTorch para CPU (será lento)…"
  "$VPY" -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
fi
"$VPY" -m pip install -r requirements.txt

echo
echo "Listo. Ejecuta ./iniciar.sh para abrir la aplicación."
echo "(La primera generación descarga el modelo elegido, unos 7 GB.)"
