# Technical Specification & Documentation: Cli_Bookwriter (v1.2.0 PKG 102)

**Author:** Elton Boehnen  
**Email:** boehnenelton2024@gmail.com  
**Website:** https://boehnenelton2024.pages.dev  
**Repository:** https://github.com/boehnenelton  
**RELATIONAL_ID:** `2f3a4b5c-6d7e-4f8a-9b0c-1d2e3f4a5b66`  
**BEJSON Specification:** 104a Primitive Key-Mapped Matrix Table  

---

## 1. Executive Summary & Core Philosophy

`Cli_Bookwriter` is an autonomous, state-persistent CLI system engineered for long-form book creation using Gemini Large Language Models. Built on top of the **BEJSON 104a** tabular format, `Cli_Bookwriter` solves the core failure modes of standard LLM writing workflows: context drift, structural inconsistency, content duplication, and loss of state upon process termination.

### 1.1 The Context Degradation Problem
Standard single-prompt LLM generation degrades rapidly beyond ~2,000 words. When asked to generate an entire book in a single response, language models compress narrative depth, omit technical details, and synthesize generic summaries. 

### 1.2 The Chained-Context Solution
`Cli_Bookwriter` adopts the AuthorCMS chained-context architecture:
1. **Plan Scope Injection**: The full structural outline of the book is provided as non-writing reference in every chapter prompt, allowing the AI to gauge pacing and avoid premature coverage of future topics.
2. **Preceding Chapter Continuity**: The complete text of chapter $N-1$ is injected into the context window for chapter $N$, ensuring immediate stylistic, terminology, and narrative continuity.
3. **Reference Bubble**: User-provided research, notes, or background context files remain persistently attached across all chapters.

```
       ┌────────────────────────────────────────────────────────┐
       │                 Attached Context Bubble                │
       └───────────────────────────┬────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           Chapter Prompt (N)                            │
├─────────────────────────────────────────────────────────────────────────┤
│ 1. Current Chapter Assignment: Title & Objective                       │
│ 2. Complete Book Plan Scope (Outline)                                  │
│ 3. Attached Context Reference Text                                     │
│ 4. Chapter (N-1) Full Text Output (Continuity Buffer)                   │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       Gemini AI Generation Engine                       │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       Brand & Text Sanitization                         │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                   BEJSON 104a Atomic Database Storage                    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Architectural Design & Component Breakdown

The codebase is strictly modularized under `app/`, operating deterministically relative to `SCRIPT_PATH`.

```
Cli_Bookwriter/
├── Cli_Bookwriter.py             # Single-shot Argparse entrypoint launcher
├── bejson_project.json           # Root package tracking manifest (BEJSON 104a)
├── config.json                   # Runtime configuration file (BEJSON 104a)
├── README.md                     # Overview & command reference
├── DOCUMENTATION.md              # Detailed technical specification (this document)
├── app/                          # Core application modules
│   ├── book_writer.py            # Chained generation engine & HTML compiler
│   ├── config.py                 # SCRIPT_PATH resolution & directory bootstrap
│   ├── context_manager.py        # Context bubble & manifest tracking
│   ├── gemini_client.py         # REST API wrapper for Gemini models
│   ├── key_loader.py            # Hierarchical API key resolution engine
│   ├── plan_manager.py           # BEJSON plan generation & parsing
│   ├── state.py                  # Persistent selection & toggle state
│   └── text_correction.py       # Brand remediation & text sanitizer
├── books/
│   ├── BEJSON/                   # Working BEJSON 104a book databases
│   └── HTML/                     # Compiled single-file HTML outputs
├── data/
│   ├── context/                  # Bubble directory & tracking manifest
│   ├── persist/                  # Selection state storage
│   ├── plans/                    # Generated BEJSON 104a outline files
│   └── temp/                     # Scratch per-chapter markdown files
├── lib/
│   └── Core/                     # Immutable BEJSON Core library dependencies
└── secure/
    └── .env                      # Local environment key storage
