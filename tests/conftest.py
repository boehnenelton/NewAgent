"""
Name:           conftest.py
Description:    Puts lib/ on sys.path for every test in this directory,
                 matching the convention already used under
                 tools/NA-CMS/tests/ (root-relative sys.path.insert per
                 test file) but centralized once via pytest's conftest.py
                 auto-discovery instead of repeating the insert in every
                 file.
Version:        1.0
Date:           2026-09-29
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  9986705c-61ba-4dc2-b723-cac4240df2a4
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
