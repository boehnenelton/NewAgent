# AGENTS.md

## Build / Lint / Test / Run

No build step (flat Python/Flask project, no compiler/bundler).

```bash
# Run the full pytest suite (path-guard traversal protection,
# MFDB manifest/entity validation) — operates on a temp copy, never touches
# the live storage/mfdb/ tree directly:
cd tests && python3 -m pytest -v

# Syntax check any file before shipping it:
python3 -m py_compile src/web/NewAgent_CMS_Admin.py

# Full smoke-test (syntax is not enough — a NameError from a missing import
# only surfaces on actual import, not py_compile):
python3 -c "import sys; sys.path.insert(0,'src/web'); import NewAgent_CMS_Admin"

# Run a service directly:
python3 src/web/NewAgent_CMS_Admin.py
python3 src/web/NewAgent_CMS_Publisher.py
```

No linter/formatter config is present in this project — match the existing
style in the file you're editing rather than introducing a new one.

## Fork Note

This is the **NewAgent CMS** fork of the old BEJSON CMS project. Page
Editor V1/V2 and the AI Persona Hub (Profile Manager) were removed
entirely, along with all prior logs and change history. Only the Admin app
(+ its 4 Blueprints) and the Publisher survive. `.bejson_project.json` and
`newagent-manage.py` were reset/renamed as part of this fork — do not
expect either to carry forward history from the old BEJSON CMS project.

## Code Style & Conventions

- **Library naming standard**: `lib_bejson_<Family>_<name>.py` for every
  library this project uses (e.g. `lib_bejson_Core_bejson_core.py`,
  `lib_bejson_NewAgentCMS_cms_core.py`) — shared/Core libs live in
  NewAgent's top-level `lib/`, CMS-specific libs live in
  `tools_lib/na-cms/` (2026-08-24: NA-CMS no longer keeps a private
  `src/lib/` copy of anything — see Library Immutability below).
  Existing files predating this standard are NOT renamed in place.
- **Snake_case** for all Python variables/functions/fields. **PascalCase**
  only for BEJSON 104a custom top-level headers.
- **Self-describing variable names** are required in all new code — no
  single-letter locals.
- **File headers**: every script/module carries a header block — `Library`,
  `Family`, `Description`, `Version`, `Date`, `RELATIONAL_ID` (a UUID4 that
  changes on every real edit, acting as a recency fingerprint). Bump the
  header version and mint a fresh `RELATIONAL_ID` on every functional
  change, not on doc-only or logging-only changes.
- **Library Immutability**: files under NewAgent's shared top-level
  `lib/lib_bejson_Core_*` are Core-family libraries and are frozen —
  never edited except for a verified, reproduced bug (this reroute
  itself required one such fix: `safe_extract_zip()` had drifted into
  NA-CMS's now-deleted private copy and needed porting back). Files
  under `tools_lib/na-cms/lib_bejson_NewAgentCMS_*` are this app's own
  family libraries and may be altered freely when this app needs it.

## Architectural Rules

- **BEJSON positional integrity**: every entity's `Fields` order must match
  `Values` order exactly. New fields are appended to the END of the array —
  never inserted mid-array — or every existing row's positional indexing
  breaks.
- **CMSCore is the only DB interface** application code should use
  (`get_records` / `add_record` / `update_record` / `delete_record` /
  `get_field_map` / `sync_manifest_count`). Never read `storage/mfdb/**`
  files directly — positional field order is an implementation detail
  `CMSCore` already resolves by field name.
- **`update_record()` does a partial merge** — only keys present in the
  `updates` dict are touched. Never pass a field "just to be safe" unless you
  intend to overwrite it.
- **Two-part page write**: a page is a `PageRecord` row in the manifest PLUS
  a standalone 104db content file at `storage/mfdb/pages_db/<uuid>.json`.
  Both are required — writing one without the other produces a 404 or an
  empty page.
- **`sync_count=False` + a single `sync_manifest_count()` call** for any loop
  that writes multiple records in one request — per-record fsync is
  expensive on constrained Android hardware.
- **Media Library is deliberately low-peak-memory**: single serial background
  worker (no multiprocessing — forking duplicates the whole process's memory
  footprint under pressure), PIL `draft()` mode for large JPEGs, header-only
  pixel-count caps before any decode, streamed uploads, chunked hashing,
  server-side pagination. Do not "optimize" this back toward parallelism.

## Directory Map

| Path | Contents |
|---|---|
| `src/web/NewAgent_CMS_Admin.py` | Thin entry point — registers the 4 Blueprints, starts Flask |
| `src/web/NewAgent_CMS_Shared.py` | Shared constants, path resolution, template rendering (`R()`), auth |
| `src/web/NewAgent_CMS_System.py` | Dashboard, site config, factory reset |
| `src/web/NewAgent_CMS_Content.py` | Pages, categories, apps, authors, HTML import |
| `src/web/NewAgent_CMS_Media.py` | Media Library (upload/gallery/delete/replace/external links) |
| `src/web/NewAgent_CMS_Interface.py` | Home, nav/social/ad config, publish trigger |
| `src/web/NewAgent_CMS_Publisher.py` | Static site generator, reads MFDB, writes `storage/builds/` |
| `src/web/NewAgent_CMS_Renderers.py` | Polymorphic page-type strategy renderers used by the Publisher |
| `src/newagent-manage.py` | Headless CLI — see `docs/CLI_GUIDE.md` |
| `../../lib/lib_bejson_Core_*` | Shared Core libraries (NewAgent top-level `lib/`) — parsing, validation, atomic writes, path guarding (frozen) |
| `../../tools_lib/na-cms/lib_bejson_NewAgentCMS_cms_core.py` | `CMSCore` — the only DB interface application code should call |
| `../../tools_lib/na-cms/lib_bejson_NewAgentCMS_cms_mfdb.py` | `MFDB_CMS_Manager` — legacy disconnected workspace/archive tooling (`mount`/`commit`, deprecated) |
| `../../tools_lib/na-cms/lib_bejson_NewAgentCMS_cms_config.py` | CMS-level config helpers |
| `../../tools_lib/na-cms/lib_bejson_NewAgentCMS_cms_ports.py` | Port resolution: env var > config.json > default (admin/publisher only) |
| `../../tools_lib/na-cms/lib_bejson_NewAgentCMS_cms_skeletons.py` | `SkeletonLoader`/`SkeletonRegistry` — draft/promote skeleton workflow |
| `storage/mfdb/site_master/` | The manifest + per-entity BEJSON 104 files (the actual database) |
| `storage/mfdb/pages_db/` | One 104db content file per page/post, keyed by `page_uuid` |
| `resources/templates/` | Jinja2/HTML skeleton templates for both the admin UI and the published site |
| `resources/styles/` | `dark.css` / `light.css`, synced into `storage/builds/style.css` on publish |
| `tests/` | pytest suite — operates on temp copies only, never the live database |

---
Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
