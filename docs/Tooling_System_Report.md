# NewAgent Official Tooling System & Architecture Audit Report

**Author:** Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton  
**Date:** October 24, 2026  
**Project:** NewAgent  
**Report Scope:** Audit of NewAgent's existing tooling architecture, library routing (`lib/` vs `lib_extensions/`), and the config-gated Antigravity (`agy`) Skills Compatibility Layer.

---

## 1. Executive Answer: Does NewAgent Have an Official Tooling System in Place?

**Partially — NewAgent has an official, hardened internal Action Tag & Native Function-Calling system for core agent primitives, but it previously lacked a formal, unified plugin/registry contract for standalone CLI tools in `tools/` and external skill bundles.**

Specifically, NewAgent's tooling architecture is divided into **four distinct tiers**:

| Tier | Subsystem | Primary Module(s) | Dispatch Mechanism | Registration / Discovery State |
| :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | **REST Engine XML Action Tag System** | `lib/lib_bejson_newagent_actions.py` | 39 built-in XML tags (`<exec>`, `<read_file>`, `<bejson_*>`, `<agy_skill>`, etc.) + 2 fallback parsers (`<tool_call>` JSON & `[tag(...)]` bracket syntax) + pre/post hooks (`config/hooks.bejson`). | **Official & Hardened** (hardcoded tag whitelist `_VALID_ACTION_TAGS` + `ACTION_PATTERN` regex). |
| **Tier 2** | **Interactions Engine Native Tool Declarations** | `lib/lib_bejson_newagent_engine_interactions.py` | Gemini Interactions API `functionDeclarations` (`build_tool_declarations()`). | **Official but Partial Parity** (exposes 18 of the 39 REST action primitives; omits `bejson_*`, `checklist_*`, `html_report*`, `context_set`, `exec_bg`, `task_*`, `job_task_done`, and `agy_skill`). |
| **Tier 3** | **Bundled Standalone CLI Tools (`tools/`)** | `tools/NA-CMS`, `tools/NA-Chunker`, `tools/NA-MD2HTML`, `tools/NA-WebToolkit`, `tools/NA-Init`, `tools/key_admin.py` | Invoked as subprocesses via `<exec>python3 tools/...</exec>`. Surfaced to the LLM only via Context Bubble keyword triggers (`config/triggers.bejson`) or knowledge pool rows (`config/knowledge_pool.bejson`). | **Ad-Hoc / Unindexed Prior to Audit** (no central `tools_registry.bejson`; `knowledge_pool.bejson` still referenced a removed `tools/bookwriter/Cli_Bookwriter.py` while the 5 active `NA-*` tools had no trigger entries). |
| **Tier 4** | **Config-Gated Antigravity (`agy`) Skills Compatibility Layer** | `lib/lib_bejson_newagent_agy_skills.py` | Gated by `agy_skills_enabled` (`true`/`false`, default `false`) in `config/config.json`. Discovers `SKILL.md` bundles in `~/.gemini/config/skills/` and builtin skill directories; exposes `<agy_skill>` action tag and `/skills` slash command. | **Official & Config-Gated** (added October 24, 2026 per `agents.md` Directive 3). |

---

## 2. Detailed Analysis of Each Tooling Tier

### 2.1 Tier 1: REST Engine XML Action Tag Dispatcher (`lib_bejson_newagent_actions.py`)
In its default `rest` engine mode (`config["engine_mode"] == "rest"`), NewAgent instructs the model via `_SYSTEM_PROMPT_TEMPLATE` to emit raw XML action tags (up to `max_actions_per_turn = 10` per turn).

1. **Supported Action Tags (39 total)**:
   - **Shell & Process Execution**: `<exec>`, `<exec_bg>`, `<task_status>`, `<task_kill>`, `<task_list/>`
   - **Filesystem & Backup Operations**: `<read_file>`, `<write_file path="...">`, `<edit_file path="...">`, `<list_dir>`, `<tree_view>`, `<make_dir>`, `<delete_file>`, `<copy_file src="..." dst="..."/>`, `<diff_file>`, `<restore_file>`, `<checkpoint>`
   - **Search & Discovery**: `<find_files>`, `<search_text>`, `<fuzzy_find>`, `<http_get>`, `<env_get>`
   - **BEJSON 104/104a/104db Native Operations**: `<bejson_create>`, `<bejson_fields>`, `<bejson_add_field>`, `<bejson_delete_field>`, `<bejson_create_record>`, `<bejson_delete_record>`, `<bejson_set_value>`, `<bejson_columns>`
   - **Workflow, Checklists, Jobs & Reporting**: `<checklist_create>`, `<checklist_check>`, `<checklist_add>`, `<checklist_view>`, `<html_report>`, `<html_report_append>`, `<project_log>`, `<context_set>`, `<job_task_done id="..."/>`, `<request_continue>`, `<speak>`
   - **Antigravity Skills Compatibility (Config-Gated)**: `<agy_skill action="list|read|exec" name="..." script="..."/>`
