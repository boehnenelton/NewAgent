"""
Library:        lib_bejson_NewAgentCMS_cms_skeletons.py
Family:         NewAgentCMS
Description:    SkeletonLoader -- reads published-site skeleton templates
                from disk (theme-aware, with fallback to a shared
                'default' set), validates each one against a registered
                {{tag}} contract, and supports a draft -> diff -> promote
                workflow so a skeleton edit can be previewed and compared
                before it ever reaches the live file a real publish reads.

                This replaces the old SkeletonBuilder pattern (skeleton
                HTML baked as Python string literals inside
                NewAgent_CMS_Publisher.py, with a force=True regen route
                that silently overwrote hand-edited files on disk) with a
                single source of truth: the files themselves, tracked by
                skeleton_registry.json (a BEJSON 104a document, resolved
                through SkeletonRegistry below rather than positional
                indexing, per Field Map Cache policy).

                See: Dynamic_Skeleton_Loader-Proposal-V1.docx for the full
                design rationale this implements.
Version:        1
Date:           2026-08-24
Author:         Elton Boehnen
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  6f3a9c1e-2b7d-4e5f-8a1c-9d6e3b2f7a4c
"""

import os
import json
import hashlib
import difflib
import shutil
from datetime import datetime, timezone

VERSION = "1"

DRAFT_SUFFIX = ".draft"
HISTORY_DIRNAME = "_history"


class SkeletonContractError(Exception):
    """Raised when a skeleton is missing one or more of its registered
    required {{tag}} placeholders. Caught at the call site to produce a
    clear per-file error instead of silently shipping a broken page."""
    pass


def _normalize_for_hash(content):
    """Normalize line endings before hashing so a Termux edit and a
    desktop-editor edit of otherwise-identical content don't register as
    drift purely from CRLF vs LF (Proposal §Risks)."""
    return content.replace("\r\n", "\n").replace("\r", "\n")


def _sha256(content):
    return hashlib.sha256(_normalize_for_hash(content).encode("utf-8")).hexdigest()


class SkeletonRegistry:
    """Thin wrapper around skeleton_registry.json (BEJSON 104a). All
    access goes through the field map cache -- never a raw positional
    index -- per the project's Core Mandate."""

    RECORD_TYPE = "SkeletonRegistry"

    def __init__(self, registry_path):
        self.registry_path = registry_path
        self._doc = None
        self._field_map = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.registry_path):
            self._doc = self._new_doc()
            self._save()
        with open(self.registry_path, encoding="utf-8") as f:
            self._doc = json.load(f)
        self._field_map = {
            field["name"]: i for i, field in enumerate(self._doc["Fields"])
        }

    def _new_doc(self):
        return {
            "Format": "BEJSON",
            "Format_Version": "104a",
            "Format_Creator": "Elton Boehnen",
            "Records_Type": [self.RECORD_TYPE],
            "Fields": [
                {"name": "registry_uuid",    "type": "string"},
                {"name": "skeleton_theme",   "type": "string"},
                {"name": "skeleton_name",    "type": "string"},
                {"name": "skeleton_path",    "type": "string"},
                {"name": "skeleton_status",  "type": "string"},
                {"name": "skeleton_version", "type": "integer"},
                {"name": "required_tags",    "type": "array"},
                {"name": "content_checksum", "type": "string"},
                {"name": "last_promoted_at", "type": "string"},
                {"name": "wired_up",         "type": "boolean"},
            ],
            "Values": [],
        }

    def _save(self):
        tmp_path = self.registry_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self._doc, f, indent=2)
        os.replace(tmp_path, self.registry_path)

    def _row_to_dict(self, row):
        return {name: row[idx] for name, idx in self._field_map.items()}

    def _find_row_index(self, theme, name):
        theme_idx = self._field_map["skeleton_theme"]
        name_idx = self._field_map["skeleton_name"]
        for i, row in enumerate(self._doc["Values"]):
            if row[theme_idx] == theme and row[name_idx] == name:
                return i
        return None

    def get(self, theme, name):
        idx = self._find_row_index(theme, name)
        if idx is None and theme != "default":
            # Fall back to a 'default' registry entry, mirroring
            # SkeletonLoader._resolve_path's own file-resolution fallback
            # -- a theme with no per-theme override shares the default
            # file, so it should share the default file's tag contract
            # too, rather than validating as "no requirements" just
            # because no theme-specific row was ever registered.
            idx = self._find_row_index("default", name)
        if idx is None:
            return None
        return self._row_to_dict(self._doc["Values"][idx])

    def list_all(self, theme=None):
        rows = [self._row_to_dict(r) for r in self._doc["Values"]]
        if theme:
            rows = [r for r in rows if r["skeleton_theme"] == theme]
        return rows

    def get_required_tags(self, theme, name):
        row = self.get(theme, name)
        return row["required_tags"] if row else []

    def upsert(self, theme, name, path, required_tags, wired_up=True, status="live"):
        import uuid
        idx = self._find_row_index(theme, name)
        row = [
            f"reg_{theme}_{name.lower()}" if idx is None else self._doc["Values"][idx][self._field_map["registry_uuid"]],
            theme,
            name,
            path,
            status,
            1 if idx is None else self._doc["Values"][idx][self._field_map["skeleton_version"]],
            required_tags,
            "",
            "",
            wired_up,
        ]
        if idx is None:
            self._doc["Values"].append(row)
        else:
            self._doc["Values"][idx] = row
        self._save()

    def bump_version(self, theme, name, checksum):
        idx = self._find_row_index(theme, name)
        if idx is None:
            return
        row = self._doc["Values"][idx]
        row[self._field_map["skeleton_version"]] += 1
        row[self._field_map["content_checksum"]] = checksum
        row[self._field_map["last_promoted_at"]] = datetime.now(timezone.utc).isoformat()
        self._save()

    def set_checksum(self, theme, name, checksum):
        idx = self._find_row_index(theme, name)
        if idx is None:
            return
        self._doc["Values"][idx][self._field_map["content_checksum"]] = checksum
        self._save()


