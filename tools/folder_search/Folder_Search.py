# BEJSON Ecosystem Tool | Version: v1.5.4 | Updated: 2026-05-09
"""
SCRIPT_NAME:    Folder Search CLI
SCRIPT_VERSION: 10.0
MFDB Version:   1.3.1
Format_Creator: Elton Boehnen
Jurisdiction:   ["PYTHON", "SYSTEM_TOOLS"]
Status:         OFFICIAL
Date:           2026-05-09
Description:    High-performance direct-content folder indexer for BEJSON Ecosystem.
"""
#!/usr/bin/env python3
"""
SCRIPT_NAME    = "FolderSearch CLI"
SCRIPT_VERSION = "10.0"
RELATIONAL_ID  = "fs-cli-2026"
AUTHOR         = "Elton Boehnen"

FolderSearch CLI — find folders by their DIRECT contents.
A folder qualifies only if the matching files sit immediately inside it.
Files 2+ levels deep past a match are ignored.

USAGE
─────
  python cli.py [SEARCH OPTIONS]
  python cli.py --save-config [SEARCH OPTIONS]   # save as defaults
  python cli.py --show-config
  python cli.py --clear-config

QUICK EXAMPLES
──────────────
  # Folders directly containing .py files
  python cli.py --root /sdcard --ext py

  # Folders with a file named "backup" that is a .zip, AND no .tmp files
  python cli.py --root /sdcard --ext zip --name backup \\
                --add "connector=NOT,ext=tmp"

  # Save those options as defaults, then run again without flags
  python cli.py --root /sdcard --ext zip --name backup --save-config
  python cli.py

  # Fuzzy search, depth-limited, bejson output
  python cli.py --ext mp4 --fuzzy --max-depth 4 --output bejson --export /sdcard/results.bejson
"""

import os
import sys
import json
import shutil
import difflib
import argparse
import calendar
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".folder_search_config.bejson")

CONFIG_DEFAULTS = {
    "root":               "",
    "logic":              "AND",
    "fuzzy":              False,
    "fuzzy_threshold":    85,
    "max_results":        500,
    "max_depth":          None,
    "folder_name_phrase": "",
    "modified_after":     "",
    "modified_before":    "",
    "min_total_files":    None,
    "max_total_files":    None,
    "output_format":      "paths",
    "export_file":        "",
    "no_color":           False
}

CONFIG_FIELDS = [
    {"name": k, "type": "string"} for k in CONFIG_DEFAULTS
]


def _cfg_path(args_config_file):
    return args_config_file or DEFAULT_CONFIG_FILE


def load_config(cfg_file):
    if not os.path.isfile(cfg_file):
        return dict(CONFIG_DEFAULTS)
    try:
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        vals = data.get("Values", {})
        cfg  = dict(CONFIG_DEFAULTS)
        cfg.update({k: v for k, v in vals.items() if k in cfg})
        return cfg
    except Exception as e:
        warn("Could not read config: " + str(e))
        return dict(CONFIG_DEFAULTS)


