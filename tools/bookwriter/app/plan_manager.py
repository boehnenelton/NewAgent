"""
Library:        plan_manager.py
Project:        Cli_Bookwriter
Description:    Name-based writing-plan CRUD. A plan is a BEJSON 104a
                 document (Records_Type ["PlanTask"], one row per chapter:
                 Task_ID, Task_Name, Is_Ready, Is_Audit, Author_ID) with
                 custom headers Writing_Type/Writing_Category/Writing_Title/
                 Book_Goal/Section_Count — the same PlanTask/BookPlan shape
                 AuthorCMS uses. Stored at data/plans/<name>.json exactly as
                 the update request specifies.
Version:        1.0.0
Date:           2026-08-05
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  0d1e2f3a-4b5c-4d6e-7f8a-9b0c1d2e3f44
"""

import json
import re
from pathlib import Path

PLAN_TASK_FIELDS = [
    {"name": "Task_ID", "type": "string"},
    {"name": "Task_Name", "type": "string"},
    {"name": "Is_Ready", "type": "boolean"},
    {"name": "Is_Audit", "type": "boolean"},
    {"name": "Author_ID", "type": "string"},
]

DEFAULT_CHAPTER_COUNT = 8

PLAN_PROMPT_TEMPLATE = """Generate a detailed writing plan in BEJSON 104a format for a book about "{topic}".
The plan should have exactly {chapter_count} chapters.
You MUST return ONLY a valid JSON object (no markdown fences, no prose) matching this interface:
{{
  "Format": "BEJSON", "Format_Version": "104a", "Format_Creator": "Elton Boehnen",
  "Records_Type": ["PlanTask"],
  "Fields": [{{"name": "Task_ID", "type": "string"}}, {{"name": "Task_Name", "type": "string"}}, {{"name": "Is_Ready", "type": "boolean"}}, {{"name": "Is_Audit", "type": "boolean"}}, {{"name": "Author_ID", "type": "string"}}],
  "Writing_Type": "standard book", "Writing_Category": "Non-Fiction", "Writing_Title": "...", "Book_Goal": "...", "Section_Count": {chapter_count},
  "Values": [
    ["TASK1", "Chapter 1: ...", false, false, ""],
    ...
  ]
}}
Context: {context}
"""


class PlanNotFoundError(Exception):
    pass


class PlanManager:
    def __init__(self, dir_plans: Path):
        self.dir_plans = dir_plans

    def _load_bejson_core_lib(self):
        import lib_bejson_Core_bejson_core as BEJSONCore
        return BEJSONCore

    def _plan_file_path(self, plan_name: str) -> Path:
        safe_plan_name = re.sub(r"[^A-Za-z0-9_\-]", "_", plan_name)
        return self.dir_plans / f"{safe_plan_name}.json"

    def plan_exists(self, plan_name: str) -> bool:
        return self._plan_file_path(plan_name).exists()

    def list_plan_names(self):
        return sorted(plan_file_path.stem for plan_file_path in self.dir_plans.glob("*.json"))

    def load_plan(self, plan_name: str) -> dict:
        plan_file_path = self._plan_file_path(plan_name)
        if not plan_file_path.exists():
            raise PlanNotFoundError(
                f"Plan '{plan_name}' not found in data/plans/. "
                f"Run --generate-plan \"<prompt>\" first, or check --list-plans."
            )
        bejson_core_lib = self._load_bejson_core_lib()
        return bejson_core_lib.bejson_core_load_file(str(plan_file_path))

    def build_prompt(self, topic: str, chapter_count: int, context_text: str) -> str:
        return PLAN_PROMPT_TEMPLATE.format(
            topic=topic, chapter_count=chapter_count,
            context=(context_text if context_text else "(no additional context supplied)"),
        )

    def parse_ai_response(self, ai_response_text: str) -> dict:
        json_match = re.search(r"\{[\s\S]*\}", ai_response_text)
        matched_json_text = json_match.group(0) if json_match else ai_response_text
        plan_doc = json.loads(matched_json_text)
        plan_doc.setdefault("Format", "BEJSON")
        plan_doc.setdefault("Format_Version", "104a")
        plan_doc.setdefault("Format_Creator", "Elton Boehnen")
        plan_doc.setdefault("Records_Type", ["PlanTask"])
        plan_doc.setdefault("Fields", PLAN_TASK_FIELDS)
        return plan_doc

    def save_plan(self, plan_name: str, plan_doc: dict) -> Path:
        plan_file_path = self._plan_file_path(plan_name)
        bejson_core_lib = self._load_bejson_core_lib()
        bejson_core_lib.bejson_core_atomic_write(str(plan_file_path), plan_doc)
        return plan_file_path
