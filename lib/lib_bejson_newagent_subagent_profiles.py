"""
Library:        lib_bejson_newagent_subagent_profiles.py
Family:         NewAgent (subagent family)
Description:    Sub-agent profile registry -- one BEJSON 104 file per
                profile under subagents/profiles/<name>.bejson, each
                describing a role a dispatched sub-agent can run as
                (system prompt fragment, model override, which action
                tags it's allowed to use, an optional exec denylist
                override). Read on every dispatch by
                lib_bejson_newagent_subagent_runtime.py.

                Inspired by Cognitive_Core's lib_bejson_agentic_tools.py
                profile functions (agentic_tools_load_agent_profile /
                _save_agent_profile / _list_agent_profiles /
                _get_active_agent / _set_active_agent), which already used
                the Field Map Cache correctly (no positional literals) --
                that part is carried over largely as-is. What's new here:
                Cognitive_Core profile files were left at whatever format
                the caller happened to construct (its own audit flagged
                "104" vs "104a" mismatches across the data/ files); every
                profile written by this library is deliberately BEJSON 104
                (not 104a) since a profile's allowed_actions field is a
                native array -- 104a can't hold that without stringifying
                it the way lib_bejson_newagent_config.py has to for
                exec_denylist, which is only tolerable there because
                config.json is a flat settings table, not a real record
                type with a natural array field. There is also no separate
                "active agent" selection concept here (Cognitive_Core's
                agentic_tools_get/set_active_agent) -- NewAgent's runtime
                always dispatches a sub-agent BY a caller-supplied profile
                name (see subagent_runtime.dispatch_subagent), so there is
                no single global "active" one to track.
Version:        1.1.0
Date:           2026-09-29
Author:         Elton Boehnen — eltonboehnen@gmail.com
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  dcf3f09e-9597-48cd-bbe3-820ae728b1da

CHANGELOG:
- 1.1.0 (2026-09-29): Remediation pass, audit finding #7 (sub-agent
  token/char history budgeting -- the audit's named priority follow-up).
  Added max_history_chars field to _PROFILE_FIELDS (appended at the end
  per BEJSON positional-integrity rules, policy Sec 10.5) plus
  DEFAULT_MAX_HISTORY_CHARS=60000 (~15k tokens at ~4 chars/token) and a
  matching make_profile_doc() parameter. Existing profile files predating
  this field are unaffected -- load_profile()'s row_to_dict() builds its
  dict against each file's OWN stored Fields array, not this module's
  current _PROFILE_FIELDS constant, so an old file simply omits the key
  and callers apply the default; no migration needed. See
  subagent_sessions.py 1.1.0 and subagent_runtime.py 1.1.0 for where the
  actual trim logic lives and is wired in.
- 1.0.0 (2026-09-12): Initial version.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib_bejson_Core_bejson_core import (
    bejson_core_load_file,
    bejson_core_atomic_write,
    bejson_core_create_104,
)
from lib_bejson_newagent_subagent_common import profiles_dir, row_to_dict

VERSION = "1.1.0"

# One row per profile file (single-record 104 document) -- a profile isn't
# a growing table, so no with_file_lock() contention here: each profile is
# its own file, and profile authoring is a rare, human-driven action, not
# a hot concurrent-write path the way sessions/signals are.
_PROFILE_FIELDS = [
    {"name": "profile_name", "type": "string"},
    {"name": "role_description", "type": "string"},
    {"name": "system_prompt", "type": "string"},
    {"name": "model_override", "type": "string"},       # "" = use the caller's active model
    {"name": "allowed_actions", "type": "array"},        # e.g. ["read_file","write_file","exec"]; ["*"] = all
    {"name": "exec_denylist_override", "type": "array"}, # "" / [] = inherit the caller's config exec_denylist
    {"name": "max_turns", "type": "integer"},            # hard cap per dispatch -- see subagent_runtime
    {"name": "created_at", "type": "string"},
    {"name": "max_history_chars", "type": "integer"},    # see DEFAULT_MAX_HISTORY_CHARS below
]

DEFAULT_MAX_TURNS = 10
DEFAULT_MAX_HISTORY_CHARS = 60000  # ~15k tokens at ~4 chars/token -- see subagent_sessions.update_session()

# FIX (Remediation pkg, audit finding #7): max_turns bounds how many
# DISPATCH turns a session can run, but nothing bounded the SIZE of the
# history accumulated along the way -- a task that produces one large
# tool output (a big file read) could blow the model's context window
# well before max_turns was reached. Appended (not inserted -- BEJSON
# positional integrity, policy Sec 10.5) rather than backfilling every
# existing profile file: load_profile()'s row_to_dict() builds its dict
# against each FILE'S OWN Fields array, not this module's current
# _PROFILE_FIELDS constant, so an existing profile predating this field
# just omits the key -- read as profile.get("max_history_chars") with
# this default applied at the call site, no data migration needed.


def _profile_path(subagents_dir: Path, profile_name: str) -> Path:
    return profiles_dir(subagents_dir) / f"{profile_name}.bejson"


def make_profile_doc(
    profile_name: str,
    role_description: str = "",
    system_prompt: str = "",
    model_override: str = "",
    allowed_actions: Optional[list] = None,
    exec_denylist_override: Optional[list] = None,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_history_chars: int = DEFAULT_MAX_HISTORY_CHARS,
) -> dict:
    """Builds a fresh profile document in memory (doesn't write it -- see
    save_profile). allowed_actions defaults to ["*"] (all action tags the
    caller's own actions.py supports) since most profiles are meant to
    delegate real work, not to be locked down by default -- callers that
    want a restricted profile pass an explicit allowlist."""
    row = [
        profile_name,
        role_description,
        system_prompt,
        model_override,
        list(allowed_actions) if allowed_actions is not None else ["*"],
        list(exec_denylist_override) if exec_denylist_override is not None else [],
        max_turns,
        datetime.now(timezone.utc).isoformat(),
        max_history_chars,
    ]
    return bejson_core_create_104("SubagentProfile", list(_PROFILE_FIELDS), [row])


def save_profile(subagents_dir: Path, profile_name: str, doc: dict) -> bool:
    """Writes a profile document (from make_profile_doc, or a loaded+edited
    one) to subagents/profiles/<profile_name>.bejson. Overwrites in full --
    a profile has exactly one record, there's nothing to merge."""
    path = _profile_path(subagents_dir, profile_name)
    return bejson_core_atomic_write(str(path), doc)


def load_profile(subagents_dir: Path, profile_name: str) -> Optional[dict]:
    """Returns the field-mapped profile record, or None if it doesn't
    exist. Raises nothing on a missing file -- callers (subagent_runtime)
    treat a missing profile as a dispatch-time error to report, not a
    library-level exception."""
    path = _profile_path(subagents_dir, profile_name)
    if not path.exists():
        return None
    doc = bejson_core_load_file(str(path))
    if not isinstance(doc, dict) or not doc.get("Values"):
        return None
    return row_to_dict(doc, doc["Values"][0])


def list_profiles(subagents_dir: Path) -> list[dict]:
    """Lists every profile in subagents/profiles/, field-mapped, with the
    bare profile name (filename stem) included as 'profile_name' -- reads
    it back out of the record itself too (should match; this is a display/
    selection helper for the caller, not a consistency check)."""
    pdir = profiles_dir(subagents_dir)
    out = []
    if not pdir.is_dir():
        return out
    for f in sorted(pdir.glob("*.bejson")):
        doc = bejson_core_load_file(str(f))
        if not isinstance(doc, dict) or not doc.get("Values"):
            continue
        record = row_to_dict(doc, doc["Values"][0])
        record.setdefault("profile_name", f.stem)
        out.append(record)
    return out


def delete_profile(subagents_dir: Path, profile_name: str) -> bool:
    path = _profile_path(subagents_dir, profile_name)
    if not path.exists():
        return False
    path.unlink()
    return True


def action_allowed(profile: dict, action_tag: str) -> bool:
    """True if `action_tag` (e.g. "exec", "write_file") is permitted for
    this profile. ["*"] (the default from make_profile_doc) permits
    everything; an explicit list is a strict allowlist."""
    allowed = profile.get("allowed_actions") or []
    return "*" in allowed or action_tag in allowed
