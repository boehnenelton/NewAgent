"""
Library:        context_manager.py
Project:        Cli_Bookwriter
Description:    Context attachment for book writing. Tracked files/folders
                 are copied into data/context/bubble/ and recorded in a
                 persistent BEJSON 104a tracking file, same shape as
                 AuthorCMS_CLI's context bubble — but here nothing auto-
                 clears after a generation call, since the whole point is
                 the same attached context gets reused across every chapter
                 of a book-writing session. Each tracked item also carries
                 an is_active flag: --select-context-* toggles which
                 tracked items are actually folded into the next prompt,
                 without having to delete/re-add anything.
Version:        1.0.0
Date:           2026-08-05
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  9c0d1e2f-3a4b-4c5d-6e7f-8a9b0c1d2e33
"""

import shutil
import time
import uuid
from pathlib import Path

CONTEXT_TRACKING_FIELDS = [
    {"name": "entry_id", "type": "string"},
    {"name": "item_type", "type": "string"},       # "file" | "folder"
    {"name": "source_path", "type": "string"},
    {"name": "bubble_rel_path", "type": "string"},
    {"name": "is_active", "type": "boolean"},
    {"name": "added_date", "type": "string"},
]

EXCLUDED_FOLDER_NAMES = {".git", "node_modules", "__pycache__"}
MAX_CONTEXT_CHARS = 40000