```

---

## 3. Core Modules Specification

### 3.1 Entrypoint Launcher (`Cli_Bookwriter.py`)
`Cli_Bookwriter.py` is a single-shot POSIX command-line utility. It instantiates the module hierarchy, parses command-line arguments using `argparse`, resolves environment configurations, and executes the requested state mutations or generation workflows.

#### Key Functions:
- `build_arg_parser()`: Defines options across Plan, Book Writing, Context, and Misc parameter groups.
- `handle_context_mutations(args, ctx)`: Handles adding, selecting, deselecting, listing, and removing context elements.
- `make_generate_text_fn(api_key, model)`: Factory function binding API key, model ID, and system instruction for generation calls.
- `main()`: Primary orchestration loop.

### 3.2 Dynamic Path Resolution & Configuration (`app/config.py`)
In accordance with the BEJSON Ecosystem Mandates, `config.py` dynamically resolves `SCRIPT_PATH` to guarantee full portability across execution environments.

```python
def get_script_path() -> Path:
    return Path(__file__).resolve().parent.parent

SCRIPT_PATH = get_script_path()
```

#### Configuration Schema (`config.json`):
`config.py` enforces a BEJSON 104a configuration schema:
```json
{
  "Format": "BEJSON",
  "Format_Version": "104a",
  "Format_Creator": "Elton Boehnen",
  "Records_Type": ["ScriptConfig"],
  "Fields": [
    {"name": "setting_name", "type": "string"},
    {"name": "setting_value", "type": "any"},
    {"name": "description", "type": "string"}
  ],
  "Values": [
    ["dotenv_path", "secure/.env", "Relative or absolute path to .env file."],
    ["use_external_paths", false, "Toggle to allow script to operate outside of local ecosystem."],
    ["local_lib_directory", "lib/", "Relative path to local dep folder."],
    ["master_lib_source", "/storage/emulated/0/Admin/libraries", "Fallback source for BEJSON libraries."],
    ["log_level", "INFO", "Default log level."]
  ]
}
```

### 3.3 Persistent Selection State (`app/state.py`)
Because `Cli_Bookwriter` is invoked statelessly per command call, state parameters are stored in `data/persist/selection_state.104a.bejson`.

#### Schema:
```json
{
  "Format": "BEJSON",
  "Format_Version": "104a",
  "Format_Creator": "Elton Boehnen",
  "Records_Type": ["SelectionState"],
  "Fields": [
    {"name": "selected_plan_name", "type": "string"},
    {"name": "auto_run_tasks", "type": "boolean"}
  ],
  "Values": [
    ["quantum-computing", true]
  ]
}
```
- `selected_plan_name`: Active plan slot currently targeted for generation.
- `auto_run_tasks`: Persistent boolean toggle determining whether `--write-book` runs all chapters consecutively (`True`) or pauses after a single chapter (`False`).

---

### 3.4 API Key Loader & Fallback Resolver (`app/key_loader.py`)

`key_loader.py` enforces a 3-stage resolution process to obtain a valid Gemini API key:

```
┌─────────────────────────────────────────────────────────┐
│ Stage 1: Local .env File                                │
│ Reads file defined by config.json (default: secure/.env)│
└───────────────────────────┬─────────────────────────────┘
                            │ (If not found / empty)
                            ▼
┌─────────────────────────────────────────────────────────┐
│ Stage 2: OS Environment Variables                       │
│ Checks GEMINI_KEY_1..21, GEMINI_API_KEY, GOOGLE_API_KEY │
└───────────────────────────┬─────────────────────────────┘
                            │ (If not found / empty)
                            ▼
┌─────────────────────────────────────────────────────────┐
│ Stage 3: Device-Wide BEJSON Env Files                   │
│ Reads /storage/emulated/0/env_file.json                 │
│ Automatically appends discovered keys to local .env     │
└─────────────────────────────────────────────────────────┘
```

#### Template Export:
`export_env_template(target_path)` generates a clean `.env` template file:
```ini
# Cli_Bookwriter — Environment Configuration
# API Keys & Runtime Configuration

