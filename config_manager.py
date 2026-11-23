#!/data/data/com.termux/files/usr/bin/python3
"""
Name:           config_manager.py
Family:         NewAgent
Description:    Dedicated 57-Column BEJSON Positional Telemetry TUI & CLI tool
                for managing all 69 NewAgent configuration options across 7
                hierarchical domain categories and 3 BEJSON 104a stores
                (config/config.json, Context/constant_config.bejson, and
                config/cliagent_config.json).
Version:        1.0.1
Date:           2026-11-14
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID:  c4a81e72-3d19-48f0-9b63-71d20e5c8a41
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def get_script_path() -> Path:
    return Path(__file__).resolve().parent


SCRIPT_PATH = get_script_path()
sys.path.insert(0, str(SCRIPT_PATH / "lib"))

import lib_bejson_newagent_config_tui as config_tui

VERSION = "1.0.1"
RELATIONAL_ID = "c4a81e72-3d19-48f0-9b63-71d20e5c8a41"
AUTHOR_CREDIT = (
    "Elton Boehnen · boehnenelton2024@gmail.com · "
    "boehnenelton2024.pages.dev · github.com/boehnenelton"
)

cli_logger = logging.getLogger("newagent.config_manager")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="config_manager.py",
        description=(
            "NewAgent 57-Column BEJSON Positional Telemetry Configuration Manager "
            "(7 Categories, 69 Options, 3 BEJSON 104a Stores)."
        ),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Display version identifier and exit.",
    )
    parser.add_argument(
        "--about",
        action="store_true",
        help="Render the 57-column About/Author screen and exit.",
    )
    parser.add_argument(
        "--config",
        type=str,
        nargs="?",
        const="SHOW_ROOT",
        help="Show the 57-column Root Config Dashboard (or specify alternate project root).",
    )
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        default=None,
        help="Render or open a specific category by index (1-7) or code (ENG, AUT, MEM, EXT, SYS, BUB, CLI).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate all 3 BEJSON 104a configuration stores and exit (0=valid, 30=invalid).",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="Probe all configured filesystem paths and render the 57-column report.",
    )
    parser.add_argument(
        "--get",
        type=str,
        default=None,
        metavar="KEY",
        help="Inspect a single configuration option in 57-column positional format.",
    )
    parser.add_argument(
        "--set",
        nargs=2,
        metavar=("KEY", "VALUE"),
        default=None,
        help="Set a configuration option value atomically and persist to its BEJSON 104a store.",
    )
    parser.add_argument(
        "--toggle",
        type=str,
        default=None,
        metavar="KEY",
        help="Toggle a BOOL option or cycle an ENUM/preset option and persist.",
    )
    parser.add_argument(
        "--reset-key",
        type=str,
        default=None,
        metavar="KEY",
        help="Reset a single configuration option to its canonical schema default.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset all 67 configuration options across all 3 stores to factory defaults.",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Create a timestamped snapshot backup of all 3 BEJSON 104a config stores in backups/.",
    )
    parser.add_argument(
        "--register",
        action="store_true",
        help="Display project registration metadata.",
    )
    return parser


def resolve_category_descriptor(
    manager_state: config_tui.NewAgentConfigManagerState,
    category_selector: str,
) -> config_tui.ConfigCategoryDescriptor | None:
    cleaned = category_selector.strip().upper()
    if cleaned.isdigit():
        idx_num = int(cleaned)
        if 1 <= idx_num <= len(manager_state.categories_list):
            return manager_state.categories_list[idx_num - 1]
    for cat_desc in manager_state.categories_list:
        if cat_desc.category_short_code.upper() == cleaned:
            return cat_desc
    return None


def main(argv_list: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="[%(levelname)s] %(message)s")
    parser = build_argument_parser()
    parsed_args = parser.parse_args(argv_list)

    if parsed_args.version:
        sys.stdout.write(f"config_manager.py v{VERSION} (Release 300) [{RELATIONAL_ID}]\n")
        return config_tui.EXIT_CODE_SUCCESS

    if parsed_args.about:
        sys.stdout.write("\n".join(config_tui.render_about_screen_lines()) + "\n")
        return config_tui.EXIT_CODE_SUCCESS

    target_root = SCRIPT_PATH
    if parsed_args.config and parsed_args.config != "SHOW_ROOT":
        candidate_root = Path(parsed_args.config).resolve()
        if candidate_root.is_file():
            candidate_root = candidate_root.parent.parent
        target_root = candidate_root

    manager_state = config_tui.NewAgentConfigManagerState(target_root)

    if parsed_args.register:
        sys.stdout.write(
            f"Project Root: {target_root}\n"
            f"Author:       {AUTHOR_CREDIT}\n"
            f"Version:      {VERSION}\n"
        )
        return config_tui.EXIT_CODE_SUCCESS

    if parsed_args.reset:
        manager_state.reset_all_stores_to_defaults()
        sys.stdout.write("\n".join(config_tui.render_root_dashboard_lines(manager_state)) + "\n")
        return config_tui.EXIT_CODE_SUCCESS

    if parsed_args.backup:
        ok, _ = manager_state.create_snapshot_backup()
        sys.stdout.write("\n".join(config_tui.render_root_dashboard_lines(manager_state)) + "\n")
        return config_tui.EXIT_CODE_SUCCESS if ok else config_tui.EXIT_CODE_ENV_FAILURE

    if parsed_args.validate:
        val_rows = manager_state.validate_all_bejson_stores()
        sys.stdout.write(
            "\n".join(config_tui.render_validation_and_probe_lines(manager_state, mode="validate")) + "\n"
        )
        all_ok = all(status_tag == "VALID_104A" for _, _, _, status_tag in val_rows)
        return config_tui.EXIT_CODE_SUCCESS if all_ok else config_tui.EXIT_CODE_VALIDATION_FAILURE

    if parsed_args.probe:
        sys.stdout.write(
            "\n".join(config_tui.render_validation_and_probe_lines(manager_state, mode="probe")) + "\n"
        )
        return config_tui.EXIT_CODE_SUCCESS

    if parsed_args.toggle:
        ok, _ = manager_state.toggle_or_cycle_option(parsed_args.toggle)
        if not ok:
            return config_tui.EXIT_CODE_VALIDATION_FAILURE
        parsed_args.get = parsed_args.toggle

    if parsed_args.reset_key:
        ok, _ = manager_state.reset_single_option(parsed_args.reset_key)
        if not ok:
            return config_tui.EXIT_CODE_VALIDATION_FAILURE
        parsed_args.get = parsed_args.reset_key

    if parsed_args.set:
        key_name, raw_val = parsed_args.set
        if key_name in config_tui.PATH_SETTING_KEYS_SET:
            cli_logger.error("Path settings must use presets or Termux file picker per Policy §8.5.")
            return config_tui.EXIT_CODE_PICKER_FAILURE
        ok, _ = manager_state.set_option_value(key_name, raw_val)
        if not ok:
            return config_tui.EXIT_CODE_VALIDATION_FAILURE
        parsed_args.get = key_name

    if parsed_args.get:
        target_key = parsed_args.get.strip()
        if target_key not in manager_state.option_metadata_registry:
            cli_logger.error("Unknown configuration key: %s", target_key)
            return config_tui.EXIT_CODE_VALIDATION_FAILURE
        opt_meta = manager_state.option_metadata_registry[target_key]
        for cat_desc in manager_state.categories_list:
            if cat_desc.category_short_code == opt_meta.category_short_code:
                row_idx = cat_desc.option_keys_order.index(target_key) + 1
                sys.stdout.write(
                    "\n".join(config_tui.render_option_inspector_lines(manager_state, cat_desc, row_idx))
                    + "\n"
                )
                return config_tui.EXIT_CODE_SUCCESS

    if parsed_args.category:
        cat_desc = resolve_category_descriptor(manager_state, parsed_args.category)
        if cat_desc is None:
            cli_logger.error("Unknown category selector: %s", parsed_args.category)
            return config_tui.EXIT_CODE_VALIDATION_FAILURE
        sys.stdout.write("\n".join(config_tui.render_category_submenu_lines(manager_state, cat_desc)) + "\n")
        return config_tui.EXIT_CODE_SUCCESS

    if parsed_args.config == "SHOW_ROOT":
        sys.stdout.write("\n".join(config_tui.render_root_dashboard_lines(manager_state)) + "\n")
        return config_tui.EXIT_CODE_SUCCESS

    controller = config_tui.PositionalConfigTUIController(manager_state)
    return controller.run_interactive_loop()


if __name__ == "__main__":
    sys.exit(main())
