"""
Library:        state.py
Project:        Cli_Bookwriter
Description:    Persistent selection state. Since this tool is invoked once
                 per command (no REPL), the currently active plan name has
                 to survive between separate process invocations — stored
                 as a single-row BEJSON 104a document under data/persist/.
Version:        1.0.0
Date:           2026-08-05
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  8b9c0d1e-2f3a-4b4c-5d6e-7f8a9b0c1d22
"""

from pathlib import Path

SELECTION_STATE_FIELDS = [
    {"name": "selected_plan_name", "type": "string"},
    {"name": "auto_run_tasks", "type": "boolean"},
]


class SelectionState:
    def __init__(self, dir_persist: Path):
        self.selection_state_path = dir_persist / "selection_state.104a.bejson"
        self._bejson_core_lib = None
        self._selection_state_doc = None
        self._load_selection_state_doc()

    def _load_bejson_core_lib(self):
        if self._bejson_core_lib is None:
            import lib_bejson_Core_bejson_core as BEJSONCore
            self._bejson_core_lib = BEJSONCore
        return self._bejson_core_lib

    def _load_selection_state_doc(self):
        bejson_core_lib = self._load_bejson_core_lib()
        if self.selection_state_path.exists():
            self._selection_state_doc = bejson_core_lib.bejson_core_load_file(str(self.selection_state_path))
        if not self._selection_state_doc:
            self._selection_state_doc = {
                "Format": "BEJSON", "Format_Version": "104a", "Format_Creator": "Elton Boehnen",
                "Records_Type": ["SelectionState"],
                "Fields": SELECTION_STATE_FIELDS,
                "Values": [["", False]],
            }
            self._save_selection_state_doc()
        else:
            # Ensure Fields and Values match current schema (migrating 1-col to 2-col if needed)
            val_row = self._selection_state_doc["Values"][0]
            if len(val_row) < 2:
                val_row.append(False)
                self._selection_state_doc["Fields"] = SELECTION_STATE_FIELDS
                self._save_selection_state_doc()

    def _save_selection_state_doc(self):
        self._load_bejson_core_lib().bejson_core_atomic_write(str(self.selection_state_path), self._selection_state_doc)

    @property
    def selected_plan_name(self):
        return self._selection_state_doc["Values"][0][0] or None

    @selected_plan_name.setter
    def selected_plan_name(self, plan_name):
        self._selection_state_doc["Values"][0][0] = plan_name or ""
        self._save_selection_state_doc()

    @property
    def auto_run_tasks(self) -> bool:
        return bool(self._selection_state_doc["Values"][0][1])

    @auto_run_tasks.setter
    def auto_run_tasks(self, val: bool):
        self._selection_state_doc["Values"][0][1] = bool(val)
        self._save_selection_state_doc()