2. **Multi-Format Parser Resilience (`parse_actions()`)**:
   - Primary pass extracts canonical XML tags via `ACTION_PATTERN`.
   - Fallback 1 (`_TOOL_CALL_BLOCK_PATTERN`) intercepts `<|tool_call_start|>...<|tool_call_end|>` and `<tool_call>...</tool_call>` blocks emitted by OpenRouter / third-party models and normalizes JSON or bracketed calls into canonical action dicts via `_map_tool_call_to_action()`.
   - Fallback 2 (`_LINE_BRACKET_CALL_PATTERN`) intercepts bare `[tag(...)]` lines when providers strip special tokens.
3. **Safety & Lifecycle Guards**:
   - Substring command denylist (`is_command_denylisted()`), optional confirmation gate (`confirmation_gate`), dry-run mode (`dryrun_mode`), automatic 24-hour file backups before any mutation (`record_backup()`), and pre/post shell hooks configured in `config/hooks.bejson` (`run_action_hook()`).

### 2.2 Tier 2: Interactions Engine Native Function-Calling (`lib_bejson_newagent_engine_interactions.py`)
When `engine_mode` is set to `"interactions"` (supported for Gemini provider models), `build_tool_declarations()` constructs native JSON Schema tool definitions for the Gemini Interactions endpoint:
- **Declared Tools (18)**: `exec`, `read_file`, `write_file`, `edit_file`, `list_dir`, `tree_view`, `make_dir`, `delete_file`, `copy_file`, `diff_file`, `restore_file`, `http_get`, `find_files`, `search_text`, `fuzzy_find`, `env_get`, `speak`, `checkpoint`.
- **Identified Parity Gap**: Newer action tags added to `lib_bejson_newagent_actions.py` (`bejson_*`, `checklist_*`, `html_report*`, `project_log`, `context_set`, `exec_bg`, `task_*`, `job_task_done`, `agy_skill`) are not yet declared in `build_tool_declarations()`.

### 2.3 Tier 3: Bundled Standalone CLI Tools (`tools/`) & Library Routing (`lib/` vs `lib_extensions/`)
The `tools/` directory contains standalone applications and CLI utilities that NewAgent (or the user) invokes via `<exec>`:

| Tool Path | Purpose | Config File (`BEJSON 104a`) | Library Routing |
| :--- | :--- | :--- | :--- |
| `tools/NA-CMS/` | Zero-SQL BEJSON 104/MFDB Content Management System (`newagent-manage.py`, `advanced_launcher.py`, `NewAgent_CMS_Admin.py`, `NewAgent_CMS_Publisher.py`) | `tools/NA-CMS/config.json` | Routes `shared_lib_directory` (`../../lib`) and `lib_extensions_directory` (`../../lib_extensions`) via `config.json`. |
| `tools/NA-Chunker/CLI_Chunker.py` | BEJSON 104a (`Chunked-104`) and 104db project chunker and unchunker | `tools/NA-Chunker/config/config.json` & `data/chunker_config.104a.bejson` | Routes `shared_lib_directory` (`../../lib`) and `lib_extensions_directory` (`../../lib_extensions`) via `config/config.json` (with embedded fallback). |
| `tools/NA-MD2HTML/MD_To_HTML.py` | Markdown-to-HTML dark-theme batch converter | `tools/NA-MD2HTML/md-to-html.config.json` | Routes `shared_lib_directory` (`../../lib`) and `lib_extensions_directory` (`../../lib_extensions`) via `md-to-html.config.json`. |
| `tools/NA-WebToolkit/Cli_Web_Toolkit.py` | DuckDuckGo search, AI/standard page extraction, and mobile terminal browser | `tools/NA-WebToolkit/config/config.json` | Routes `shared_lib_directory` (`../../lib`) and `lib_extensions_directory` (`../../lib_extensions`) via `config/config.json` in `env_loader.py`. |
| `tools/NA-Init/CLI_Init.py` | Standalone CLI to scaffold/upsert per-directory `context.bejson` sections | `tools/NA-Init/config/config.json` | Routes `shared_lib_directory` (`../../lib`) and `lib_extensions_directory` (`../../lib_extensions`) via `config/config.json`. |
| `tools/key_admin.py` | API key registry & key-ledger inspection/flagging CLI | `config/config.json` (root) | Resolves `PROJECT_ROOT / "lib"`. |

