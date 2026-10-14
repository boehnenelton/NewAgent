"""
Name:           _libpath.py
Description:    Puts lib/ on sys.path. Imported (for its side effect) by every
                 test module so BOTH `python3 -m pytest tests` and
                 `python3 -m unittest discover -s tests` can resolve lib_*
                 modules -- conftest.py is pytest-only and is not loaded by
                 unittest discovery.
Version:        1.0
Date:           2026-10-13
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  b5d1e2a0-6c1f-4f0e-9a3b-0f6b9d7a41c2
"""
import sys
from pathlib import Path

_LIB = str(Path(__file__).resolve().parent.parent / "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
