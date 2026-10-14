#!/usr/bin/env python3
"""
Name:           key_admin.py
Description:    Key Admin CLI Tool for NewAgent. Lists active keys, usage stats, blocks, and ledger history.
Version:        1.0.0
Date:           2026-10-10
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID:  2b2377ef-fa59-43dc-b45c-32bcd7829ef3
"""
import os
import sys
import argparse
from pathlib import Path

# Self-locating
def get_script_path() -> Path:
    return Path(__file__).resolve().parent

SCRIPT_PATH = get_script_path()
PROJECT_ROOT = SCRIPT_PATH.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from lib_bejson_newagent_engine_rest import KeyRegistry, sync_keys_from_env_sources
from lib_bejson_newagent_key_ledger import (
    key_ledger_parse_flags,
    key_ledger_format_flags
)

VERSION = "1.0.0"

def get_registry():
    config_dir = PROJECT_ROOT / "config"
    return KeyRegistry(keys_path=config_dir / "keys.bejson", state_path=config_dir / "key_state.bejson")

def cmd_list(args):
    reg = get_registry()
    print(f"API Key Registry: (usable {len(reg.keys)}/{len(reg.key_metadata)})")
    ordered = sorted(reg.key_metadata.items(), key=lambda kv: kv[1].get("slot") or 0)
    for k, meta in ordered:
        if str(meta.get("label", "")).startswith("REDACTED") or k.startswith(reg.PLACEHOLDER_PREFIX):
            continue
        usage = reg.usage.get(meta["key_hash"]) or {}
        state = "active" if meta.get("is_active", True) else "deactivated"
        if meta.get("cooldown_until") and meta["cooldown_until"] > reg._now():
            state = f"cooldown({int(meta['cooldown_until'] - reg._now())}s)"
        
        last_err = usage.get("usage_last_error") or ""
        out = (
            f"slot {meta.get('slot'):>3} {reg._get_key_hash(k)} {meta.get('label', ''):14} "
            f"[{meta.get('flag') or '-'}] {state:12} ok={usage.get('usage_success_count', 0)} "
            f"fail={usage.get('usage_failure_count', 0)} last={usage.get('usage_last_status') or '-'}"
        )
        if last_err and usage.get("usage_last_status") != "ok":
            out += f" ({last_err[:60]})"
        print(out)

def cmd_ledger(args):
    reg = get_registry()
    entries = reg.ledger.list_all()
    print(f"Key Ledger ({len(entries)} entries):")
    for entry in entries:
        flags = entry.get("ledger_flags") or "-"
        print(f"  {entry['ledger_key_hash'][:12]}  {entry.get('ledger_label') or '?':16} flags={flags:18} last_seen={entry.get('ledger_last_seen_at') or '?'}")

def cmd_flag(args):
    reg = get_registry()
    hits = reg.find_known_keys(args.ident)
    
    if len(hits) != 1:
        if not hits:
            # check ledger
            ledger_hits = reg.ledger.find_by_prefix(args.ident) if len(args.ident) >= 6 else []
            if len(ledger_hits) == 1:
                entry_hash = ledger_hits[0]["ledger_key_hash"]
                flags = key_ledger_parse_flags(ledger_hits[0].get("ledger_flags"))
                changes = key_ledger_parse_flags(args.flags)
                if args.action == "flag":
                    flags = flags | changes
                else:
                    flags = flags - changes
                reg.ledger.set_flags(entry_hash, flags, args.note)
                print(f"Ledger entry {entry_hash[:12]} flags now '{key_ledger_format_flags(flags)}'.")
                return
            print(f"Not found: nothing matches '{args.ident}'.")
            return
        print(f"Ambiguous: {len(hits)} keys match '{args.ident}'.")
        return

    key = hits[0]
    if args.action == "flag":
        reg.flag_key(key, add=[args.flags], note=args.note)
    else:
        reg.flag_key(key, remove=[args.flags], note=args.note)
    
    meta = reg.key_metadata.get(key, {})
    print(f"Key {reg._get_key_hash(key)} flag now '{meta.get('flag') or '-'}'.")

    print("Sync complete.")

def main():
    parser = argparse.ArgumentParser(description="NewAgent Key Admin CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    subparsers.add_parser("list", help="List active registry keys and usage")
    subparsers.add_parser("ledger", help="List all ledger entries")
    
    parser_flag = subparsers.add_parser("flag", help="Add flag to a key")
    parser_flag.add_argument("ident", help="Hash prefix, slot, uuid, or label")
    parser_flag.add_argument("flags", help="Comma-separated flags (e.g. paid,leaked)")
    parser_flag.add_argument("note", nargs="?", default="", help="Optional note")
    parser_flag.set_defaults(action="flag")

    parser_unflag = subparsers.add_parser("unflag", help="Remove flag from a key")
    parser_unflag.add_argument("ident", help="Hash prefix, slot, uuid, or label")
    parser_unflag.add_argument("flags", help="Comma-separated flags (e.g. paid,leaked)")
    parser_unflag.add_argument("note", nargs="?", default="", help="Optional note")
    parser_unflag.set_defaults(action="unflag")
    

    args = parser.parse_args()
    
    if args.command == "list":
        cmd_list(args)
    elif args.command == "ledger":
        cmd_ledger(args)
    elif args.command in ("flag", "unflag"):
        cmd_flag(args)

if __name__ == "__main__":
    main()