class SkeletonLoader:
    """Resolution order for get(theme, name): resources/templates/<theme>/
    <name>.html if it exists, else resources/templates/default/<name>.html.
    Matches today's actual behavior (one shared markup set across all
    three CSS themes) as the zero-effort default, while a genuine
    per-theme override is just a matter of dropping one file in the
    theme's own folder -- no code change, no duplicated literal."""

    def __init__(self, templates_root, registry_path):
        self.templates_root = templates_root
        self.registry = SkeletonRegistry(registry_path)
        self._cache = {}  # (theme, name) -> (mtime, content)

    # ---- path resolution ----

    def _resolve_path(self, theme, name):
        themed = os.path.join(self.templates_root, theme, f"{name}.html")
        if os.path.exists(themed):
            return themed
        return os.path.join(self.templates_root, "default", f"{name}.html")

    def _draft_path(self, theme, name):
        return self._resolve_path(theme, name) + DRAFT_SUFFIX

    # ---- read path ----

    def get(self, theme, name, validate=True):
        path = self._resolve_path(theme, name)
        mtime = os.path.getmtime(path)
        cached = self._cache.get((theme, name))
        if cached and cached[0] == mtime:
            content = cached[1]
        else:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self._cache[(theme, name)] = (mtime, content)
        if validate:
            missing = self.validate(theme, name, content)
            if missing:
                raise SkeletonContractError(
                    f"{name} for theme '{theme}' (resolved from {path}) is "
                    f"missing required tags: {missing}"
                )
        return content

    def validate(self, theme, name, content=None):
        """Returns a list of missing {{tag}} placeholders -- empty list
        means the file satisfies its registered contract. A skeleton with
        no registry entry at all validates as OK (nothing to check
        against) rather than failing closed, so registering a skeleton is
        additive, not a prerequisite for it to render."""
        if content is None:
            content = self.get(theme, name, validate=False)
        required = self.registry.get_required_tags(theme, name)
        return [t for t in required if f"{{{{{t}}}}}" not in content]

    def validate_all(self, theme=None):
        """Pre-publish gate (Proposal §3.4/Suggestion #6): validates
        every registered skeleton for the given theme (or every theme if
        omitted) and returns {(theme, name): [missing_tags]} for any
        failures. Empty dict means everything registered is clean.

        Mirrors the same theme->default fallback used by _resolve_path()
        and SkeletonRegistry.get(): a theme with no registry rows of its
        own (the common case -- see §3.1, most themes share the
        'default' markup set) is checked against the 'default' rows
        rather than silently matching nothing at all. Without this, a
        real bug was caught during integration testing: requesting
        validate_all(theme='behtml') against a registry seeded only
        under theme='default' returned an empty failures dict even with
        a deliberately corrupted skeleton on disk, because the theme
        filter matched zero rows -- not because nothing was wrong."""
        failures = {}
        if theme is None:
            rows = self.registry.list_all()
        else:
            rows = self.registry.list_all(theme=theme)
            if not rows and theme != "default":
                rows = self.registry.list_all(theme="default")
        for row in rows:
            t, n = row["skeleton_theme"], row["skeleton_name"]
            try:
                path = self._resolve_path(theme if theme else t, n)
                if not os.path.exists(path):
                    failures[(theme or t, n)] = [f"file not found: {path}"]
                    continue
                with open(path, encoding="utf-8") as f:
                    content = f.read()
                missing = [tag for tag in row["required_tags"] if f"{{{{{tag}}}}}" not in content]
                if missing:
                    failures[(theme or t, n)] = missing
            except Exception as e:
                failures[(theme or t, n)] = [f"error reading skeleton: {e}"]
        return failures

    # ---- draft / diff / promote / discard ----

    def save_draft(self, theme, name, content):
        path = self._draft_path(theme, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
        return path

    def has_draft(self, theme, name):
        return os.path.exists(self._draft_path(theme, name))

    def diff_draft(self, theme, name):
        """Returns a unified diff (list of lines) between the live file
        and its staged draft, or None if no draft is staged."""
        draft_path = self._draft_path(theme, name)
        if not os.path.exists(draft_path):
            return None
        live_path = self._resolve_path(theme, name)
        live_lines = []
        if os.path.exists(live_path):
            with open(live_path, encoding="utf-8") as f:
                live_lines = f.readlines()
        with open(draft_path, encoding="utf-8") as f:
            draft_lines = f.readlines()
        return list(difflib.unified_diff(
            live_lines, draft_lines,
            fromfile=f"{name} (live, {theme})", tofile=f"{name} (draft, {theme})",
        ))

    def _backup_current(self, theme, name):
        live_path = self._resolve_path(theme, name)
        if not os.path.exists(live_path):
            return None
        history_dir = os.path.join(self.templates_root, HISTORY_DIRNAME, theme)
        os.makedirs(history_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = os.path.join(history_dir, f"{name}.{stamp}.html")
        shutil.copy2(live_path, backup_path)
        return backup_path

    def promote(self, theme, name):
        """Validates the staged draft against its registered tag
        contract, backs up the current live file, then overwrites live
        from the draft. Refuses (does not touch the live file) if
        validation fails -- a skeleton_version is only ever bumped on a
        successful promote, never on a draft save (Proposal Suggestion
        #9: the version should mean 'this shipped', not 'someone was
        working on it')."""
        draft_path = self._draft_path(theme, name)
        if not os.path.exists(draft_path):
            return False, "No draft staged for this skeleton."
        with open(draft_path, encoding="utf-8") as f:
            content = f.read()
        missing = self.validate(theme, name, content)
        if missing:
            return False, f"Refusing to promote -- missing required tags: {missing}"
        live_path = self._resolve_path(theme, name)
        backup_path = self._backup_current(theme, name)
        os.makedirs(os.path.dirname(live_path), exist_ok=True)
        tmp_path = live_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, live_path)
        os.remove(draft_path)
        self._cache.pop((theme, name), None)
        checksum = _sha256(content)
        self.registry.bump_version(theme, name, checksum)
        note = f"Promoted {name} for theme '{theme}' (v{self.registry.get(theme, name)['skeleton_version']})."
        if backup_path:
            note += f" Previous live version backed up to {backup_path}."
        return True, note

    def discard_draft(self, theme, name):
        path = self._draft_path(theme, name)
        if not os.path.exists(path):
            return False, "No draft staged for this skeleton."
        os.remove(path)
        return True, f"Discarded draft for {name} ({theme})."

    # ---- theme / factory reset ----

    def reset_to_factory(self, theme, factory_root):
        """Copies every file from resources/templates/_factory/default/
        onto resources/templates/default/ (or the given theme's own
        folder, if one exists) -- a plain file copy, never code. Only
        ever touches the requested theme's folder; other themes and
        their overrides are untouched (Proposal §Risks)."""
        target_dir = os.path.join(self.templates_root, theme)
        if not os.path.isdir(target_dir):
            target_dir = os.path.join(self.templates_root, "default")
        os.makedirs(target_dir, exist_ok=True)
        restored = []
        for fname in sorted(os.listdir(factory_root)):
            if not fname.endswith(".html"):
                continue
            src = os.path.join(factory_root, fname)
            dst = os.path.join(target_dir, fname)
            self._backup_current(theme, fname.replace(".html", ""))
            shutil.copy2(src, dst)
            restored.append(fname)
        self._cache.clear()
        return True, f"Reset {len(restored)} skeleton(s) to factory default: {', '.join(restored)}"

    def list_themes(self):
        themes = set()
        if os.path.isdir(self.templates_root):
            for entry in os.listdir(self.templates_root):
                full = os.path.join(self.templates_root, entry)
                if os.path.isdir(full) and entry != HISTORY_DIRNAME and not entry.startswith("_"):
                    themes.add(entry)
        return sorted(themes)

    def list_skeletons(self, theme):
        default_dir = os.path.join(self.templates_root, "default")
        names = set()
        for d in (os.path.join(self.templates_root, theme), default_dir):
            if os.path.isdir(d):
                for fname in os.listdir(d):
                    if fname.endswith(".html"):
                        names.add(fname[:-5])
        return sorted(names)
