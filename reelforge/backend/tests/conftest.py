import os
import sys
import tempfile
from pathlib import Path

_DATA = tempfile.mkdtemp(prefix="reelforge-test-")
os.environ["REELFORGE_DATA"] = _DATA
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reelforge import config  # noqa: E402

config.ensure_dirs()
