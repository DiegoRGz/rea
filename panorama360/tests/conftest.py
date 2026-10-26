import os
import sys
import tempfile
from pathlib import Path

# Los datos de prueba van a una carpeta temporal, nunca a salidas/ del usuario.
os.environ.setdefault("PANORAMA360_HOME", tempfile.mkdtemp(prefix="pano360-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