# Gemini API Keys (List in order of priority)
GEMINI_API_KEY=
GEMINI_KEY_1=
GEMINI_KEY_2=
GEMINI_KEY_3=

# Optional model override
# DEFAULT_MODEL=gemini-2.5-flash
```

---

### 3.5 Context Manager (`app/context_manager.py`)

The context manager manages user-attached research and documentation. When files or directories are added:
1. Files are copied into `data/context/bubble/`.
2. Metadata is logged to `data/context/context_tracking.104a.bejson`.
3. `build_active_context_text()` aggregates all active context files into a single structured string for prompt inclusion.

#### Tracking Manifest Fields:
- `entry_id` (string): Unique identifier GUID.
- `item_type` (string): `"file"` or `"folder"`.
- `path` (string): Source file path.
- `bubble_path` (string): Relative path inside `data/context/bubble/`.
- `active` (boolean): Ingestion toggle flag.

---

### 3.6 Plan Manager (`app/plan_manager.py`)

`plan_manager.py` handles outline generation and parsing.

#### Outline Generation Prompt:
When `--generate-plan` is called, `plan_manager.py` builds an instruction prompt requesting JSON array output containing chapter tasks:

```json
{
  "Writing_Title": "Title of the Book",
  "Writing_Type": "Non-Fiction Guide",
  "Writing_Category": "Technology",
  "Book_Goal": "Comprehensive introduction to the subject.",
  "Chapters": [
    {
      "Task_Name": "Chapter 1: Foundations of Quantum Mechanics",
      "Task_Goal": "Introduce qubits, superposition, and entanglement."
    }
  ]
}
```

The parsed output is saved to `data/plans/<plan_name>.json` as a BEJSON 104a document.

---

### 3.7 Chained Generation Engine & HTML Compiler (`app/book_writer.py`)

`book_writer.py` is the central generation and assembly module.

#### Multi-Entity Database Schema (`books/BEJSON/<plan_name>.bejson`):
Each working book record is a BEJSON 104a document storing both book metadata and written chapters:

```json
{
  "Format": "BEJSON",
  "Format_Version": "104a",
  "Format_Creator": "Elton Boehnen",
  "Records_Type": ["Book", "Chapter"],
  "Fields": {
    "Book": [
      {"name": "entry_id", "type": "string"},
      {"name": "topic", "type": "string"},
      {"name": "title", "type": "string"},
      {"name": "plan_name", "type": "string"},
      {"name": "generation_date", "type": "string"}
    ],
    "Chapter": [
      {"name": "chapter_number", "type": "integer"},
      {"name": "chapter_title", "type": "string"},
      {"name": "content", "type": "string"}
    ]
  },
  "Book": [
    ["quantum-computing", "Quantum Computing Guide", "Quantum Computing", "quantum-computing", "2026-08-10T22:00:00Z"]
  ],
  "Chapters": [
    [1, "Foundations of Quantum Mechanics", "# Chapter 1..."]
  ]
}
```

#### Chapter Generation Loop:
For each chapter in the plan:
1. Check if `chapter_number` already exists in `Chapters`. If present, skip writing (Resume mechanism).
2. Construct prompt using `CHAPTER_PROMPT_TEMPLATE`.
3. Invoke Gemini API.
4. Pass output through `text_correction.fix_text()`.
5. Append chapter to BEJSON record and execute atomic write to disk.
6. Write scratch copy to `data/temp/<plan_name>/<chapter_number>_<slug>.md`.
7. Check `auto_run`: if `False`, break loop after 1 chapter.
8. Upon completing all chapters, invoke `_compile_single_html()` and clear scratch files.

#### HTML Compilation Engine:
`_compile_single_html()` converts Markdown fragments into a single, self-contained HTML page formatted with CSS typography:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Book Title</title>
<style>
body{background:#FFFFFF;color:#000000;font-family:Inter,sans-serif;max-width:800px;margin:0 auto;padding:2rem;}
h1,h2,h3{font-family:'Source Code Pro',monospace;}
pre{background:#000000;color:#FFFFFF;padding:1rem;overflow-x:auto;}
article{margin-bottom:3rem;}
footer{margin-top:3rem;border-top:1px solid #000;padding-top:1rem;font-size:0.85rem;}
</style>
</head>
<body>
<h1>Book Title</h1>
<p><em>Book Goal / Topic</em></p>
<article id="chapter-1">
<h2>Chapter 1: Title</h2>
<p>Content...</p>
</article>
<footer>
Elton Boehnen | boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
</footer>
</body>
</html>
```

