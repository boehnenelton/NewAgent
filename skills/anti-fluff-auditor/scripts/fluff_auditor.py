#!/usr/bin/env python3
"""
Name: fluff_auditor.py
Description: CLI scanner enforcing Policy §2.7 & §3.7 Core Purpose Labeling Law.
             Identifies and reports buzzword fluff, slogans, metaphor leaks,
             and implementation flexing in files and directory trees.
Version: 100
Date Created: 2026-11-06
Author Credit: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID: 7b8c9d0e-1f2a-3b4c-5d6e-7f8a9b0c1d2e
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 57-Column Terminal Discipline Constants ─────────────────────────────────
TERMINAL_COLUMN_CEILING_INTEGER: int = 57
BOX_HORIZONTAL_SEPARATOR_LINE: str = "─" * TERMINAL_COLUMN_CEILING_INTEGER
ANSI_COLOR_RED: str = "\033[91m"
ANSI_COLOR_GREEN: str = "\033[92m"
ANSI_COLOR_YELLOW: str = "\033[93m"
ANSI_COLOR_RESET: str = "\033[0m"

# ── Prohibited Fluff Taxonomy Table ──────────────────────────────────────────
# (compiled_regex, violation_category, violation_label, required_replacement)
PROHIBITED_FLUFF_TAXONOMY_LIST: List[Tuple[re.Pattern, str, str, str]] = [
    # 1. Metaphor Leaks (Example 1)
    (
        re.compile(r"(?i)\bchamber\s+web\b"),
        "Metaphor Leak",
        "Chamber Web",
        "Use plain core purpose: 'Notes Editor'"
    ),
    (
        re.compile(r"(?i)\[\s*chamber\s*:\s*[^\]]+\]"),
        "Metaphor Leak",
        "[CHAMBER: ...]",
        "Use plain status badge: '[Active: <id>]'"
    ),
    (
        re.compile(r"(?i)\bchamber\s+unloaded\b"),
        "Metaphor Leak",
        "chamber unloaded",
        "Use plain empty state: '(No note selected)'"
    ),
    (
        re.compile(r"(?i)\bloaded\s+chamber\s+(web|gui|ui|interface|dashboard)\b"),
        "Metaphor Leak",
        "Loaded Chamber UI",
        "Use plain core purpose: 'Notes Editor'"
    ),
    (
        re.compile(r"(?i)\bunload\s+note\b"),
        "Metaphor Leak",
        "Unload Note",
        "Use plain action: 'Close Note' or 'Deselect'"
    ),

    # 2. Implementation Flexing & Bragging (Example 2)
    (
        re.compile(r"(?i)\bzero-sql\s+categorized\s+notes\s+hub\b"),
        "Implementation Flex",
        "Zero-SQL Categorized Notes Hub",
        "Use plain core purpose: 'Notes Hub'"
    ),
    (
        re.compile(r"(?i)\bzero-sql\s+(notes|hub|portal|system|app|editor)\b"),
        "Implementation Flex",
        "Zero-SQL <X>",
        "Remove storage brag; label by purpose: 'Notes Hub'"
    ),
    (
        re.compile(r"(?i)\bhigh-density\s+nosql\b"),
        "Implementation Flex",
        "High-density NoSQL",
        "Use plain functional title: 'Notes Database'"
    ),
    (
        re.compile(r"(?i)\bo\(1\)\s+(cached\s+)?data\s+engine\b"),
        "Implementation Flex",
        "O(1) Data Engine",
        "Use plain functional title: 'Data Cache' or 'Engine'"
    ),

    # 3. Pretentious Sloganeering & Marketing Hype
    (
        re.compile(r"(?i)\bdata\s+god\s+edition\b"),
        "Sloganeering",
        "Data God Edition",
        "Remove slogan; label by solid version: 'v1.5.0'"
    ),
    (
        re.compile(r"(?i)\bgod\s+tier\b"),
        "Classification Hype",
        "God Tier",
        "Use objective tier: 'Core / System Architecture' or 'Advanced'"
    ),
    (
        re.compile(r"(?i)\bvanguard\s+of\s+compute\b"),
        "Marketing Hype",
        "Vanguard of compute",
        "Remove puffery; state direct technical facts"
    ),
    (
        re.compile(r"(?i)\brevolutionary\s+(architecture|format|platform|engine)\b"),
        "Marketing Hype",
        "Revolutionary ...",
        "Use plain engineering label: 'Decoupled format'"
    ),
    (
        re.compile(r"(?i)\bworld-class\s+(engine|platform|tool|suite)\b"),
        "Marketing Hype",
        "World-class ...",
        "Remove slogan; state functional purpose directly"
    ),
    (
        re.compile(r"(?i)\bcutting-edge\b"),
        "Marketing Fluff",
        "Cutting-edge",
        "Remove puffery; describe specific engineering capabilities"
    ),
    (
        re.compile(r"(?i)\bgame-chang(er|ing)\b"),
        "Buzzword Fluff",
        "Game-changer",
        "Remove buzzword; state verified technical properties"
    ),
    (
        re.compile(r"(?i)\bbattle-hardened\s+(database|engine|framework)\b"),
        "Metaphorical Hype",
        "Battle-hardened",
        "Use objective descriptor: 'Tested' or 'Stable'"
    ),

    # 4. Over-Descriptive Category Fluff & Puffery (Violation of Purpose-Driven Labels)
    (
        re.compile(r"(?i)\b(architecture\s+&\s+)?technical\s+knowledge\s+hub\b"),
        "Category Fluff",
        "Technical Knowledge Hub",
        "Use purpose-driven label: 'Notes - (Category Name)' (e.g. 'Notes - Architecture')"
    ),
    (
        re.compile(r"(?i)\bauthoritative\s+technical\s+notes\b"),
        "Puffery Subtitle",
        "Authoritative technical notes",
        "Remove puffery; use plain purpose-driven label or omit subtitle"
    ),
    (
        re.compile(r"(?i)\bknowledge\s+hub\b"),
        "Category Fluff",
        "Knowledge Hub",
        "Use purpose-driven label: 'Notes - (Category Name)'"
    )
]

EXCLUDED_FILENAMES_SET: set[str] = {
    "anti_fluff_guard.py",
    "fluff_auditor.py",
    "readme_auditor.py",
    "readme_visual_guide.md",
    "GEMINI.md",
    "SKILL.md",
    "banned_fluff_patterns.md"
}


def audit_single_file_content(file_path_string: str) -> List[Dict[str, str]]:
    """Scan file content and return list of discovered violations."""
    target_basename_string: str = os.path.basename(file_path_string)
    if target_basename_string in EXCLUDED_FILENAMES_SET:
        return []

    discovered_violations_list: List[Dict[str, str]] = []

    try:
        with open(file_path_string, "r", encoding="utf-8", errors="ignore") as file_handle:
            file_content_lines: List[str] = file_handle.readlines()
    except Exception:
        return []

    for line_index_number, single_line_text in enumerate(file_content_lines, start=1):
        for pattern_regex, category_name, token_label, replacement_guidance in PROHIBITED_FLUFF_TAXONOMY_LIST:
            match_found = pattern_regex.search(single_line_text)
            if match_found:
                discovered_violations_list.append({
                    "file_path": file_path_string,
                    "line_number": str(line_index_number),
                    "matched_token": match_found.group(0),
                    "category": category_name,
                    "replacement": replacement_guidance
                })

    return discovered_violations_list


def scan_target_tree(target_path_string: str) -> List[Dict[str, str]]:
    """Recursively scan target file or directory for fluff violations."""
    all_violations_accumulator: List[Dict[str, str]] = []

    if os.path.isfile(target_path_string):
        return audit_single_file_content(target_path_string)

    for root_dir_path, subdirs_list, files_list in os.walk(target_path_string):
        # Skip git, cache, and virtual environment directories
        subdirs_list[:] = [d for d in subdirs_list if d not in (".git", "__pycache__", ".pytest_cache", "node_modules", "venv")]
        for single_filename in files_list:
            if single_filename.endswith((".py", ".html", ".js", ".ts", ".json", ".md")):
                full_item_path: str = os.path.join(root_dir_path, single_filename)
                violations = audit_single_file_content(full_item_path)
                all_violations_accumulator.extend(violations)

    return all_violations_accumulator


def print_57_column_banner(header_text: str) -> None:
    """Print centered header bounded by 57-column box rules."""
    print(BOX_HORIZONTAL_SEPARATOR_LINE)
    print(f" {header_text.center(55)} ")
    print(BOX_HORIZONTAL_SEPARATOR_LINE)


def main() -> int:
    """Main CLI entrypoint."""
    argument_parser = argparse.ArgumentParser(
        description="Anti-Fluff & Core Purpose Labeling Auditor (Policy §2.7 & §3.7)"
    )
    argument_parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="Target directory or file path to audit (defaults to current directory)"
    )
    argument_parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON array of discovered violations"
    )

    parsed_arguments = argument_parser.parse_args()
    target_scan_path: str = os.path.abspath(parsed_arguments.target)

    if not os.path.exists(target_scan_path):
        print(f"Error: Target path '{target_scan_path}' does not exist.", file=sys.stderr)
        return 2

    violations_found = scan_target_tree(target_scan_path)

    if parsed_arguments.json:
        import json
        print(json.dumps(violations_found, indent=2))
        return 1 if violations_found else 0

    print_57_column_banner("ANTI-FLUFF AUDITOR (POLICY §2.7 & §3.7)")
    print(f" Target : {os.path.basename(target_scan_path)}")
    print(f" Path   : {target_scan_path[:45]}...")
    print(BOX_HORIZONTAL_SEPARATOR_LINE)

    if not violations_found:
        print(f"{ANSI_COLOR_GREEN} [PASS] Zero fluff or slogan violations found.{ANSI_COLOR_RESET}")
        print(" All labels strictly adhere to Core Purpose Law.")
        print(BOX_HORIZONTAL_SEPARATOR_LINE)
        return 0

    print(f"{ANSI_COLOR_RED} [FAIL] Discovered {len(violations_found)} Core Purpose Violations:{ANSI_COLOR_RESET}")
    print(BOX_HORIZONTAL_SEPARATOR_LINE)

    for item in violations_found:
        rel_path = os.path.relpath(item["file_path"], target_scan_path)
        print(f"{ANSI_COLOR_YELLOW}• {rel_path}:{item['line_number']}{ANSI_COLOR_RESET}")
        print(f"  Category: {item['category']}")
        print(f"  Offense : '{item['matched_token']}'")
        print(f"  Remedy  : {item['replacement']}")
        print(BOX_HORIZONTAL_SEPARATOR_LINE)

    return 1


if __name__ == "__main__":
    sys.exit(main())
