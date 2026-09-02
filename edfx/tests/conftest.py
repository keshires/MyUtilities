import sys
from pathlib import Path

_edfx_root = Path(__file__).resolve().parent.parent   # edfx/
sys.path.insert(0, str(_edfx_root / "scripts"))
sys.path.insert(0, str(_edfx_root.parent / "shared"))