class ContextManager:
    def __init__(self, dir_context: Path, dir_bubble: Path):
        self.dir_context = dir_context
        self.dir_bubble = dir_bubble
        self.context_tracking_path = dir_context / "context_tracking.104a.bejson"
        self._bejson_core_lib = None
        self._context_tracking_doc = None
        self._load_context_tracking_doc()

    def _load_bejson_core_lib(self):
        if self._bejson_core_lib is None:
            import lib_bejson_Core_bejson_core as BEJSONCore
            self._bejson_core_lib = BEJSONCore
        return self._bejson_core_lib

    def _load_context_tracking_doc(self):
        bejson_core_lib = self._load_bejson_core_lib()
        if self.context_tracking_path.exists():
            self._context_tracking_doc = bejson_core_lib.bejson_core_load_file(str(self.context_tracking_path))
        if not self._context_tracking_doc:
            self._context_tracking_doc = {
                "Format": "BEJSON", "Format_Version": "104a", "Format_Creator": "Elton Boehnen",
                "Records_Type": ["ContextItem"],
                "Fields": CONTEXT_TRACKING_FIELDS,
                "Values": [],
            }
            self._save_context_tracking_doc()

    def _save_context_tracking_doc(self):
        self._load_bejson_core_lib().bejson_core_atomic_write(str(self.context_tracking_path), self._context_tracking_doc)

    def _current_timestamp(self):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def files(self):
        return [tracking_row for tracking_row in self._context_tracking_doc["Values"] if tracking_row[1] == "file"]

    def folders(self):
        return [tracking_row for tracking_row in self._context_tracking_doc["Values"] if tracking_row[1] == "folder"]

    def _next_available_bubble_path(self, stem: str, suffix: str, folder_mode: bool = False):
        duplicate_suffix_counter = 0
        candidate_bubble_path = self.dir_bubble / (stem if folder_mode else f"{stem}{suffix}")
        while candidate_bubble_path.exists():
            duplicate_suffix_counter += 1
            candidate_bubble_path = self.dir_bubble / (
                f"{stem}_{duplicate_suffix_counter}" if folder_mode else f"{stem}_{duplicate_suffix_counter}{suffix}")
        return candidate_bubble_path

    def add_file(self, source_path: str):
        source_file_path = Path(source_path).expanduser().resolve()
        if not source_file_path.is_file():
            raise FileNotFoundError(f"Not a file: {source_file_path}")
        bubble_copy_path = self._next_available_bubble_path(source_file_path.stem, source_file_path.suffix)
        shutil.copy2(source_file_path, bubble_copy_path)
        bubble_relative_path = bubble_copy_path.relative_to(self.dir_bubble)
        tracking_row = [str(uuid.uuid4())[:8], "file", str(source_file_path), str(bubble_relative_path),
                         True, self._current_timestamp()]
        self._context_tracking_doc["Values"].append(tracking_row)
        self._save_context_tracking_doc()
        return tracking_row

    def add_folder(self, source_path: str):
        source_folder_path = Path(source_path).expanduser().resolve()
        if not source_folder_path.is_dir():
            raise NotADirectoryError(f"Not a folder: {source_folder_path}")
        bubble_copy_path = self._next_available_bubble_path(source_folder_path.name, "", folder_mode=True)
        shutil.copytree(source_folder_path, bubble_copy_path,
                         ignore=shutil.ignore_patterns(*EXCLUDED_FOLDER_NAMES))
        bubble_relative_path = bubble_copy_path.relative_to(self.dir_bubble)
        tracking_row = [str(uuid.uuid4())[:8], "folder", str(source_folder_path), str(bubble_relative_path),
                         True, self._current_timestamp()]
        self._context_tracking_doc["Values"].append(tracking_row)
        self._save_context_tracking_doc()
        return tracking_row

    def _resolve_row(self, rows, name_or_index: str):
        """Selection/removal accepts either a numeric index into the given
        row list, or a case-insensitive match against the tracked item's
        display name (source basename)."""
        try:
            numeric_index = int(name_or_index)
            if 0 <= numeric_index < len(rows):
                return rows[numeric_index]
        except ValueError:
            pass
        lowered_query = name_or_index.lower()
        for tracking_row in rows:
            source_basename = Path(tracking_row[2]).name
            if source_basename.lower() == lowered_query:
                return tracking_row
        raise IndexError(f"No tracked context item matches '{name_or_index}'.")

    def toggle_active_file(self, name_or_index: str, active: bool):
        tracking_row = self._resolve_row(self.files(), name_or_index)
        tracking_row[4] = active
        self._save_context_tracking_doc()
        return tracking_row

    def toggle_active_folder(self, name_or_index: str, active: bool):
        tracking_row = self._resolve_row(self.folders(), name_or_index)
        tracking_row[4] = active
        self._save_context_tracking_doc()
        return tracking_row

    def remove_file(self, name_or_index: str):
        tracking_row = self._resolve_row(self.files(), name_or_index)
        self._remove_tracking_row(tracking_row)

    def remove_folder(self, name_or_index: str):
        tracking_row = self._resolve_row(self.folders(), name_or_index)
        self._remove_tracking_row(tracking_row)

    def _remove_tracking_row(self, tracking_row):
        bubble_target_path = self.dir_bubble / tracking_row[3]
        if bubble_target_path.is_dir():
            shutil.rmtree(bubble_target_path, ignore_errors=True)
        elif bubble_target_path.is_file():
            bubble_target_path.unlink(missing_ok=True)
        self._context_tracking_doc["Values"].remove(tracking_row)
        self._save_context_tracking_doc()

    def build_active_context_text(self) -> str:
        """Concatenates the readable content of every active tracked item
        (files, and every non-binary file inside active folders) into a
        single context string, truncated to MAX_CONTEXT_CHARS. Returns ""
        if nothing is active."""
        context_sections = []
        for tracking_row in self._context_tracking_doc["Values"]:
            if not tracking_row[4]:
                continue
            item_display_name = Path(tracking_row[2]).name
            bubble_item_path = self.dir_bubble / tracking_row[3]
            if tracking_row[1] == "file":
                file_text = self._read_text_best_effort(bubble_item_path)
                if file_text is not None:
                    context_sections.append(f"--- FILE: {item_display_name} ---\n{file_text}")
            else:
                for nested_file_path in sorted(bubble_item_path.rglob("*")):
                    if not nested_file_path.is_file():
                        continue
                    if any(excluded_name in nested_file_path.parts for excluded_name in EXCLUDED_FOLDER_NAMES):
                        continue
                    nested_file_text = self._read_text_best_effort(nested_file_path)
                    if nested_file_text is not None:
                        nested_display_path = f"{item_display_name}/{nested_file_path.relative_to(bubble_item_path)}"
                        context_sections.append(f"--- FILE: {nested_display_path} ---\n{nested_file_text}")
        combined_context_text = "\n\n".join(context_sections)
        return combined_context_text[:MAX_CONTEXT_CHARS]

    @staticmethod
    def _read_text_best_effort(file_path: Path):
        try:
            return file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return None
