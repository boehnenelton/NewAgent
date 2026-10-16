"""
Library:        lib_bejson_newagent_help.py
Family:         NewAgent
Description:    Data-driven help system. Every help screen (/help index, /help
                <topic>, /help <command>, /<command> help) is rendered from a
                single BEJSON 104 registry (config/help.bejson, Records_Type
                "HelpEntry"). `help_topic` is the topic discriminator: all rows
                sharing a help_topic value belong to that topic. `help_kind`
                says what a row is: topic (header: title + blurb), command,
                note, or example. Edit the .bejson file to change help; no code
                change needed. Fields are resolved through the Field Map Cache.
Version:        1.0.0
Date:           2026-10-14
Author:         Elton Boehnen — boehnenelton2024@gmail.com
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  8f3c1a52-7e49-4d06-b2a8-6d19f0c3e7b4
CHANGELOG:
- 1.0.0 (2026-10-14): Initial release -- topic submenus, grouped index, per-command
  pages, "did you mean" suggestions, mtime-cached registry, safe fallback.
"""

import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import bejson_core_load_file, bejson_core_get_field_map
from lib_bejson_newagent_tui import C

VERSION = "1.0.0"
logger = logging.getLogger(__name__)

# Registry schema (field names live here once; the rest of the module uses the constants).
F_ID = "help_id"
F_TOPIC = "help_topic"          # discriminator: which topic a row belongs to
F_KIND = "help_kind"
F_COMMAND = "help_command"
F_TITLE = "help_title"
F_SYNTAX = "help_syntax"
F_TEXT = "help_text"
F_ORDER = "help_order"
REQUIRED_FIELDS = (F_ID, F_TOPIC, F_KIND, F_COMMAND, F_TITLE, F_SYNTAX, F_TEXT, F_ORDER)

KIND_TOPIC = "topic"
KIND_COMMAND = "command"
KIND_NOTE = "note"
KIND_EXAMPLE = "example"

# Self-locating default (project_root/config/help.bejson); ctx["_config_dir"] overrides it.
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parent.parent / "config" / "help.bejson"
REGISTRY_FILENAME = "help.bejson"


@dataclass
class CommandEntry:
    command: str
    title: str
    syntax: str
    text: str
    topic: str
    order: int = 0


@dataclass
class Topic:
    key: str
    title: str
    blurb: str
    order: int = 0
    commands: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    examples: list = field(default_factory=list)


@dataclass
class HelpRegistry:
    topics: dict            # key -> Topic, in display order
    commands: dict          # "/cmd" -> CommandEntry


_cache: dict = {}           # path -> (mtime, HelpRegistry)


def _clean(value) -> str:
    """Boundary-layer sanitization: strip whitespace on every string value."""
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value).strip())


def _norm_command(text: str) -> str:
    text = _clean(text).lower()
    return text if not text or text.startswith("/") else "/" + text


