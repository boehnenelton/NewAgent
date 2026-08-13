# Cli_Bookwriter (v1.2.0 PKG 102)

[![BEJSON Core Compatible](https://img.shields.io/badge/BEJSON-104a-blue.svg)](https://boehnenelton2024.pages.dev)
[![Format Creator](https://img.shields.io/badge/Creator-Elton_Boehnen-red.svg)](https://github.com/boehnenelton)

**Cli_Bookwriter** is a command-line chapter-by-chapter book writing and compilation engine built on top of the **BEJSON 104a** ecosystem. Derived from the proven architecture of `AuthorCMS`, `Cli_Bookwriter` generates structured non-fiction and fiction books using Gemini AI model integration, chained contextual awareness (attached research bubble + full outline scope + previous chapter continuity), robust crash recovery/resumability, and single-file static HTML book compilation.

---

## Table of Contents
1. [Overview & Core Architecture](#overview--core-architecture)
2. [Key Features](#key-features)
3. [Installation & Requirements](#installation--requirements)
4. [Environment & Configuration Setup](#environment--configuration-setup)
5. [Complete Workflow Guide](#complete-workflow-guide)
6. [Command Reference](#command-reference)
7. [Persistent Context System](#persistent-context-system)
8. [Auto-Run vs Single-Step Execution](#auto-run-vs-single-step-execution)
9. [BEJSON Data & Folder Structure](#bejson-data--folder-structure)
10. [Error Handling & Task Resumability](#error-handling--task-resumability)
11. [Author Credits & Specification](#author-credits--specification)

---

## Overview & Core Architecture

`Cli_Bookwriter` addresses the main challenge of LLM-based long-form writing: **context degradation and topic drift**. Rather than attempting to generate an entire book in a single prompt (which leads to hallucination and brevity), `Cli_Bookwriter` executes an automated pipeline:

```
┌─────────────────────────┐     ┌─────────────────────────┐     ┌─────────────────────────┐
│  1. Attached Context    │ ──> │  2. Plan Generation     │ ──> │ 3. Sequential Chapter   │
│  (Research Files/Dirs)  │     │  (BEJSON 104a Outline)  │     │    Chained Writing      │
└─────────────────────────┘     └─────────────────────────┘     └─────────────────────────┘
                                                                             │
                                                                             ▼
┌─────────────────────────┐     ┌─────────────────────────┐     ┌─────────────────────────┐
│ 6. Single HTML File     │ <── │ 5. Brand Text Fixer     │ <── │ 4. BEJSON 104a Working  │
│    Compilation          │     │    (Boehnen Elton JSON) │     │    Book Database        │
└─────────────────────────┘     └─────────────────────────┘     └─────────────────────────┘
```

1. **Context Ingestion**: Source reference materials, notes, or structured files into a local context bubble without modifying original files.
2. **BEJSON 104a Outline Planning**: Generates a multi-chapter outline containing title, topic, targets, and chapter tasks.
3. **Chained Sequential Generation**: Writes each chapter individually. The AI prompt receives:
   - Attached reference context.
   - Entire book plan scope (giving full situational awareness of where the chapter fits).
   - Exact text of the preceding chapter (enforcing narrative and stylistic continuity).
4. **Resumable Database Persistence**: Writes chapter outputs into a atomic BEJSON 104a database (`books/BEJSON/<name>.bejson`) on a per-chapter basis.
5. **Brand & Text Remediation**: Filters text through `text_correction` to fix AI formatting artifacts and maintain terminology standards.
6. **Static Web Compilation**: Merges all completed chapters into a single, self-contained HTML book file.

---

## Key Features

- **Persistent Selection State**: Selection state (`data/persist/selection_state.104a.bejson`) tracks the active plan name and settings across CLI invocations without requiring a background server.
- **Persistent Auto-Run Toggle (`--auto-run`)**: Toggle between full automated end-to-end chapter generation or controlled step-by-step single chapter generation.
- **Fail-Safe Resume**: If an API quota error or network drop occurs during chapter 5 of a 10-chapter book, running `--resume-plan` automatically resumes from chapter 5 without duplicating or losing chapters 1–4.
- **BEJSON 104a Configuration Integration**: Configured via `config.json`, supporting customized `.env` paths (`dotenv_path`) and external path toggles (`use_external_paths`).
- **Template Export & Auto-Fallback**: Generate clean `.env` template files via `--export-env-template` and automatically pull/append system environment API keys from device storage if local configuration is missing.

---

## Installation & Requirements

### System Requirements
- Operating System: Linux / Android Termux / macOS / Windows WSL
- Python: Version 3.10 or higher
- External Dependencies: `requests` library (for Gemini API REST calls)

### Quick Setup

```bash
# Clone or navigate to the repository
cd /storage/emulated/0/Admin/tools/Cli_Bookwriter

# Install Python requirements
pip install requests --break-system-packages

# Verify installation & check system status
python3 Cli_Bookwriter.py --status
```

---

## Environment & Configuration Setup

`Cli_Bookwriter` checks for Gemini API keys using the standard multi-tier fallback hierarchy:

1. **Configured `.env` File**: Reads key from `secure/.env` (or custom path defined in `config.json`).
2. **OS Environment Variables**: Checks `GEMINI_KEY_1` through `GEMINI_KEY_21`, `GEMINI_API_KEY`, or `GOOGLE_API_KEY`.
3. **Device BEJSON Environment Files**: Reads `/storage/emulated/0/env_file.json` or `/storage/emulated/0/env_file_2.json`.

### Exporting an Environment Template

To export a fresh `.env` template file:

```bash
python3 Cli_Bookwriter.py --export-env-template secure/.env.template
```

### Configuring `config.json`

On first launch, `Cli_Bookwriter` generates a standard BEJSON 104a `config.json`:

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

---

## Complete Workflow Guide

Here is the step-by-step workflow to produce a published HTML book:

### Step 1: Add Reference Material (Optional)
Attach notes, documentation, or background files to inform the book generation.

```bash
# Attach a single research markdown file
python3 Cli_Bookwriter.py --add-context-file /path/to/research_notes.md

# Attach an entire directory of reference material
python3 Cli_Bookwriter.py --add-context-folder /path/to/reference_docs/

# List all attached context items (* = active)
python3 Cli_Bookwriter.py --list-context
```

### Step 2: Create & Generate a Book Plan
Name your book project and instruct Gemini to outline the chapter tasks.

```bash
# Set active plan slot
python3 Cli_Bookwriter.py --new-plan quantum-computing

# Generate outline (6 chapters) based on a topic prompt
python3 Cli_Bookwriter.py --generate-plan "A comprehensive beginner's guide to Quantum Computing and Qubits" --chapters 6

# Inspect the generated chapter structure
python3 Cli_Bookwriter.py --view-plan
```

### Step 3: Configure Auto-Run Mode
Choose whether you want the tool to write all chapters in sequence automatically or pause after each chapter.

```bash
# Enable automated multi-chapter writing (Default)
python3 Cli_Bookwriter.py --auto-run on

# Or set single-step execution mode
python3 Cli_Bookwriter.py --auto-run off
```

### Step 4: Write & Compile the Book
Execute the writing process.

```bash
python3 Cli_Bookwriter.py --write-book
```

- If **auto-run is ON**: `Cli_Bookwriter` generates Chapter 1 through Chapter 6 consecutively, saves each chapter to `books/BEJSON/quantum-computing.bejson`, and automatically compiles the final book into `books/HTML/quantum-computing.html`.
- If **auto-run is OFF**: It completes Chapter 1, saves progress, and pauses. Run `python3 Cli_Bookwriter.py --resume-plan` to write Chapter 2, and so on.

---

## Command Reference

| Flag / Option | Short Aliases | Description |
| :--- | :--- | :--- |
| `--new-plan NAME` | | Set and select a new plan slot name |
| `--select-plan NAME` | | Switch active selection to an existing plan |
| `--generate-plan PROMPT` | | Generate chapter outline for active plan via AI |
| `--chapters N` | | Set chapter count for `--generate-plan` (Default: `8`) |
| `--view-plan` | | Display outline structure of the active plan |
| `--list-plans` | | List all saved plan files |
| `--write-book` | `--resume-plan` | Write or resume chapter writing for active plan |
| `--auto-run [on\|off]` | | Toggle persistent automated chapter loop |
| `--add-context-file PATH` | `--acf`, `--Add-Context-File` | Track and copy a file into context bubble |
| `--add-context-folder PATH` | `--acd`, `--Add-Context-Folder` | Track and copy a folder into context bubble |
| `--select-context-file ID` | `--scf` | Mark a tracked context file active |
| `--select-context-folder ID`| `--scd` | Mark a tracked context folder active |
| `--deselect-context-file` | `--dcf` | Mark a context file inactive without removing |
| `--deselect-context-folder` | `--dcd` | Mark a context folder inactive without removing |
| `--remove-context-file ID` | `--rcf` | Untrack and remove context file copy |
| `--remove-context-folder ID`| `--rcd` | Untrack and remove context folder copy |
| `--list-context` | | List all tracked context files and folders |
| `--export-env-template` | | Export clean `.env` template file |
| `--model MODEL_ID` | | Specify Gemini model ID (Default: `gemini-2.5-flash`) |
| `--status` | | Display current selection, context, and key status |

---

## Persistent Context System

Context attached to `Cli_Bookwriter` persists across commands under `data/context/`. When context items are added:
1. File and folder contents are copied into `data/context/bubble/`.
2. A manifest tracking document `data/context/context_tracking.104a.bejson` registers the item paths and `active` status.
3. Active items are concatenated into an attached context block provided to Gemini during plan generation and chapter writing.

Unlike transient session bubbles, context items remain attached until explicitly deactivated with `--deselect-context-*` or deleted with `--remove-context-*`.

---

## Auto-Run vs Single-Step Execution

`Cli_Bookwriter` supports two operational modes controlled by the persistent `--auto-run` flag stored in `data/persist/selection_state.104a.bejson`:

- **Auto-Run Enabled (`--auto-run on`)**:
  Ideal for headless generation. Once started, `Cli_Bookwriter` loops sequentially through all unwritten tasks in the plan, updates the BEJSON record, clears scratch markdown files, and outputs the compiled HTML book in one run.

- **Single-Step Mode (`--auto-run off`)**:
  Ideal for interactive writing. `Cli_Bookwriter` writes exactly one chapter per command execution, allowing you to review scratch markdown files in `data/temp/<plan_name>/` or tweak context before continuing with `--resume-plan`.

---

## BEJSON Data & Folder Structure

All data managed by `Cli_Bookwriter` resides in deterministic, relative paths from `SCRIPT_PATH`:

```
Cli_Bookwriter/
├── Cli_Bookwriter.py             # Main CLI entrypoint launcher
├── bejson_project.json           # BEJSON 104a project tracking manifest
├── config.json                   # BEJSON 104a runtime configuration
├── README.md                     # Quickstart overview guide
├── DOCUMENTATION.md              # In-depth architectural & API specification
├── app/                          # Core python application modules
│   ├── book_writer.py            # Chained chapter generation & HTML compiler
│   ├── config.py                 # Self-locating path bootstrap & config loader
│   ├── context_manager.py        # Context bubble & manifest tracking
│   ├── gemini_client.py         # REST API wrapper for Gemini models
│   ├── key_loader.py            # Multilevel environment key resolver
│   ├── plan_manager.py           # BEJSON plan generator & parser
│   ├── state.py                  # SelectionState persistent manager
│   └── text_correction.py       # Brand standards & markdown sanitizer
├── books/
│   ├── BEJSON/                   # Resumable BEJSON 104a book records
│   └── HTML/                     # Single-file compiled HTML output books
├── data/
│   ├── context/                  # Tracked context manifest & bubble copies
│   ├── persist/                  # Persistent selection state (active plan/auto-run)
│   ├── plans/                    # Generated BEJSON 104a plan files
│   └── temp/                     # Per-chapter scratch markdown files
├── lib/
│   └── Core/                     # Immutable BEJSON Core library dependencies
└── secure/
    └── .env                      # Local environment API keys
```

---

## Error Handling & Task Resumability

`Cli_Bookwriter` guarantees atomic state persistence:
- **Atomic File Writes**: All database modifications use `bejson_core_atomic_write` to avoid corruption.
- **Interruption Recovery**: If execution halts due to network failure, API rate limits, or terminal termination, previously written chapters remain safely committed to `books/BEJSON/<plan_name>.bejson`. Re-executing `--write-book` automatically resumes writing from the next incomplete chapter.
- **Scratch Files**: Markdown drafts are written to `data/temp/<plan_name>/` per chapter for manual inspection and are cleaned up only when the complete book compiles to HTML.

---

## Author Credits & Specification

**Cli_Bookwriter** is designed and maintained under the BEJSON core standards by:

**Elton Boehnen**  
Email: [boehnenelton2024@gmail.com](mailto:boehnenelton2024@gmail.com)  
Website: [boehnenelton2024.pages.dev](https://boehnenelton2024.pages.dev)  
GitHub: [github.com/boehnenelton](https://github.com/boehnenelton)  
Relational ID: `2f3a4b5c-6d7e-4f8a-9b0c-1d2e3f4a5b66`