---

### 3.8 Brand & Text Sanitizer (`app/text_correction.py`)

`text_correction.py` sanitizes raw model output prior to database persistence. It performs regex replacement of brand terms, formatting quirks, and broken escape patterns to ensure output compliance.

---

## 4. Complete CLI Command & Option Matrix

| Flag | Short Aliases | Argument | Description |
| :--- | :--- | :--- | :--- |
| `--new-plan` | | `NAME` | Select and initialize a plan slot name |
| `--select-plan` | | `NAME` | Switch active selection state to an existing plan |
| `--generate-plan` | | `PROMPT` | AI outline generation prompt |
| `--chapters` | | `N` | Chapter count for outline generation (Default: 8) |
| `--view-plan` | | | Render the active plan structure to terminal |
| `--list-plans` | | | List all saved plans in `data/plans/` |
| `--write-book` | `--resume-plan` | | Execute or resume chapter writing for active plan |
| `--auto-run` | | `[on\|off]` | Toggle persistent multi-chapter iteration loop |
| `--add-context-file` | `--acf`, `--Add-Context-File` | `PATH` | Track and copy a reference file |
| `--add-context-folder`| `--acd`, `--Add-Context-Folder`| `PATH` | Track and copy a reference folder |
| `--select-context-file`| `--scf` | `ID_OR_NAME` | Set context file status to active |
| `--select-context-folder`| `--scd` | `ID_OR_NAME` | Set context folder status to active |
| `--deselect-context-file`| `--dcf` | `ID_OR_NAME` | Set context file status to inactive |
| `--deselect-context-folder`| `--dcd` | `ID_OR_NAME` | Set context folder status to inactive |
| `--remove-context-file`| `--rcf` | `ID_OR_NAME` | Untrack and delete context file copy |
| `--remove-context-folder`| `--rcd` | `ID_OR_NAME` | Untrack and delete context folder copy |
| `--list-context` | | | List tracked context elements |
| `--export-env-template` | | `[PATH]` | Export environment template file |
| `--model` | | `MODEL_ID` | Specify Gemini model string |
| `--status` | | | Display system status, key state, and context counts |

---

## 5. End-to-End Operational Workflows

### 5.1 Workflow A: Fully Automated End-to-End Book Generation

```bash
# 1. Inspect environment status
python3 Cli_Bookwriter.py --status

# 2. Attach background research material
python3 Cli_Bookwriter.py --add-context-folder ./research/

# 3. Create new plan slot and generate 5-chapter outline
python3 Cli_Bookwriter.py --new-plan deep-learning --generate-plan "A technical guide to Deep Learning and Transformers" --chapters 5

# 4. Ensure Auto-Run is enabled
python3 Cli_Bookwriter.py --auto-run on

# 5. Execute full generation & compilation
python3 Cli_Bookwriter.py --write-book
```

**Result**: Output compiled single-file document saved to `books/HTML/deep-learning.html`.

---

### 5.2 Workflow B: Interactive Single-Step Chapter Writing