#### Library Synchronization & Consolidation Performed (Directives 1 & 2)
- **Core Libraries (`lib/`)**: Verified all 7 Core Release 300 BEJSON 104 libraries in `lib/` match `/storage/emulated/0/Admin/Libraries/libraries_104/Lib_PY/Core/` byte-for-byte (`lib_bejson_Core_bejson_core.py` v2.0.10, `bejson_env.py` v2.3.0, `bejson_errors.py` v2.5.0, `bejson_path_guard.py` v1.3.0, `bejson_validator.py` v2.2.7, `mfdb_core.py` v2.3.5, `mfdb_validator.py` v2.2.4).
- **Extended Libraries (`lib_extensions/`)**: Synchronized all 48 Release 300 BEJSON 104 Python libraries from `/storage/emulated/0/Admin/Libraries/libraries_104/Lib_PY/` (`AI/`, `Chunker/`, `Core/`, `MD/`, `Utility/`) plus the 5 `lib_bejson_NewAgentCMS_*.py` modules into `/storage/emulated/0/Admin/Dev/Python/Development/NewAgent/lib_extensions/` (53 modules total).
- **Eliminated Duplicate Per-Tool Library Sprawl**: Removed hardcoded `/storage/emulated/0/Admin/libraries/...` fallbacks and broken `src/lib` references across `tools/`, routing all tool imports cleanly through each tool's BEJSON 104a `config.json` to `../../lib` and `../../lib_extensions`.

---

## 3. Tier 4: Config-Gated Antigravity (`agy`) Skills Compatibility Layer (`lib_bejson_newagent_agy_skills.py`)

Per Directive 3 of `agents.md`, NewAgent now includes a first-class compatibility layer for Antigravity (`agy`) `SKILL.md` bundles (`lib/lib_bejson_newagent_agy_skills.py`), providing a structured alternative/complement to the raw tool system.

### 3.1 Strict Configuration Gate (`config/config.json`)
- Controlled by `agy_skills_enabled` (`"false"` by default in `config/config.json`, `False` in `DEFAULT_CONFIG` in `lib/lib_bejson_newagent_config.py`).
- **When `agy_skills_enabled` is `false`**:
  - `is_agy_skills_enabled(config)` returns `False`.
  - `discover_installed_agy_skills()`, `match_agy_skills_for_prompt()`, and `build_agy_skills_context_section()` return empty results immediately with **zero filesystem I/O and zero prompt token overhead**.
  - Any `<agy_skill ...>` tag emitted while disabled is rejected immediately with `[DISABLED] Antigravity (agy) skills compatibility layer is disabled (agy_skills_enabled=false in config/config.json)`.
- **When `agy_skills_enabled` is `true`** (toggled via `/skills on` or by editing `config/config.json`):
  - Scans `agy_skills_directories` (`/data/data/com.termux/files/home/.gemini/config/skills` and `/data/data/com.termux/files/home/.gemini/antigravity-cli/builtin/skills`) with directory `mtime` caching.
  - Parses YAML frontmatter (`name`, `description`) and indexes bundled `scripts/`, `references/`, and `resources/`.
  - Injects a budget-capped `## Antigravity (agy) Skills Compatibility Layer (ENABLED)` section into `Context_Bubble.md` with top prompt-matched skills.
  - Enables `<agy_skill action="list"/>`, `<agy_skill name="<skill>" action="read"/>`, and `<agy_skill name="<skill>" action="exec" script="scripts/..."/>` in `run_action_queue()`.
  - Enables `/skills [on|off|list [filter]|info <name>]` in interactive CLI/Web sessions.

---

**Author Credit:** Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
