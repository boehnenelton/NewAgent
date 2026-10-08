#!/usr/bin/env python3
"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Module:      env_loader.py
Description: Simple dotenv parser for NA-WebToolkit.
Version:     1.0.0
Date:        2026-08-13
Author:      Elton Boehnen
Contact:     boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 8d7e6f5a-4b3c-2d1e-0f9a-8b7c6d5e4f3a
"""

import os


def load_dotenv(dotenv_path=None):
    """Loads key=value pairs from a .env file into os.environ."""
    if dotenv_path is None:
        dotenv_path = os.path.join(os.getcwd(), '.env')

    if not os.path.isfile(dotenv_path):
        return False

    try:
        with open(dotenv_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' in line:
                    key, val = line.split('=', 1)
                    key = key.strip()
                    val = val.strip().strip("'\"")
                    if key and key not in os.environ:
                        os.environ[key] = val
        return True
    except Exception:
        return False