```bash
# 1. Select plan and disable Auto-Run
python3 Cli_Bookwriter.py --select-plan deep-learning
python3 Cli_Bookwriter.py --auto-run off

# 2. Write Chapter 1
python3 Cli_Bookwriter.py --write-book
# (Script completes Chapter 1, saves to BEJSON record, and pauses)

# 3. Inspect scratch markdown file
cat data/temp/deep-learning/01_Chapter_1_Title.md

# 4. Resume to write Chapter 2
python3 Cli_Bookwriter.py --resume-plan
```

---

### 5.3 Workflow C: Interruption Recovery & Failure Resume

If execution is terminated during chapter generation (e.g., terminal drop or API rate limit):

```
[OK] Writing chapter 3/5: "Convolutional Neural Networks"...
[ERROR] book writing failed: API key quota exceeded
```

No data is lost. Chapters 1 and 2 are stored in `books/BEJSON/deep-learning.bejson`. To resume:

```bash
# Simply execute resume command once API key/network is restored
python3 Cli_Bookwriter.py --resume-plan

# Output:
# [OK] Chapter 1/5 "Introduction" already written — skipping (resume).
# [OK] Chapter 2/5 "Neural Networks" already written — skipping (resume).
# [OK] Writing chapter 3/5: "Convolutional Neural Networks"...
```

---

## 6. BEJSON Schema Integrity & Validation Rules

All structured files produced or read by `Cli_Bookwriter` adhere to BEJSON specifications:

1. **Mandatory Headers**:
   - `Format`: `"BEJSON"`
   - `Format_Version`: `"104a"`
   - `Format_Creator`: `"Elton Boehnen"`
   - `Records_Type`: Array of entity strings.
   - `Fields`: Definitions of field names and data types.
   - `Values`: Dense record arrays matching `Fields` length exactly.

2. **Positional Integrity**: Access to record values is performed via positional indices rather than string key lookups, maintaining high execution speed and low memory overhead.

3. **Atomic Operations**: All file mutations use `bejson_core_atomic_write` to write to a temporary file before atomic renaming, preventing file corruption during unexpected process failure.

---

## 7. Troubleshooting & Diagnostics

| Symptom | Cause | Resolution |
| :--- | :--- | :--- |
| `[ERROR] no active plan.` | No plan has been selected or created. | Run `python3 Cli_Bookwriter.py --new-plan NAME` or `--select-plan NAME`. |
| `[ERROR] no Gemini API key found.` | API key missing from `.env` and environment. | Export template via `--export-env-template`, populate `secure/.env`, or define `GEMINI_KEY_1`. |
| `[ERROR] plan 'NAME' not found in data/plans/.` | Plan name selected does not exist on disk. | Run `--generate-plan "PROMPT"` to generate the plan. |
| Auto-run not triggering loop | `auto_run_tasks` is set to `False`. | Run `python3 Cli_Bookwriter.py --auto-run on` to set persistent mode. |
| Context files not appearing in prompts | Context items are marked inactive. | Run `python3 Cli_Bookwriter.py --list-context` and verify `*` active marker. Use `--select-context-file` to activate. |

---

## 8. Development & Maintenance Log

### Version History:
- **1.0.0** (2026-08-05): Initial build of `Cli_Bookwriter` per AuthorCMS plan specification.
- **1.1.0** (2026-08-10): Added persistent auto-run toggle (`--auto-run on/off`), single-step chapter execution, and automatic HTML compilation upon completing plan tasks.
- **1.2.0** (2026-08-10): Added BEJSON 104a `config.json` loader, `--export-env-template` option, configurable `dotenv_path`, and fallback key populator.

---

## 10. Deep-Dive API & Functions Reference

### 10.1 `Cli_Bookwriter.py` (CLI Controller)

#### `build_arg_parser() -> argparse.ArgumentParser`
Initializes the `argparse` argument parser, configuring argument groups for Plan Management, Book Writing, Context Operations, and System Utilities.

- **Returns**: Fully configured `ArgumentParser` instance.
- **Side Effects**: None.

