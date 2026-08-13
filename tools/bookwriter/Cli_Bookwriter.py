#!/usr/bin/env python3
"""
Library:        Cli_Bookwriter.py
Project:        Cli_Bookwriter
Description:    Chapter-by-chapter book writing CLI, modeled on AuthorCMS's
                 plan -> chapter-task -> chained-context generation flow, per
                 the "Update Request for CLI web extractor" plan doc
                 (Cli_Bookwriter half only — the web extractor is a separate,
                 library-free tool and out of scope here). Single-shot
                 argparse CLI (call it once per step from the shell); state
                 that needs to survive between calls (which plan is active)
                 persists under data/persist/.

                 No author-profile system, no book "library" step, no image
                 generation — per spec, output is a single combined HTML
                 file per book, chapters written from a named plan, each
                 chapter chained to the plan scope + the previous chapter's
                 content.
Version:        1.0.0
Date:           2026-08-05
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  2f3a4b5c-6d7e-4f8a-9b0c-1d2e3f4a5b66

Changelog:
  1.0.0 - Initial build per CLI_PLAN_BOOK_CMS.md. Name-based plans
          (data/plans/<name>.json), resumable chapter-by-chapter book
          writing (books/BEJSON/<name>.bejson working record ->
          books/HTML/<name>.html single-file output), a persistent
          select/add/remove context system (data/context/), and Gemini
          keys pulled from secure/.env first, then the device-wide BEJSON
          env-file convention, then plain OS environment variables.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))

import config  # noqa: E402

config.bootstrap_dirs()
config.bootstrap_lib_path()

import key_loader        # noqa: E402
import gemini_client      # noqa: E402
import state as state_mod  # noqa: E402
import context_manager    # noqa: E402
import plan_manager       # noqa: E402
import book_writer        # noqa: E402

RED = "\033[38;2;222;38;38m"
RESET = "\033[0m"
BOLD = "\033[1m"


def status(message, ok=True):
    tag_color = "" if ok else RED
    tag_text = "OK" if ok else "ERROR"
    print(f"[{tag_color}{tag_text}{RESET if not ok else ''}] {message}")


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="Cli_Bookwriter.py",
        description="Chapter-by-chapter book writing CLI (BEJSON-backed, AuthorCMS-derived).",
    )
    plan_group = parser.add_argument_group("Plan")
    plan_group.add_argument("--new-plan", metavar="NAME", help="Name and select a new plan slot.")
    plan_group.add_argument("--select-plan", metavar="NAME", help="Select an existing plan by name.")
    plan_group.add_argument("--generate-plan", metavar="PROMPT",
                             help="Generate the active plan's chapters via AI.")
    plan_group.add_argument("--chapters", metavar="N", type=int, default=plan_manager.DEFAULT_CHAPTER_COUNT,
                             help=f"Chapter count for --generate-plan (default {plan_manager.DEFAULT_CHAPTER_COUNT}).")
    plan_group.add_argument("--view-plan", action="store_true", help="Print the active plan's chapters.")
    plan_group.add_argument("--list-plans", action="store_true", help="List all saved plan names.")

    book_group = parser.add_argument_group("Book writing")
    book_group.add_argument("--write-book", action="store_true", help="Write (or continue) the active plan's book.")
    book_group.add_argument("--resume-plan", action="store_true",
                             help="Same as --write-book — resumes from the last written chapter.")
    book_group.add_argument("--auto-run", choices=["on", "off", "true", "false", "1", "0"], nargs="?", const="on",
                             help="Set or check persistent auto-run toggle (default 'on' when passed without value).")


    context_group = parser.add_argument_group("Context")
    context_group.add_argument("--add-context-file", "--Add-Context-File", "--acf", metavar="PATH", dest="add_context_file")
    context_group.add_argument("--add-context-folder", "--Add-Context-Folder", "--acd", metavar="PATH", dest="add_context_folder")
    context_group.add_argument("--select-context-file", "--Select-Context-File", "--scf", metavar="NAME_OR_INDEX", dest="select_context_file")
    context_group.add_argument("--select-context-folder", "--Select-Context-Folder", "--scd", metavar="NAME_OR_INDEX", dest="select_context_folder")
    context_group.add_argument("--deselect-context-file", "--dcf", metavar="NAME_OR_INDEX", dest="deselect_context_file",
                                help="Marks a tracked file inactive without removing it.")
    context_group.add_argument("--deselect-context-folder", "--dcd", metavar="NAME_OR_INDEX", dest="deselect_context_folder")
    context_group.add_argument("--remove-context-file", "--Remove-Context-File", "--rcf", metavar="NAME_OR_INDEX", dest="remove_context_file")
    context_group.add_argument("--remove-context-folder", "--Remove-Context-Folder", "--rcd", metavar="NAME_OR_INDEX", dest="remove_context_folder")
    context_group.add_argument("--list-context", action="store_true", help="List all tracked context files/folders.")

    misc_group = parser.add_argument_group("Misc")
    misc_group.add_argument("--model", default=gemini_client.DEFAULT_MODEL, help="Gemini model id.")
    misc_group.add_argument("--export-env-template", metavar="PATH", nargs="?", const="secure/.env.template",
                             help="Export a clean .env template file (default: secure/.env.template).")
    misc_group.add_argument("--status", action="store_true", help="Show current selection + key status.")
    return parser


def handle_context_mutations(args, ctx: context_manager.ContextManager):
    if args.add_context_file:
        tracking_row = ctx.add_file(args.add_context_file)
        status(f"context file added [{tracking_row[0]}]: {tracking_row[2]}")
    if args.add_context_folder:
        tracking_row = ctx.add_folder(args.add_context_folder)
        status(f"context folder added [{tracking_row[0]}]: {tracking_row[2]}")
    if args.select_context_file:
        ctx.toggle_active_file(args.select_context_file, True)
        status(f"context file '{args.select_context_file}' selected (active).")
    if args.select_context_folder:
        ctx.toggle_active_folder(args.select_context_folder, True)
        status(f"context folder '{args.select_context_folder}' selected (active).")
    if args.deselect_context_file:
        ctx.toggle_active_file(args.deselect_context_file, False)
        status(f"context file '{args.deselect_context_file}' deselected (inactive).")
    if args.deselect_context_folder:
        ctx.toggle_active_folder(args.deselect_context_folder, False)
        status(f"context folder '{args.deselect_context_folder}' deselected (inactive).")
    if args.remove_context_file:
        ctx.remove_file(args.remove_context_file)
        status(f"context file '{args.remove_context_file}' removed.")
    if args.remove_context_folder:
        ctx.remove_folder(args.remove_context_folder)
        status(f"context folder '{args.remove_context_folder}' removed.")
    if args.list_context:
        print(f"  {BOLD}Files{RESET}")
        for file_index, tracking_row in enumerate(ctx.files()):
            active_marker = "*" if tracking_row[4] else " "
            print(f"  [{file_index}]{active_marker} {Path(tracking_row[2]).name}")
        print(f"  {BOLD}Folders{RESET}")
        for folder_index, tracking_row in enumerate(ctx.folders()):
            active_marker = "*" if tracking_row[4] else " "
            print(f"  [{folder_index}]{active_marker} {Path(tracking_row[2]).name}")
        print("  (* = active / included in the next generation)")


def make_generate_text_fn(api_key, model, system_instruction=None):
    def generate_text_fn(prompt_text):
        return gemini_client.generate_text(
            prompt_text, api_key=api_key, system_instruction=system_instruction, model=model)
    return generate_text_fn


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    selection_state = state_mod.SelectionState(config.DIR_PERSIST)
    ctx = context_manager.ContextManager(config.DIR_CONTEXT, config.DIR_CONTEXT_BUBBLE)
    plans = plan_manager.PlanManager(config.DIR_PLANS)
    writer = book_writer.BookWriter(config.DIR_BOOKS_BEJSON, config.DIR_BOOKS_HTML, config.DIR_TEMP)

    any_action_taken = False

    try:
        handle_context_mutations(args, ctx)
        if any(v for k, v in vars(args).items() if k.startswith(("add_context", "select_context",
                                                                   "deselect_context", "remove_context"))) or args.list_context:
            any_action_taken = True

        if args.new_plan:
            any_action_taken = True
            if plans.plan_exists(args.new_plan):
                status(f"plan '{args.new_plan}' already has a saved file — selecting it. "
                       f"Run --generate-plan to regenerate/overwrite it.", ok=True)
            selection_state.selected_plan_name = args.new_plan
            status(f"active plan set to '{args.new_plan}'.")

        if args.select_plan:
            any_action_taken = True
            if not plans.plan_exists(args.select_plan):
                status(f"plan '{args.select_plan}' not found in data/plans/. "
                       f"Use --new-plan '{args.select_plan}' --generate-plan \"...\" to create it.", ok=False)
                sys.exit(1)
            selection_state.selected_plan_name = args.select_plan
            status(f"active plan set to '{args.select_plan}'.")

        dotenv_setting = config.get_config_setting("dotenv_path", "secure/.env")

        if args.export_env_template:
            any_action_taken = True
            out_target = Path(args.export_env_template)
            if not out_target.is_absolute():
                out_target = config.SCRIPT_PATH / out_target
            exported_file = key_loader.export_env_template(out_target)
            status(f"env template exported -> {exported_file.relative_to(config.SCRIPT_PATH) if exported_file.is_relative_to(config.SCRIPT_PATH) else exported_file}")

        if args.generate_plan:
            any_action_taken = True
            active_plan_name = selection_state.selected_plan_name
            if not active_plan_name:
                status("no active plan. Run --new-plan <name> first (or --select-plan <name>).", ok=False)
                sys.exit(1)
            api_key = key_loader.load_gemini_api_key(config.SCRIPT_PATH, dotenv_rel_path=dotenv_setting)
            if not api_key:
                status(f"no Gemini API key found. Add one to {dotenv_setting} "
                        "(GEMINI_API_KEY=... or GEMINI_KEY_1=...) and try again.", ok=False)
                sys.exit(1)
            active_context_text = ctx.build_active_context_text()
            plan_prompt = plans.build_prompt(args.generate_plan, args.chapters, active_context_text)
            status(f"generating plan '{active_plan_name}' ({args.chapters} chapters)...")
            try:
                ai_response_text = gemini_client.generate_text(plan_prompt, api_key=api_key, model=args.model)
                plan_doc = plans.parse_ai_response(ai_response_text)
            except Exception as generation_error:
                status(f"plan generation failed: {generation_error}", ok=False)
                sys.exit(1)
            plan_file_path = plans.save_plan(active_plan_name, plan_doc)
            status(f"plan saved -> {plan_file_path.relative_to(config.SCRIPT_PATH)} "
                    f"({len(plan_doc.get('Values', []))} chapters).")

        if args.view_plan:
            any_action_taken = True
            active_plan_name = selection_state.selected_plan_name
            if not active_plan_name:
                status("no active plan. Run --new-plan <name> --generate-plan \"...\", "
                        "or --select-plan <name>.", ok=False)
                sys.exit(1)
            try:
                plan_doc = plans.load_plan(active_plan_name)
            except plan_manager.PlanNotFoundError as plan_error:
                status(str(plan_error), ok=False)
                sys.exit(1)
            plan_field_index_map = {field_def["name"]: field_index
                                     for field_index, field_def in enumerate(plan_doc["Fields"])}
            print(f"  {BOLD}{plan_doc.get('Writing_Title', active_plan_name)}{RESET}  [{active_plan_name}]")
            print(f"  Type: {plan_doc.get('Writing_Type')} | Category: {plan_doc.get('Writing_Category')}")
            print(f"  Goal: {plan_doc.get('Book_Goal')}")
            for chapter_number, task_row in enumerate(plan_doc.get("Values", []), start=1):
                print(f"    {chapter_number}. {task_row[plan_field_index_map['Task_Name']]}")

        if args.auto_run is not None:
            any_action_taken = True
            new_val = args.auto_run.lower() in ("on", "true", "1")
            selection_state.auto_run_tasks = new_val
            status(f"persistent auto-run toggle set to: {'ON (automatic chapter workflow)' if new_val else 'OFF (single chapter step)'}")

        if args.list_plans:
            any_action_taken = True
            plan_names = plans.list_plan_names()
            if not plan_names:
                print("  (no plans saved yet)")
            for plan_name in plan_names:
                marker = " *" if plan_name == selection_state.selected_plan_name else ""
                print(f"  {plan_name}{marker}")

        if args.write_book or args.resume_plan:
            any_action_taken = True
            active_plan_name = selection_state.selected_plan_name
            if not active_plan_name:
                status("no active plan. Run --new-plan <name> --generate-plan \"...\" first, "
                        "or --select-plan <name> to pick an existing one.", ok=False)
                sys.exit(1)
            try:
                plan_doc = plans.load_plan(active_plan_name)
            except plan_manager.PlanNotFoundError as plan_error:
                status(str(plan_error), ok=False)
                sys.exit(1)
            api_key = key_loader.load_gemini_api_key(config.SCRIPT_PATH, dotenv_rel_path=dotenv_setting)
            if not api_key:
                status(f"no Gemini API key found. Add one to {dotenv_setting} "
                        "(GEMINI_API_KEY=... or GEMINI_KEY_1=...) and try again.", ok=False)
                sys.exit(1)
            active_context_text = ctx.build_active_context_text()
            generate_text_fn = make_generate_text_fn(api_key, args.model)
            auto_run_setting = selection_state.auto_run_tasks
            try:
                _, html_output_path = writer.write_or_resume_book(
                    active_plan_name, plan_doc, active_context_text, generate_text_fn, status, auto_run=auto_run_setting)
            except Exception as writing_error:
                status(f"book writing failed: {writing_error}", ok=False)
                sys.exit(1)
            if html_output_path:
                status(f"done -> {html_output_path.relative_to(config.SCRIPT_PATH)}")

        if args.status:
            any_action_taken = True
            print(f"  active plan:     {selection_state.selected_plan_name or '(none)'}")
            print(f"  auto-run tasks:  {'ON' if selection_state.auto_run_tasks else 'OFF'}")
            print(f"  config file:     config.json (dotenv_path: {dotenv_setting})")
            print(f"  context files:   {len(ctx.files())} ({sum(1 for r in ctx.files() if r[4])} active)")
            print(f"  context folders: {len(ctx.folders())} ({sum(1 for r in ctx.folders() if r[4])} active)")
            api_key = key_loader.load_gemini_api_key(config.SCRIPT_PATH, dotenv_rel_path=dotenv_setting)
            print(f"  gemini key:      {'found' if api_key else f'NOT FOUND — check {dotenv_setting}'}")

        if not any_action_taken:
            parser.print_help()

    except (FileNotFoundError, NotADirectoryError, IndexError, ValueError) as known_error:
        status(str(known_error), ok=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
