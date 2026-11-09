"""Shared paths for production tests: reuse the art test fixtures and import this repo's packages."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
# ROOT goes first (packages); tests/art goes last so its test_*.py files (e.g. test_install) never shadow ours.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / 'tests' / 'art') not in sys.path:
    sys.path.append(str(ROOT / 'tests' / 'art'))