#### `handle_context_mutations(args: argparse.Namespace, ctx: context_manager.ContextManager) -> None`
Evaluates context-related flags (`add_context_file`, `add_context_folder`, `select_context_file`, etc.) and executes mutations against the `ContextManager`.

- **Parameters**:
  - `args`: Parsed CLI namespace.
  - `ctx`: Active `ContextManager` instance.
- **Console Output**: Prints `[OK]` status messages for added, modified, or removed context items.

#### `make_generate_text_fn(api_key: str, model: str, system_instruction: str = None) -> Callable[[str], str]`
Higher-order function returning a closure bound to the specified Gemini API key, model ID, and system instruction.

- **Parameters**:
  - `api_key`: Resolved Gemini API key string.
  - `model`: Model string (e.g. `gemini-2.5-flash`).
  - `system_instruction`: Optional system prompt string.
- **Returns**: Function `generate_text_fn(prompt: str) -> str`.

---

### 10.2 `app/config.py` (Path Bootstrap & Configuration Engine)

#### `get_script_path() -> Path`
Resolves the absolute root directory of the `Cli_Bookwriter` package.

- **Returns**: `Path` object representing `SCRIPT_PATH`.

#### `bootstrap_dirs() -> None`
Creates all required subdirectory structures (`secure/`, `data/plans/`, `data/persist/`, `data/context/`, `data/temp/`, `books/BEJSON/`, `books/HTML/`) if they do not exist, and triggers `ensure_config_file()`.

#### `ensure_config_file() -> dict`
Checks for the presence of `config.json` in `SCRIPT_PATH`. If absent, serializes `DEFAULT_CONFIG_DOC` (BEJSON 104a) to disk.

- **Returns**: Dictionary representing the active `config.json` BEJSON document.

#### `get_config_setting(setting_name: str, default: Any = None) -> Any`
Queries `config.json` for the specified `setting_name` value using BEJSON 104a matrix lookups.

- **Parameters**:
  - `setting_name`: Key string to look up in `Values`.
  - `default`: Fallback value if `setting_name` is absent.
- **Returns**: Setting value.

---

### 10.3 `app/state.py` (SelectionState Manager)

#### Class: `SelectionState(dir_persist: Path)`
Manages persistent state across execution calls using `data/persist/selection_state.104a.bejson`.

##### Properties:
- `selected_plan_name -> Optional[str]`: Gets or sets the active plan name slot.
- `auto_run_tasks -> bool`: Gets or sets the persistent auto-run toggle.

##### Internal Methods:
- `_load_selection_state_doc()`: Loads `selection_state.104a.bejson` via `lib_bejson_Core`. Automatically performs 1-column to 2-column migration if updating from older state schemas.
- `_save_selection_state_doc()`: Executes atomic write to save state modifications to disk.

---

### 10.4 `app/key_loader.py` (Environment Key Loader)

#### `export_env_template(target_path: Path) -> Path`
Writes a clean `.env` template file containing default key headers to `target_path`.

- **Parameters**: `target_path`: Destination file path.
- **Returns**: `Path` object of created file.

#### `_parse_dotenv_file(dotenv_path: Path) -> dict[str, str]`
Parses a standard `.env` file (ignoring comments `#` and blank lines) into a key-value dictionary.

#### `_append_keys_to_template(dotenv_path: Path, discovered_keys: dict[str, str]) -> None`
Appends newly discovered keys (from system fallback files) to the target `.env` file without overwriting existing entries.

#### `load_gemini_api_key(script_path: Path, dotenv_rel_path: str = "secure/.env") -> str`
Executes 3-tier key resolution hierarchy.

- **Parameters**:
  - `script_path`: `SCRIPT_PATH` root path.
  - `dotenv_rel_path`: Relative or absolute path to local `.env` file.
- **Returns**: Valid Gemini API key string, or empty string `""` if none found.

---

