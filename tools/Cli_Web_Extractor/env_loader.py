"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Module: env_loader.py
Description: Minimal .env loader for the Cli_Web_Extractor tool. No hardcoded
             keys of any kind — this only reads whatever the caller's own
             .env file (or OS environment) already provides.
Version:     1.0.0
Credit: Elton Boehnen (boehnenelton2024@gmail.com)
"""

import os


def load_dotenv(env_path=".env"):
    """Load KEY=VALUE lines from env_path into os.environ. Silently returns
    an empty dict if the file doesn't exist -- callers fall back to whatever
    is already in the OS environment."""
    if not os.path.exists(env_path):
        return {}
    loaded = {}
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and val:
                    os.environ.setdefault(key, val)
                    loaded[key] = val
    except Exception as e:
        print(f"WARN: Error reading {env_path}: {e}")
    return loaded
