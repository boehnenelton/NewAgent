"""
Name:           web_common.py
Path:           web_routes/web_common.py
Description:    Shared constants, directory layout, persistent background asyncio
                loop (run_async), and describe_attachment_path() for the web terminal.
Version:        2.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  8f265734-d3bb-4f8a-97a8-ab1fe3afd753
"""

import asyncio
import threading
from pathlib import Path

VERSION = "0.14.0"

# Directories/paths -- identical layout to agent.py
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"

_background_loop = asyncio.new_event_loop()
_background_loop_thread = threading.Thread(
    target=_background_loop.run_forever, name="webagent-event-loop", daemon=True
)
_background_loop_thread.start()


def run_async(async_coroutine, timeout=None):
    """Run an async coroutine on the persistent background loop from synchronous Flask route code."""
    concurrent_future = asyncio.run_coroutine_threadsafe(
        async_coroutine, _background_loop
    )
    return concurrent_future.result(timeout=timeout)


def describe_attachment_path(raw_attachment_path: str) -> str:
    """Resolve an attachment path to its canonical absolute form and flag missing/unresolvable targets."""
    try:
        resolved_attachment_path = Path(raw_attachment_path).expanduser().resolve()
    except (OSError, RuntimeError) as resolution_error:
        return f"{raw_attachment_path}  [UNRESOLVABLE: {resolution_error}]"
    if not resolved_attachment_path.exists():
        return (
            f"{resolved_attachment_path}  [NOT FOUND -- no file exists at this path]"
        )
    return str(resolved_attachment_path)


KEYS_PATH = CONFIG_DIR / "keys.bejson"
STATE_PATH = CONFIG_DIR / "key_state.bejson"
MODELS_PATH = CONFIG_DIR / "models.bejson"
MODEL_CATALOG_PATH = CONFIG_DIR / "gemini_catalog.bejson"
LOGS_DIR = BASE_DIR / "logs"
CONTEXT_DIR = BASE_DIR / "Context"
BACKUPS_DIR = BASE_DIR / "backups"
JOBS_DIR = BASE_DIR / "jobs"
NOTES_DIR = BASE_DIR / "notes"
NOTES_FILE = NOTES_DIR / "webagent_notes.txt"

MAX_AUTO_CONTINUE = 5