### 10.5 `app/context_manager.py` (Context Bubble Manager)

#### Class: `ContextManager(dir_context: Path, dir_bubble: Path)`
Tracks attached research files and directories.

##### Methods:
- `add_file(source_path_str: str) -> list`: Copies file to `dir_bubble`, logs entry in `context_tracking.104a.bejson`, and returns tracking row.
- `add_folder(source_folder_str: str) -> list`: Copies directory to `dir_bubble` and logs entry.
- `toggle_active_file(target_id_or_name: str, active: bool) -> None`: Sets active flag for a tracked file.
- `toggle_active_folder(target_id_or_name: str, active: bool) -> None`: Sets active flag for a tracked folder.
- `remove_file(target_id_or_name: str) -> None`: Removes file from bubble and tracking manifest.
- `remove_folder(target_id_or_name: str) -> None`: Removes folder from bubble and tracking manifest.
- `build_active_context_text() -> str`: Concatenates all active context files into a single structured prompt payload string.

---

### 10.6 `app/plan_manager.py` (Plan Generator & Manager)

#### Class: `PlanManager(dir_plans: Path)`
Manages outline generation, parsing, and BEJSON file serialization under `data/plans/`.

##### Methods:
- `plan_exists(plan_name: str) -> bool`: Checks if `<plan_name>.json` exists in `data/plans/`.
- `build_prompt(topic_prompt: str, chapter_count: int, active_context_text: str) -> str`: Constructs prompt instructing Gemini to output a structured JSON chapter outline.
- `parse_ai_response(response_text: str) -> dict`: Extracts JSON block from model response and validates fields.
- `save_plan(plan_name: str, plan_doc: dict) -> Path`: Writes plan dictionary to `data/plans/<plan_name>.json` in BEJSON 104a format.
- `load_plan(plan_name: str) -> dict`: Loads plan document from disk.
- `list_plan_names() -> list[str]`: Returns list of all available plan names.

---

### 10.7 `app/book_writer.py` (Sequential Engine & HTML Compiler)

#### Class: `BookWriter(dir_books_bejson: Path, dir_books_html: Path, dir_temp: Path)`
Engine for chapter generation, BEJSON storage, and HTML compilation.

##### Methods:
- `write_or_resume_book(plan_name: str, plan_doc: dict, active_context_text: str, generate_text_fn: Callable, status_fn: Callable, auto_run: bool = True) -> tuple[dict, Optional[Path]]`: Main chapter writing loop. Generates incomplete chapters in sequence, applies text corrections, saves to BEJSON database, writes scratch files, and compiles to HTML upon completing all tasks.
- `_load_or_create_book_doc(plan_name: str, topic: str, title: str) -> dict`: Loads existing `books/BEJSON/<plan_name>.bejson` or initializes a new multi-entity BEJSON 104a document.
- `_save_book_doc(plan_name: str, book_doc: dict) -> None`: Executes atomic write for book document.
- `_compile_single_html(plan_name: str, book_doc: dict) -> Path`: Compiles all chapters in `book_doc` into a single static HTML document styled with modern responsive typography.
- `_markdown_to_html_fragment(markdown_text: str) -> str`: Converts Markdown chapter content to HTML tags (headings, paragraphs, code blocks, bold/italic formatting) without external dependencies.

---

### 10.8 `app/text_correction.py` (Brand Standards Sanitizer)

#### `fix_text(input_text: str) -> tuple[str, list]`
Sanitizes raw text against brand guidelines and terminology rules.

- **Parameters**: `input_text`: Raw model output string.
- **Returns**: Tuple `(corrected_text, list_of_applied_fixes)`.

---

## 11. Complete BEJSON Schema Definitions

### 11.1 Plan Document Schema (`data/plans/<plan_name>.json`)