def load_registry(path: Path) -> Optional[HelpRegistry]:
    """Load + index the help registry. Returns None (and logs) if it is missing
    or malformed. Cached per path and invalidated when the file's mtime changes,
    so edits to help.bejson show up without restarting the agent."""
    path = Path(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        logger.warning("[Help] registry not found: %s", path)
        return None
    hit = _cache.get(str(path))
    if hit and hit[0] == mtime:
        return hit[1]

    doc = bejson_core_load_file(str(path))
    if not doc or not isinstance(doc.get("Values"), list):
        logger.warning("[Help] registry unreadable: %s", path)
        return None
    fmap = bejson_core_get_field_map(doc)
    missing = [f for f in REQUIRED_FIELDS if f not in fmap]
    if missing:
        logger.warning("[Help] registry %s missing fields: %s", path, ", ".join(missing))
        return None

    rows = []
    for raw in doc["Values"]:
        if len(raw) < len(fmap):
            continue
        rows.append({name: raw[idx] for name, idx in fmap.items()})
    for r in rows:
        for k in (F_ID, F_TOPIC, F_KIND, F_COMMAND, F_TITLE, F_SYNTAX, F_TEXT):
            r[k] = _clean(r[k])
        try:
            r[F_ORDER] = int(r[F_ORDER])
        except (TypeError, ValueError):
            r[F_ORDER] = 0

    topic_rows = sorted((r for r in rows if r[F_KIND] == KIND_TOPIC), key=lambda r: r[F_ORDER])
    topics = {r[F_TOPIC]: Topic(r[F_TOPIC], r[F_TITLE] or r[F_TOPIC], r[F_TEXT], r[F_ORDER]) for r in topic_rows}
    commands: dict = {}
    for r in sorted(rows, key=lambda r: r[F_ORDER]):
        topic = topics.get(r[F_TOPIC])
        if topic is None:
            continue                       # row for an undeclared topic: ignored
        if r[F_KIND] == KIND_COMMAND:
            cmd = _norm_command(r[F_COMMAND])
            if not cmd:
                continue
            entry = CommandEntry(cmd, r[F_TITLE], r[F_SYNTAX] or cmd, r[F_TEXT], topic.key, r[F_ORDER])
            topic.commands.append(entry)
            commands[cmd] = entry
        elif r[F_KIND] == KIND_NOTE:
            topic.notes.append(r[F_TEXT])
        elif r[F_KIND] == KIND_EXAMPLE:
            topic.examples.append(r[F_TEXT])

    reg = HelpRegistry(topics, commands)
    _cache[str(path)] = (mtime, reg)
    return reg


# ---------------------------------------------------------------- rendering --

def render_index(reg: HelpRegistry) -> str:
    width = max((len(c.command) for c in reg.commands.values()), default=8)
    lines = [f"{C.RED_B}NewAgent Slash Commands{C.RESET}"]
    for topic in reg.topics.values():
        lines.append(f"\n{C.WHITE_B}{topic.title}{C.RESET}  {C.DIM}(/help {topic.key}){C.RESET}")
        for cmd in topic.commands:
            lines.append(f"  {C.RED_B}{cmd.command:<{width}}{C.RESET} - {C.WHITE}{cmd.title}{C.RESET}")
    keys = ", ".join(reg.topics)
    lines.append(f"\n{C.YELLOW}Topics: {keys}{C.RESET}")
    lines.append(f"{C.YELLOW}Tip: {C.RED_B}/help <topic>{C.YELLOW} for a section, {C.RED_B}/help <command>{C.YELLOW} "
                 f"or {C.RED_B}/<command> help{C.YELLOW} for usage.{C.RESET}")
    return "\n" + "\n".join(lines) + "\n"


def render_command(reg: HelpRegistry, cmd: CommandEntry) -> str:
    topic = reg.topics.get(cmd.topic)
    lines = [f"{C.RED_B}{cmd.command} Help:{C.RESET}", f"Usage: {cmd.syntax}"]
    if cmd.text:
        lines.append(cmd.text)
    elif cmd.title:
        lines.append(cmd.title)
    if topic:
        lines.append(f"\n{C.DIM}Topic: {topic.title} -- /help {topic.key}{C.RESET}")
    return "\n".join(lines)


def render_topic(reg: HelpRegistry, topic: Topic) -> str:
    lines = [f"{C.RED_B}{topic.title}{C.RESET}", topic.blurb] if topic.blurb else [f"{C.RED_B}{topic.title}{C.RESET}"]
    for cmd in topic.commands:
        lines.append(f"\n{C.RED_B}{cmd.syntax.splitlines()[0]}{C.RESET}")
        if cmd.text:
            lines.extend("  " + ln for ln in cmd.text.splitlines())
        else:
            lines.append(f"  {cmd.title}")
    if topic.notes:
        lines.append(f"\n{C.WHITE_B}Notes{C.RESET}")
        lines.extend(f"  * {n}" for n in topic.notes)
    if topic.examples:
        lines.append(f"\n{C.WHITE_B}Examples{C.RESET}")
        lines.extend(f"  {e}" for e in topic.examples)
    others = ", ".join(k for k in reg.topics if k != topic.key)
    lines.append(f"\n{C.DIM}Other topics: {others}  (/help for the full list){C.RESET}")
    return "\n" + "\n".join(lines) + "\n"


def render_unknown(reg: HelpRegistry, query: str) -> str:
    pool = list(reg.topics) + [c.lstrip("/") for c in reg.commands]
    close = list(dict.fromkeys(difflib.get_close_matches(query.lower().lstrip("/"), pool, n=5, cutoff=0.5)))[:3]
    lines = [f"{C.YELLOW}No help topic or command matches '{query}'.{C.RESET}"]
    if close:
        lines.append("Did you mean: " + ", ".join(f"/help {m}" for m in close) + "?")
    lines.append("Topics: " + ", ".join(reg.topics) + "   (/help for everything)")
    return "\n".join(lines)


# ------------------------------------------------------------------ lookup --

def resolve(reg: HelpRegistry, query: str):
    """Return ("index"|"topic"|"command"|"unknown", object). Order: exact topic,
    exact command (with or without the slash), unique prefix, otherwise unknown."""
    q = _clean(query).lower()
    if not q:
        return "index", None
    if q in reg.topics:
        return "topic", reg.topics[q]
    cmd = _norm_command(q)
    if cmd in reg.commands:
        return "command", reg.commands[cmd]
    hits = [("topic", t) for k, t in reg.topics.items() if k.startswith(q)]
    hits += [("command", c) for k, c in reg.commands.items() if k.startswith(cmd)]
    if len(hits) == 1:
        return hits[0]
    return "unknown", None


def registry_path_for(config_dir: Optional[Path]) -> Path:
    return Path(config_dir) / REGISTRY_FILENAME if config_dir else DEFAULT_REGISTRY_PATH


def render_help(query: str = "", config_dir: Optional[Path] = None) -> str:
    """Entry point used by the slash-command dispatcher for /help [query]."""
    reg = load_registry(registry_path_for(config_dir))
    if reg is None:
        return (f"{C.YELLOW}Help registry unavailable -- restore config/{REGISTRY_FILENAME} "
                f"(BEJSON 104, Records_Type HelpEntry). Basics: /help, /about, /exit.{C.RESET}")
    kind, obj = resolve(reg, query)
    if kind == "index":
        return render_index(reg)
    if kind == "topic":
        return render_topic(reg, obj)
    if kind == "command":
        return render_command(reg, obj)
    return render_unknown(reg, query)


def render_command_help(cmd: str, config_dir: Optional[Path] = None) -> Optional[str]:
    """For `/<cmd> help`. None when the registry has no entry for cmd."""
    reg = load_registry(registry_path_for(config_dir))
    if reg is None:
        return None
    entry = reg.commands.get(_norm_command(cmd))
    return render_command(reg, entry) if entry else None
