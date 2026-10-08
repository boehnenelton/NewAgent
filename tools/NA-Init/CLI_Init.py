"""
Name:           CLI_Init.py
Family:         NewAgent
Description:    Standalone INIT CLI -- scaffolds/updates a project's
                 context.bejson from any directory, without needing a
                 running NewAgent chat session. Same file, same schema, and
                 the exact same upsert engine (upsert_cwd_context_section)
                 as the in-session /init command and any bejson_* work the
                 model does on context.bejson mid-conversation -- this tool,
                 the slash command, and the model's own edits all converge
                 on one file with one set of rules, so nothing forks.
Version:        1.0.0
Date:           2026-08-16
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  e4b8d1a6-9c3f-4e7b-a5d2-1f9c6b8e3a72

CHANGELOG:
- 1.0.0 (2026-08-16): Initial version, per Elton's INIT request: "CREATE
  CLI tool to play INIT in any directory" and "anytime he's given important
  project instructions like the purpose of a project our main rules,
  inject those in the directory structure of the project in a init." Ties
  into context.bejson (already auto-injected every turn by
  build_cwd_context_section -- no keyword trigger, no cooldown, always on)
  rather than inventing a second parallel init file format.
"""

import argparse
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_PATH.parent.parent / "lib"))

import lib_bejson_newagent_context_bubble as bubble

VERSION = "1.0.0"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="CLI_Init.py",
        description=(
            "Scaffold or update a project's context.bejson (the same file "
            "NewAgent auto-injects into every turn's context when it's "
            "working in that directory). Safe to run more than once -- "
            "existing sections are updated in place, not duplicated."
        ),
    )
    parser.add_argument("directory", help="Target project directory (must already exist).")
    parser.add_argument("--purpose", help="Sets the 'Purpose' section -- what this project is / is for.")
    parser.add_argument("--rules", help="Sets the 'Rules' section -- ground rules/constraints for this project.")
    parser.add_argument(
        "--set", metavar="SECTION=CONTENT", action="append", default=[],
        help="Set an arbitrary section, e.g. --set \"Stack=Python 3.11, Flask, BEJSON 104a\". Repeatable.",
    )
    args = parser.parse_args()

    target = Path(args.directory)
    if not target.is_dir():
        print(f"[ERROR] {target} is not an existing directory.", file=sys.stderr)
        return 1

    pairs: list[tuple[str, str]] = []
    if args.purpose:
        pairs.append(("Purpose", args.purpose))
    if args.rules:
        pairs.append(("Rules", args.rules))
    for raw in args.set:
        if "=" not in raw:
            print(f"[ERROR] --set \"{raw}\" needs an '=' — format is SECTION=CONTENT.", file=sys.stderr)
            return 1
        section, content = raw.split("=", 1)
        section = section.strip()
        if not section:
            print(f"[ERROR] --set \"{raw}\" has an empty section name.", file=sys.stderr)
            return 1
        pairs.append((section, content))

    if not pairs:
        # No content given -- just scaffold the empty file (mirrors /init).
        ok, msg = bubble.init_cwd_context_template(str(target))
        print(msg, file=sys.stderr if not ok else sys.stdout)
        return 0 if ok else 1

    exit_code = 0
    for section, content in pairs:
        ok, msg = bubble.upsert_cwd_context_section(str(target), section, content)
        print(msg, file=sys.stderr if not ok else sys.stdout)
        if not ok:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