```json
{
  "Format": "BEJSON",
  "Format_Version": "104a",
  "Format_Creator": "Elton Boehnen",
  "Writing_Title": "Title of the Book",
  "Writing_Type": "Non-Fiction Guide",
  "Writing_Category": "Technology",
  "Book_Goal": "Comprehensive introduction to the subject.",
  "Records_Type": ["PlanTask"],
  "Fields": [
    {"name": "Task_Number", "type": "integer"},
    {"name": "Task_Name", "type": "string"},
    {"name": "Task_Goal", "type": "string"}
  ],
  "Values": [
    [1, "Chapter 1: Foundations of Quantum Mechanics", "Introduce qubits, superposition, and entanglement."],
    [2, "Chapter 2: Quantum Algorithms", "Cover Shor's and Grover's algorithms."]
  ]
}
```

### 11.2 Context Tracking Schema (`data/context/context_tracking.104a.bejson`)

```json
{
  "Format": "BEJSON",
  "Format_Version": "104a",
  "Format_Creator": "Elton Boehnen",
  "Records_Type": ["ContextTracking"],
  "Fields": [
    {"name": "entry_id", "type": "string"},
    {"name": "item_type", "type": "string"},
    {"name": "path", "type": "string"},
    {"name": "bubble_path", "type": "string"},
    {"name": "active", "type": "boolean"}
  ],
  "Values": [
    ["c1a2b3c4", "file", "/storage/emulated/0/notes.md", "data/context/bubble/notes.md", true]
  ]
}
```

---

## 12. Prompt Engineering Specifications

### 12.1 Plan Generation Prompt Template

```
You are an expert outline creator and book planner.
Given the following request and reference context, create a detailed chapter plan for a book.

Topic/Goal: {user_prompt}
Requested Chapter Count: {chapter_count}

Attached Context Reference Material:
{attached_context}

Output MUST be a single valid JSON object formatted EXACTLY as follows:
{{
  "Writing_Title": "Book Title",
  "Writing_Type": "Non-Fiction / Guide",
  "Writing_Category": "Category",
  "Book_Goal": "Summary of overall goal",
  "Chapters": [
    {{
      "Task_Name": "Chapter 1: Title",
      "Task_Goal": "Goal of this chapter"
    }}
  ]
}}
```

### 12.2 Chapter Writing Prompt Template

```
You are writing a book titled "{book_title}" on the topic of "{topic}".

*** CRITICAL INSTRUCTION ***
Your CURRENT ASSIGNMENT is to ONLY write the content for the single chapter titled: "{chapter_title}".
Do NOT write the entire book. Do NOT write other chapters. Focus exclusively on delivering a complete,
high-quality draft of this one chapter, in Markdown.

--- ATTACHED CONTEXT (reference material) ---
{attached_context}

--- DOCUMENT PLAN SCOPE (for reference ONLY, so you understand the whole book's structure) ---
{plan_scope}

--- PREVIOUS CHAPTER (for continuity ONLY — do not rewrite this) ---
{previous_chapter_content}
```

---

## 13. Security, Privacy & Environment Mandates

1. **Local Data Boundaries**: All files generated by `Cli_Bookwriter` remain strictly inside `SCRIPT_PATH` unless `use_external_paths` is manually set to `True` in `config.json`.
2. **Credential Protection**: `.env` files stored in `secure/` are excluded from version control.
3. **No External Network Dependencies**: Outside of standard HTTPS REST calls to Google Gemini API endpoints, `Cli_Bookwriter` requires no remote servers or third-party web frameworks.

---

## 14. Project Metadata & Sign-off

- **Package Name**: Cli_Bookwriter
- **Project Version**: 1.2.0
- **Package Version**: 102
- **BEJSON Spec Version**: 104a
- **Format Creator & Author**: Elton Boehnen
- **Contact Email**: boehnenelton2024@gmail.com
- **Website**: https://boehnenelton2024.pages.dev
- **Repository**: https://github.com/boehnenelton
- **RELATIONAL_ID**: `2f3a4b5c-6d7e-4f8a-9b0c-1d2e3f4a5b66`