def save_config(cfg, cfg_file):
    out = {
        "Format":         "BEJSON",
        "Format_Version": "104a",
        "Format_Creator": "Elton Boehnen",
        "Script_Name":    "FolderSearch CLI",
        "Script_Version": "10.0",
        "Records_Type":   "FolderSearchConfig",
        "Fields":         CONFIG_FIELDS,
        "Values":         cfg
    }
    tmp = cfg_file + ".tmp"
    try:
        os.makedirs(os.path.dirname(cfg_file) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        os.replace(tmp, cfg_file)
    except Exception as e:
        warn("Could not save config: " + str(e))


# ── Terminal output ────────────────────────────────────────────────────────────

USE_COLOR = sys.stdout.isatty()

C = {
    "red":   "\033[91m",
    "green": "\033[92m",
    "yellow":"\033[93m",
    "cyan":  "\033[96m",
    "dim":   "\033[2m",
    "bold":  "\033[1m",
    "reset": "\033[0m"
}


def cc(text, *codes):
    if not USE_COLOR:
        return text
    return "".join(C.get(c, "") for c in codes) + text + C["reset"]


def warn(msg):
    print(cc("  ! " + msg, "yellow"), file=sys.stderr)


def err(msg):
    print(cc("  ✕ " + msg, "red"), file=sys.stderr)


def ok(msg):
    print(cc("  ✓ " + msg, "green"))


def header(msg):
    print(cc(msg, "bold", "cyan"))


# ── Core search logic (mirrors app.py — kept standalone, no Flask dep) ─────────

def fuzzy_match(phrase, text, threshold):
    if phrase in text:
        return True
    return difflib.SequenceMatcher(None, phrase, text).ratio() >= threshold


def parse_date_ts(s):
    if not s:
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    try:
        d = datetime.strptime(s.strip(), "%Y-%m-%d")
        return float(calendar.timegm(d.timetuple()))
    except Exception:
        return None


def folder_matches(direct_filenames, dirpath, criteria_list, logic,
                   fuzzy_threshold=None, global_filters=None):
    if not criteria_list:
        return False

    gf = global_filters or {}
    total = len(direct_filenames)

    min_tot = gf.get("min_total_files")
    max_tot = gf.get("max_total_files")
    if min_tot is not None and total < min_tot:
        return False
    if max_tot is not None and total > max_tot:
        return False

    mod_after  = gf.get("modified_after")
    mod_before = gf.get("modified_before")
    if mod_after is not None or mod_before is not None:
        date_ok = False
        for fname in direct_filenames:
            try:
                mtime = os.path.getmtime(os.path.join(dirpath, fname))
                if mod_after  is not None and mtime < mod_after:
                    continue
                if mod_before is not None and mtime > mod_before:
                    continue
                date_ok = True
                break
            except OSError:
                continue
        if not date_ok:
            return False

    def single_match(criterion):
        phrase      = criterion.get("phrase", "").strip().lower()
        path_phrase = criterion.get("path_phrase", "").strip().lower()
        extension   = criterion.get("extension", "").strip().lstrip(".").lower()
        amount      = criterion.get("amount", "").strip()
        min_sz      = criterion.get("min_size")
        max_sz      = criterion.get("max_size")

        if path_phrase and path_phrase not in dirpath.lower():
            return False

        matched = list(direct_filenames)

        if extension:
            matched = [f for f in matched if f.lower().endswith("." + extension)]

        if phrase:
            if fuzzy_threshold is not None:
                matched = [f for f in matched if fuzzy_match(phrase, f.lower(), fuzzy_threshold)]
            else:
                matched = [f for f in matched if phrase in f.lower()]

        if min_sz is not None or max_sz is not None:
            sized = []
            for f in matched:
                try:
                    sz = os.path.getsize(os.path.join(dirpath, f))
                    if min_sz is not None and sz < min_sz:
                        continue
                    if max_sz is not None and sz > max_sz:
                        continue
                    sized.append(f)
                except OSError:
                    pass
            matched = sized

        if not phrase and not extension and not amount and min_sz is None and max_sz is None:
            return True

        if amount:
            try:
                return len(matched) >= int(amount)
            except ValueError:
                pass

        return len(matched) > 0

    not_criteria      = [c for c in criteria_list if c.get("connector", "").upper() == "NOT"]
    positive_criteria = [c for c in criteria_list if c.get("connector", "").upper() != "NOT"]

    for c in not_criteria:
        if single_match(c):
            return False

    if not positive_criteria:
        return True

    results = [single_match(c) for c in positive_criteria]
    return any(results) if logic == "OR" else all(results)


def do_search(root, criteria_list, logic, max_results=500, fuzzy_threshold=None,
              global_filters=None, folder_name_phrase="", max_depth=None,
              progress_cb=None):
    """
    Walk root, return list of matching folder paths.
    progress_cb(dirpath, scanned, found) called each directory if provided.
    """
    matches  = []
    scanned  = 0
    fnp_low  = folder_name_phrase.lower() if folder_name_phrase else ""

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        if len(matches) >= max_results:
            del dirnames[:]
            break

        if max_depth is not None:
            rel   = os.path.relpath(dirpath, root)
            depth = 0 if rel == "." else rel.replace("\\", "/").count("/") + 1
            if depth > max_depth:
                del dirnames[:]
                continue

        dirnames.sort()
        scanned += 1

        if progress_cb:
            progress_cb(dirpath, scanned, len(matches))

        if fnp_low and fnp_low not in os.path.basename(dirpath).lower():
            continue

        if folder_matches(filenames, dirpath, criteria_list, logic,
                          fuzzy_threshold=fuzzy_threshold, global_filters=global_filters):
            matches.append(dirpath)

    return matches, scanned


def results_to_bejson(paths):
    fields = [
        {"name": "folder_path",      "type": "string"},
        {"name": "folder_name",      "type": "string"},
        {"name": "parent_path",      "type": "string"},
        {"name": "export_timestamp", "type": "string"}
    ]
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    values = [
        [p, os.path.basename(p) or p, os.path.dirname(p), ts]
        for p in sorted(paths)
    ]
    return {
        "Format":         "BEJSON",
        "Format_Version": "104",
        "Format_Creator": "Elton Boehnen",
        "Script_Name":    "FolderSearch CLI",
        "Script_Version": "10.0",
        "Records_Type":   ["FolderSearchResult"],
        "Fields":         fields,
        "Values":         values
    }


def print_tree(paths, indent=0):
    """Print a simple indented tree of matched paths."""
    sorted_paths = sorted(paths)
    if not sorted_paths:
        return
    # Find common prefix depth for compression
    for p in sorted_paths:
        print(cc("  " * indent + "📂 ", "red") + cc(os.path.basename(p), "bold") +
              cc("  " + p, "dim"))


def render_tree_nested(paths):
    """Nested tree output showing parent relationships."""
    sorted_paths = sorted(set(paths))
    nodes = {}
    for p in sorted_paths:
        nodes[p] = {"path": p, "children": []}
    roots = []
    for p in sorted_paths:
        parent = os.path.dirname(p)
        if parent in nodes and parent != p:
            nodes[parent]["children"].append(nodes[p])
        else:
            roots.append(nodes[p])

    def _print(node, depth=0):
        prefix = "  " * depth
        name   = os.path.basename(node["path"]) or node["path"]
        parent = os.path.dirname(node["path"])
        print(prefix + cc("📂 ", "red") + cc(name, "bold") +
              cc("  (" + parent + ")", "dim"))
        for child in node["children"]:
            _print(child, depth + 1)

    for r in roots:
        _print(r)


# ── Argument parsing ──────────────────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        prog="cli.py",
        description="FolderSearch CLI v10.0 — find folders by their direct contents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CRITERION FLAGS (primary — first criterion)
  --ext EXT             extension filter  (e.g. --ext zip)
  --name PHRASE         filename contains phrase
  --path-contains STR   folder full path must contain string
  --min N               minimum N matching files
  --min-size BYTES      each matching file must be >= N bytes
  --max-size BYTES      each matching file must be <= N bytes

EXTRA CRITERIA
  --add SPEC            add another criterion (repeatable)
                        SPEC format: connector=AND|OR|NOT,ext=X,name=Y,path=Z,min=N,min_size=B,max_size=B
                        Examples:
                          --add "connector=AND,ext=py"
                          --add "connector=NOT,ext=tmp"
                          --add "connector=OR,name=backup,min=2"

GLOBAL FOLDER FILTERS
  --folder-name PHRASE  folder's own name must contain phrase
  --max-depth N         do not descend more than N levels from root
  --modified-after DATE files modified after date (YYYY-MM-DD)
  --modified-before DATE files modified before date (YYYY-MM-DD)
  --min-total N         folder must have >= N direct files (any type)
  --max-total N         folder must have <= N direct files (any type)

OUTPUT
  --output FORMAT       paths (default), tree, count, bejson
  --export FILE         also save BEJSON 104 results to FILE

CONFIG
  --save-config         save all current flags as persistent defaults
  --show-config         print current saved config and exit
  --clear-config        reset config to defaults and exit
  --config-file PATH    config file path (default: ~/.folder_search_config.bejson)
"""
    )

    # Root
    p.add_argument("--root",      default=None, help="Search root directory")
    p.add_argument("--storage",   default=None, choices=["internal", "sd"],
                   help="Use named Android storage root (internal|sd)")

    # Primary criterion
    p.add_argument("--ext",           default=None, help="File extension (no dot)")
    p.add_argument("--name",          default=None, help="Filename phrase")
    p.add_argument("--path-contains", default=None, dest="path_contains",
                   help="Folder path must contain string")
    p.add_argument("--min",           default=None, type=int, help="Min matching files")
    p.add_argument("--min-size",      default=None, type=int, dest="min_size",
                   help="Min file size in bytes (per matching file)")
    p.add_argument("--max-size",      default=None, type=int, dest="max_size",
                   help="Max file size in bytes (per matching file)")

    # Extra criteria
    p.add_argument("--add", action="append", default=[], dest="add",
                   metavar="SPEC", help="Add extra criterion (see --help)")

    # Logic
    p.add_argument("--logic", default=None, choices=["AND", "OR"],
                   help="Top-level logic for positive criteria (default AND)")

    # Fuzzy
    p.add_argument("--fuzzy",           action="store_true", default=None,
                   help="Enable fuzzy filename phrase matching")
    p.add_argument("--fuzzy-threshold", default=None, type=int, dest="fuzzy_threshold",
                   help="Fuzzy match threshold 0-100 (default 85)")

    # Global folder filters
    p.add_argument("--folder-name",    default=None, dest="folder_name_phrase",
                   help="Folder name must contain phrase")
    p.add_argument("--max-depth",      default=None, type=int, dest="max_depth",
                   help="Max directory depth from root")
    p.add_argument("--modified-after", default=None, dest="modified_after",
                   help="Files modified after YYYY-MM-DD")
    p.add_argument("--modified-before",default=None, dest="modified_before",
                   help="Files modified before YYYY-MM-DD")
    p.add_argument("--min-total",      default=None, type=int, dest="min_total_files",
                   help="Folder must have >= N direct files")
    p.add_argument("--max-total",      default=None, type=int, dest="max_total_files",
                   help="Folder must have <= N direct files")

    # Limits
    p.add_argument("--max-results", default=None, type=int, dest="max_results",
                   help="Stop after N matches (default 500)")

    # Output
    p.add_argument("--output",  default=None, choices=["paths", "tree", "count", "bejson"],
                   help="Output format (default paths)")
    p.add_argument("--export",  default=None, dest="export_file",
                   help="Save BEJSON results to FILE")
    p.add_argument("--no-color",action="store_true", default=False, dest="no_color",
                   help="Disable ANSI color output")

    # Config
    p.add_argument("--save-config",  action="store_true", default=False, dest="save_config")
    p.add_argument("--show-config",  action="store_true", default=False, dest="show_config")
    p.add_argument("--clear-config", action="store_true", default=False, dest="clear_config")
    p.add_argument("--config-file",  default=None, dest="config_file",
                   help="Config file path")

    return p


def parse_add_spec(spec_str):
    """Parse 'connector=AND,ext=py,name=foo,path=bar,min=2,min_size=1024' into a criterion dict."""
    criterion = {}
    for part in spec_str.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if key == "connector":
            criterion["connector"] = val.upper()
        elif key == "ext":
            criterion["extension"] = val
        elif key == "name":
            criterion["phrase"] = val
        elif key in ("path", "path_contains", "path_phrase"):
            criterion["path_phrase"] = val
        elif key == "min":
            criterion["amount"] = val
        elif key == "min_size":
            try:
                criterion["min_size"] = int(val)
            except ValueError:
                pass
        elif key == "max_size":
            try:
                criterion["max_size"] = int(val)
            except ValueError:
                pass
    return criterion


ANDROID_ROOTS = {
    "internal": os.environ.get("INTERNAL_STORAGE", "/storage/emulated/0"),
    "sd":       os.environ.get("EXTERNAL_SD", "/storage/7B30-0E0B")
}


def resolve_root(args_root, args_storage, cfg_root):
    """Determine search root from args, storage shorthand, or saved config."""
    if args_root:
        return args_root
    if args_storage:
        return ANDROID_ROOTS.get(args_storage, ANDROID_ROOTS["internal"])
    if cfg_root:
        return cfg_root
    return None


def merge_with_config(args, cfg):
    """
    Merge parsed args with loaded config. Args always win over config when
    explicitly provided (i.e. not None).
    Returns a final options dict.
    """
    def pick(arg_val, cfg_key, default=None):
        return arg_val if arg_val is not None else cfg.get(cfg_key, default)

    return {
        "root":               resolve_root(args.root, args.storage, cfg.get("root", "")),
        "logic":              pick(args.logic, "logic", "AND").upper(),
        "fuzzy":              pick(args.fuzzy, "fuzzy", False),
        "fuzzy_threshold":    pick(args.fuzzy_threshold, "fuzzy_threshold", 85),
        "max_results":        pick(args.max_results, "max_results", 500),
        "max_depth":          pick(args.max_depth, "max_depth", None),
        "folder_name_phrase": pick(args.folder_name_phrase, "folder_name_phrase", ""),
        "modified_after":     pick(args.modified_after, "modified_after", ""),
        "modified_before":    pick(args.modified_before, "modified_before", ""),
        "min_total_files":    pick(args.min_total_files, "min_total_files", None),
        "max_total_files":    pick(args.max_total_files, "max_total_files", None),
        "output_format":      pick(args.output, "output_format", "paths"),
        "export_file":        pick(args.export_file, "export_file", ""),
        "no_color":           args.no_color or cfg.get("no_color", False),
        # primary criterion pieces (not stored in config — built per-run)
        "_ext":           args.ext,
        "_name":          args.name,
        "_path_contains": args.path_contains,
        "_min":           args.min,
        "_min_size":      args.min_size,
        "_max_size":      args.max_size,
        "_add":           args.add
    }


def build_criteria(opts):
    """Build criteria_list from merged options."""
    has_primary = any([
        opts["_ext"], opts["_name"], opts["_path_contains"],
        opts["_min"], opts["_min_size"], opts["_max_size"]
    ])

    criteria = []
    if has_primary:
        c = {"connector": ""}
        if opts["_ext"]:           c["extension"]   = opts["_ext"]
        if opts["_name"]:          c["phrase"]       = opts["_name"]
        if opts["_path_contains"]: c["path_phrase"]  = opts["_path_contains"]
        if opts["_min"]:           c["amount"]       = str(opts["_min"])
        if opts["_min_size"]:      c["min_size"]     = opts["_min_size"]
        if opts["_max_size"]:      c["max_size"]     = opts["_max_size"]
        criteria.append(c)

    for spec in (opts["_add"] or []):
        c = parse_add_spec(spec)
        if c:
            criteria.append(c)

    return criteria


# ── Progress display ──────────────────────────────────────────────────────────

class ProgressPrinter:
    def __init__(self, enabled=True):
        self.enabled  = enabled and sys.stderr.isatty()
        self._last    = ""

    def __call__(self, dirpath, scanned, found):
        if not self.enabled:
            return
        short = dirpath if len(dirpath) <= 65 else "..." + dirpath[-62:]
        line  = "\r  Scanned: {:>5}  Found: {:>4}  {}".format(scanned, found, short)
        if line != self._last:
            sys.stderr.write(line.ljust(100) + "")
            sys.stderr.flush()
            self._last = line

    def done(self):
        if self.enabled:
            sys.stderr.write("\r" + " " * 105 + "\r")
            sys.stderr.flush()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global USE_COLOR
    parser = build_parser()
    args   = parser.parse_args()

    cfg_file = _cfg_path(args.config_file)

    # ── Config commands ────────────────────────────────────────────────────────
    if args.show_config:
        cfg = load_config(cfg_file)
        header("\nFolderSearch CLI — Saved Config")
        print(cc("  File: ", "dim") + cfg_file)
        for k, v in cfg.items():
            print("  {:25s} {}".format(k, cc(str(v), "cyan")))
        print()
        sys.exit(0)

    if args.clear_config:
        save_config(dict(CONFIG_DEFAULTS), cfg_file)
        ok("Config cleared: " + cfg_file)
        sys.exit(0)

    # Load saved config, merge with args
    cfg  = load_config(cfg_file)
    opts = merge_with_config(args, cfg)

    if args.no_color:
        USE_COLOR = False

    # ── Save config ────────────────────────────────────────────────────────────
    if args.save_config:
        new_cfg = {k: v for k, v in opts.items() if not k.startswith("_")}
        save_config(new_cfg, cfg_file)
        ok("Config saved to: " + cfg_file)
        # Continue to run the search too

    # ── Validate root ──────────────────────────────────────────────────────────
    root = opts["root"]
    if not root:
        err("No search root specified. Use --root PATH or --storage internal|sd")
        err("Or save a default root: python cli.py --root /path --save-config")
        sys.exit(1)

    root = os.path.expanduser(root)
    if not os.path.isdir(root):
        err("Root directory does not exist: " + root)
        sys.exit(1)

    # ── Build criteria ─────────────────────────────────────────────────────────
    criteria_list = build_criteria(opts)
    if not criteria_list:
        err("No search criteria. Specify --ext, --name, or --add.")
        sys.exit(1)

    # ── Fuzzy ─────────────────────────────────────────────────────────────────
    fuzzy_threshold = None
    if opts["fuzzy"]:
        pct = int(opts["fuzzy_threshold"]) if opts["fuzzy_threshold"] else 85
        fuzzy_threshold = max(0.0, min(1.0, pct / 100.0))

    # ── Global filters ─────────────────────────────────────────────────────────
    global_filters = {
        "modified_after":  parse_date_ts(opts.get("modified_after")),
        "modified_before": parse_date_ts(opts.get("modified_before")),
        "min_total_files": opts.get("min_total_files"),
        "max_total_files": opts.get("max_total_files"),
    }

    # ── Print search summary ───────────────────────────────────────────────────
    header("\n  FolderSearch CLI v10.0")
    print(cc("  Root:     ", "dim") + cc(root, "cyan"))
    print(cc("  Logic:    ", "dim") + opts["logic"])
    if fuzzy_threshold is not None:
        print(cc("  Fuzzy:    ", "dim") + "{}%".format(opts["fuzzy_threshold"]))
    if opts.get("max_depth") is not None:
        print(cc("  Depth:    ", "dim") + "max " + str(opts["max_depth"]))
    if opts.get("folder_name_phrase"):
        print(cc("  Folder:   ", "dim") + opts["folder_name_phrase"])
    if opts.get("modified_after"):
        print(cc("  After:    ", "dim") + opts["modified_after"])
    if opts.get("modified_before"):
        print(cc("  Before:   ", "dim") + opts["modified_before"])
    print(cc("  Criteria: ", "dim") + str(len(criteria_list)))
    for i, c in enumerate(criteria_list):
        conn = c.get("connector") or "PRIMARY"
        parts = []
        if c.get("extension"):   parts.append("ext=" + c["extension"])
        if c.get("phrase"):      parts.append("name=" + c["phrase"])
        if c.get("path_phrase"): parts.append("path=" + c["path_phrase"])
        if c.get("amount"):      parts.append("min=" + str(c["amount"]))
        if c.get("min_size"):    parts.append("min_size=" + str(c["min_size"]))
        if c.get("max_size"):    parts.append("max_size=" + str(c["max_size"]))
        print("    [{}] {} {}".format(
            i + 1,
            cc(conn, "red" if conn == "NOT" else "cyan"),
            cc(", ".join(parts) if parts else "(path only)", "dim")
        ))
    print()

    # ── Run search ─────────────────────────────────────────────────────────────
    prog = ProgressPrinter(enabled=True)

    matches, scanned = do_search(
        root,
        criteria_list,
        opts["logic"],
        max_results=int(opts["max_results"]),
        fuzzy_threshold=fuzzy_threshold,
        global_filters=global_filters,
        folder_name_phrase=opts.get("folder_name_phrase", ""),
        max_depth=opts.get("max_depth"),
        progress_cb=prog
    )
    prog.done()

    # ── Output ─────────────────────────────────────────────────────────────────
    fmt = opts.get("output_format", "paths")

    if fmt == "count":
        print(cc("  Found: ", "bold") + cc(str(len(matches)), "red") +
              "  (scanned {} dirs)".format(scanned))

    elif fmt == "bejson":
        bj = results_to_bejson(matches)
        print(json.dumps(bj, indent=2))

    elif fmt == "tree":
        if matches:
            print(cc("  Results — {} match{}\n".format(
                len(matches), "es" if len(matches) != 1 else ""), "bold"))
            render_tree_nested(matches)
        else:
            print(cc("  No matches found.", "dim"))

    else:  # paths (default)
        if matches:
            for p in sorted(matches):
                print(cc("  📂 ", "red") + p)
        else:
            print(cc("  No matches found.", "dim"))

    # Summary line
    print()
    if matches:
        print(cc("  ✓ ", "green") +
              cc(str(len(matches)), "bold") +
              " folder{} matched  •  ".format("s" if len(matches) != 1 else "") +
              cc(str(scanned) + " dirs scanned", "dim"))
    else:
        print(cc("  ✕ ", "red") + "No folders matched  •  " +
              cc(str(scanned) + " dirs scanned", "dim"))
    print()

    # ── Export ─────────────────────────────────────────────────────────────────
    export_file = opts.get("export_file", "")
    if export_file and matches:
        bj  = results_to_bejson(matches)
        tmp = export_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(bj, f, indent=2)
            os.replace(tmp, export_file)
            ok("Exported " + str(len(matches)) + " results to: " + export_file)
        except Exception as e:
            err("Export failed: " + str(e))

    sys.exit(0 if matches else 1)


if __name__ == "__main__":
    main()
