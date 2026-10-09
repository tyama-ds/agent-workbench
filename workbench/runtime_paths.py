"""Source resource boundaries, retaining historical frozen-build regression cases."""
from pathlib import Path
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
RESOURCE_ROOT = Path(__file__).resolve().parents[1]
INSTALL_ROOT = Path(sys.executable).resolve().parent if FROZEN else RESOURCE_ROOT
PROTECTED_ROOTS = tuple(dict.fromkeys((RESOURCE_ROOT, INSTALL_ROOT)))
