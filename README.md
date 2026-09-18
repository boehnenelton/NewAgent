# NewAgent

[![Release Version](https://img.shields.io/badge/version-3.33.0-red.svg)](https://github.com/boehnenelton/NewAgent)
[![Package Version](https://img.shields.io/badge/package-114-black.svg)](https://github.com/boehnenelton/NewAgent)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/License-PolyForm%20Noncommercial%201.0.0-red.svg)](LICENSE)
[![Python Version](https://img.shields.io/badge/python-3.10%2B-black.svg)](https://www.python.org/)
[![BEJSON Standard](https://img.shields.io/badge/BEJSON-104a%20%7C%20104db%20%7C%20105-DE2626.svg)](file:///storage/emulated/0/Admin/repos/New/NewAgent/config/constant_config.bejson)

> **Ground-up, high-performance asynchronous agent terminal client and multi-agent coordination system featuring dual REST and Gemini Interactions engines, BEJSON positional integrity, and sub-agent orchestration.**

---

## 📋 Table of Contents
- [Overview](#-overview)
- [Key Features](#-key-features)
- [System Architecture & Visual Visualizations](#-system-architecture--visual-visualizations)
  - [High-Level Architectural Overview](#high-level-architectural-overview)
  - [Visual Architecture Slide Gallery](#visual-architecture-slide-gallery)
  - [Directory Layout Architecture](#directory-layout-architecture)
- [Persistence Engine & Data Schemas](#-persistence-engine--data-schemas)
  - [BEJSON 104a / 104db Positional Integrity Standard](#bejson-104a--104db-positional-integrity-standard)
  - [MFDB Relational Database Schema](#mfdb-relational-database-schema)
- [Sub-Agent Orchestration Framework](#-sub-agent-orchestration-framework)
  - [Sub-Agent Profiles & Mailbox Signaling](#sub-agent-profiles--mailbox-signaling)
  - [Sub-Agent CLI Management (`subagent_admin.py`)](#sub-agent-cli-management-subagent_adminpy)
- [Installation & Setup](#-installation--setup)
  - [Prerequisites](#prerequisites)
  - [Quick Start](#quick-start)
  - [Environment Sourcing Setup](#environment-sourcing-setup)
- [Usage & Execution Interfaces](#-usage--execution-interfaces)
  - [Interactive CLI Agent (`agent.py`)](#interactive-cli-agent-agentpy)
  - [Web Terminal UI (`webagent.py`)](#web-terminal-ui-webagentpy)
  - [Headless Scripting Client (`cliagent.py`)](#headless-scripting-client-cliagentpy)
- [Security & System Hardening](#-security--system-hardening)
  - [Authentication & Access Control](#authentication--access-control)
  - [Path Traversal & Execution Safeguards](#path-traversal--execution-safeguards)
  - [Environment Credential Isolation](#environment-credential-isolation)
- [Included Tool Suites](#-included-tool-suites)
  - [NA-CMS (Content Management System)](#na-cms-content-management-system)
  - [NA-WebToolkit & NA-Chunker](#na-webtoolkit--na-chunker)
- [Known Issues & Audit Roadmap](#-known-issues--audit-roadmap)
- [Contributing](#-contributing)
- [License & Author Credits](#-license--author-credits)

---

## 🔍 Overview

**NewAgent** is an enterprise-grade, asynchronous AI agent terminal client and multi-agent execution framework engineered specifically for Termux, Android, Linux, and macOS environments. Built from the ground up to replace legacy sync-polling agent loops, NewAgent couples a fast, decoupled execution core with dual AI provider engines: a raw REST engine supporting multi-key rotation and a native Gemini Interactions engine for high-speed streaming and function calling.

The system is designed adhering to a brutalist, high-contrast administrative design language (**#FFFFFF** background, **#000000** foreground, **#DE2626** accent) and strict **BEJSON 104a/104db/105** data schemas. Every data structure within NewAgent guarantees field map cache resolution ($O(1)$ property mapping), complete positional integrity, and zero hardcoded index assumptions.

With built-in dynamic keyword-triggered context dripping, nearest-wins hierarchical context inheritance (`context.bejson`), lock-protected token generation, background task execution, and a multi-role sub-agent coordination pipeline, NewAgent delivers an autonomous, auditable, and extensible workspace for software engineering and data pipeline tasks.

---

## ✨ Key Features

- ⚡ **Dual AI Engines**: Toggle seamlessly between raw REST multi-key failover (`RestPrompter`) and Google Gemini Interactions native API streaming (`engine_interactions.py`).
- 🔐 **Multi-Key Failover & Circuit Breakers**: Automatic credential rotation across up to 25 Gemini API keys with 3-consecutive-failure circuit breakers and key cooldown tracking (`key_state.bejson`).
- 🧠 **Dynamic Keyword Context Dripper**: Scans incoming prompt turns against a weighted knowledge base (`knowledge_pool.bejson`) to inject precise technical documentation and worked schema examples into the turn context window.
- 🌳 **Hierarchical Context Inheritance (`INIT`)**: Recursively resolves ancestor `context.bejson` files from root to leaf, allowing child subdirectories to override or inherit project ground rules cleanly.
- 🤖 **Sub-Agent Orchestration Engine**: Built-in profile-gated sub-agent launcher (`lib_bejson_newagent_subagent_*.py`) supporting inter-agent mailbox signaling, custom action allowlists, and unattended task delegation.
- 🌐 **Web & CLI Access Interfaces**: Run via an interactive terminal (`agent.py`), a headless automation runner (`cliagent.py`), or a responsive web terminal (`webagent.py`) featuring `X-Auth-Token` authentication and live execution logging.
- 📊 **Strict BEJSON 104a/104db Data Standards**: Integrated schema validation enforcing 6-value type vocabularies (`string`, `integer`, `number`, `boolean`, `array`, `object`), atomic file writes, and field-map caching.
- 🛠️ **Embedded Production Toolkits**: Bundles specialized sub-tools including `NA-CMS` (BEJSON-backed static site engine and admin panel), `NA-WebToolkit` (headless scraping engine), and `NA-Chunker`.

---

## 🛠️ System Architecture & Visual Visualizations

### High-Level Architectural Overview

```
+-----------------------------------------------------------------------------------+
|                            User Access & Execution Layer                          |
|   +-----------------------+   +-----------------------+   +-------------------+   |
|   |   agent.py (CLI UI)   |   |  webagent.py (Web UI) |   | cliagent.py (Head)|   |
|   +-----------------------+   +-----------------------+   +-------------------+   |
+-----------------------------------------------------------------------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
|                         Core Orchestration & Context Engine                       |
|   +---------------------------------------------------------------------------+   |
|   | Context Bubble Assembler (knowledge_pool, triggers.bejson, context.bejson)|   |
|   +---------------------------------------------------------------------------+   |
|   | Action Parser & Tag Dispatcher (<exec>, <write_file>, <bejson_create>, etc)|   |
|   +---------------------------------------------------------------------------+   |
|   | Sub-Agent Coordinator & Signal Mailbox (subagent_admin.py / profiles)     |   |
|   +---------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------+
                                        |
                    +-------------------+-------------------+
                    |                                       |
                    v                                       v
+---------------------------------------+   +---------------------------------------+
|        Engine REST / Multi-Key        |   |       Engine Interactions Native      |
|  (RestPrompter + key_state.bejson)    |   |  (Gemini Interactions + Native Tools) |
+---------------------------------------+   +---------------------------------------+
                    |                                       |
                    +-------------------+-------------------+
                                        |
                                        v
+-----------------------------------------------------------------------------------+
|                          Persistence & Schema Engine                              |
|   +---------------------------------------------------------------------------+   |
|   | BEJSON 104a Single-Entity Stores  | BEJSON 104db Multi-Entity Tables           |
|   | MFDB Relational Multi-File DB     | Field Map Cache Resolution Engine         |
|   +---------------------------------------------------------------------------+   |
+-----------------------------------------------------------------------------------+
```

### Visual Architecture Slide Gallery

Below is the complete architectural visualization breakdown of NewAgent, illustrating its core subsystems, execution pipelines, data boundaries, and multi-agent coordination flows:

````carousel
![Slide 1: System Overview](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_1.png)
<!-- slide -->
![Slide 2: Dual Model Engine Architecture](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_2.png)
<!-- slide -->
![Slide 3: Context Assembly & Keyword Dripper](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_3.png)
<!-- slide -->
![Slide 4: Action Dispatcher & Execution Flow](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_4.png)
<!-- slide -->
![Slide 5: BEJSON 104a vs 104db Storage Rules](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_5.png)
<!-- slide -->
![Slide 6: Sub-Agent Lifecycle & Mailbox Signaling](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_6.png)
<!-- slide -->
![Slide 7: Security Boundaries & Hardening Layers](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_7.png)
<!-- slide -->
![Slide 8: Key Failover & Cooldown Pipeline](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_8.png)
<!-- slide -->
![Slide 9: Hierarchical Context Inheritance](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_9.png)
<!-- slide -->
![Slide 10: Environment Sourcing Hierarchy](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_10.png)
<!-- slide -->
![Slide 11: Web Terminal & Token Authentication](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_11.png)
<!-- slide -->
![Slide 12: NA-CMS Integrated Architecture](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_12.png)
<!-- slide -->
![Slide 13: NA-WebToolkit Execution Flow](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_13.png)
<!-- slide -->
![Slide 14: Session Archival & Logging Pipeline](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_14.png)
<!-- slide -->
![Slide 15: Sub-Agent Profile Security Matrix](file:///storage/emulated/0/Admin/repos/New/NewAgent/images/NewAgent_System_Architecture_-_Slide_15.png)
````

### Directory Layout Architecture

```
NewAgent/
├── agent.py                        # Primary interactive terminal client
├── webagent.py                     # Flask-based web terminal interface
├── cliagent.py                     # Headless single-turn / scripting CLI runner
├── subagent_admin.py               # Sub-agent administration & session management CLI
├── JobMaker.py                     # Async task & batch job deployment runner
├── .bejson_project.json            # Canonical single-source-of-truth project manifest
├── requirements.txt                # Dependency specifications
├── AUDIT.md                        # Master codebase audit and remediation tracker
│
├── config/                         # Configuration & BEJSON knowledge registries
│   ├── config.json                 # Primary system settings & active provider paths
│   ├── constant_config.bejson      # Token budget & context assembly constants
│   ├── gemini_catalog.bejson       # Registered Gemini model tiers & pricing specs
│   ├── knowledge_pool.bejson       # Technical knowledge facts & worked schemas
│   ├── triggers.bejson             # Keyword-to-fact triggering rules
│   ├── keys.bejson                 # Redacted API key registry
│   └── key_state.bejson            # Key cooldown & error count tracker
│
├── lib/                            # Core NewAgent runtime libraries
│   ├── lib_bejson_Core_bejson_core.py          # Core BEJSON I/O & schema engine
│   ├── lib_bejson_Core_bejson_validator.py     # BEJSON structural validator
│   ├── lib_bejson_newagent_actions.py          # Action tag parser & tag execution engine
│   ├── lib_bejson_newagent_config.py           # Configuration manager & lock helper
│   ├── lib_bejson_newagent_context_bubble.py   # Dynamic context assembly engine
│   ├── lib_bejson_newagent_engine_rest.py       # REST API prompter & key rotator
│   ├── lib_bejson_newagent_engine_interactions.py # Gemini Interactions API engine
│   ├── lib_bejson_newagent_env.py              # Secure environment resolver
│   ├── lib_bejson_newagent_session.py          # Session logger & transcript archiver
│   ├── lib_bejson_newagent_subagent_common.py  # Shared sub-agent lock & path helpers
│   ├── lib_bejson_newagent_subagent_profiles.py# Sub-agent profile definitions (BEJSON 104)
│   ├── lib_bejson_newagent_subagent_sessions.py# Sub-agent active session tables
│   ├── lib_bejson_newagent_subagent_signals.py # Inter-agent mailbox signaling system
│   └── lib_bejson_newagent_subagent_runtime.py # Sub-agent execution orchestrator
│
├── env_templates/                  # Environment bootstrap schemas
│   ├── secureenv_file.template.json# Secret credentials schema template
│   ├── paths.template.json         # Non-sensitive paths schema template
│   └── README.md                   # Environment setup guide
│
├── tools/                          # Production tool suites
│   ├── NA-CMS/                     # Static Site Generator & CMS Admin Application
│   ├── NA-WebToolkit/              # Headless web scraping & content extraction tool
│   ├── NA-Chunker/                 # Text & code chunking utility
│   ├── NA-Init/                    # Standalone INIT context initializer
│   └── NA-MD2HTML/                 # Markdown-to-HTML compilation engine
│
├── dev/                            # Active development tracking
│   ├── change-log.md               # Maintained technical version history
│   ├── dead_code.md                # Deprecated symbol registry
│   ├── variable_naming_issues.md   # Structural tracking notes
│   └── security-notes.md           # Security audit findings & remediation log
│
├── docs/                           # Technical documentation
│   ├── technical_overview.md       # Function signatures & module specs
│   └── Reports/                    # Architectural audits & deep-dive reports
│
├── images/                         # Architectural diagrams & slide graphics
├── jobs/                           # Active & completed batch job definitions
└── logs/                           # Runtime transcripts & session archives
```

---

## 💾 Persistence Engine & Data Schemas

### BEJSON 104a / 104db Positional Integrity Standard

All internal storage across NewAgent strictly adheres to the **BEJSON 104a** (single-entity document) and **BEJSON 104db** (multi-entity relational table) specifications. 

Key constraints enforced across the persistence layer:
1. **Positional Integrity**: The order of attributes listed in the `Fields` header array must match the column order in every row within the `Values` array.
2. **Field Map Cache Mandate**: Direct index lookups (e.g., `row[2]`) are strictly forbidden in application code. All operations resolve indices dynamically via `bejson_core_get_field_map()` or `bejson_core_get_field_index()`.
3. **6-Value Type Vocabulary**: Fields must declare explicit lowercase types (`string`, `integer`, `number`, `boolean`, `array`, `object`). Untyped or generic designations (such as `any`) are rejected by `lib_bejson_Core_bejson_validator.py`.

#### Canonical BEJSON 104a Schema Example (`constant_config.bejson`):

```json
{
  "Format": "BEJSON",
  "Format_Version": "104a",
  "Format_Creator": "Elton Boehnen",
  "Records_Type": ["SystemConstants"],
  "Fields": [
    {"name": "constant_name", "type": "string"},
    {"name": "defined_value", "type": "string"},
    {"name": "default_value", "type": "string"},
    {"name": "description", "type": "string"}
  ],
  "Values": [
    ["max_context_tokens", "8000", "8000", "Total token budget for context assembly"],
    ["pct_keyword_triggers", "0.2", "0.2", "Budget share allocated to keyword facts"],
    ["chars_per_token", "4.0", "4.0", "Estimated character count per token"]
  ]
}
```

### MFDB Relational Database Schema

For multi-entity workloads (e.g., in `NA-CMS`), NewAgent utilizes **MFDB (Multi-File Database)** structures. An MFDB database consists of a master manifest (`manifest.104a.bejson`) describing system entities, primary keys, and relative entity storage paths:

```
+-------------------------------------------------------+
|            manifest.104a.bejson (MFDB Root)          |
+-------------------------------------------------------+
                           |
            +--------------+--------------+
            |                             |
            v                             v
+-----------------------+     +-----------------------+
|  entities/posts.bejson|     |entities/authors.bejson|
|  (Primary Key: id)    |     | (Primary Key: id)     |
+-----------------------+     +-----------------------+
```

---

## 🤖 Sub-Agent Orchestration Framework

### Sub-Agent Profiles & Mailbox Signaling

NewAgent includes an autonomous multi-agent orchestration framework (`lib_bejson_newagent_subagent_*.py`). Sub-agents operate with isolated system prompts, custom action tag allowlists, and dedicated session tables (`.subagent_sessions.104.bejson`).

Communication between the main agent and sub-agents occurs via a lock-protected mailbox signaling engine (`.subagent_signals.104.bejson`):
- **Signals**: `TASK_ASSIGN`, `TASK_COMPLETE`, `TASK_FAILED`, `PAUSE`, `RESUME`.
- **Mailbox Protocol**: Sub-agents can pause turn loops using `<await_signal type="TASK_COMPLETE"/>` and automatically resume execution once the target signal is posted.

```
+------------------+       send_signal()        +----------------------+
| Main Agent Core  | -------------------------> |  Sub-Agent Mailbox   |
+------------------+                            +----------------------+
         ^                                                 |
         |              poll_signals()                     v
         +-------------------------------------- +----------------------+
                                                 | Sub-Agent Worker     |
                                                 +----------------------+
```

### Sub-Agent CLI Management (`subagent_admin.py`)

The `subagent_admin.py` utility allows system operators to inspect, create, and dispatch sub-agents directly from the command line:

```bash
# List all registered sub-agent profiles
python3 subagent_admin.py profiles list

# Create a new specialized researcher sub-agent profile
python3 subagent_admin.py profiles create researcher \
  --description "Codebase & Web Researcher" \
  --actions "read_file,list_dir,search_web,run_command" \
  --system-prompt "You are a read-only research assistant."

# Dispatch a sub-agent task session
python3 subagent_admin.py dispatch researcher "Analyze lib/ directory for memory leaks"

# Inspect active sub-agent sessions and mailbox signals
python3 subagent_admin.py sessions list
python3 subagent_admin.py signals list
```

---

## ⚙️ Installation & Setup

### Prerequisites
- **Python**: Version **3.10** or higher.
- **Operating System**: Linux, Termux (Android), macOS, or Windows (WSL recommended).
- **Core Dependencies**: Installed via `requirements.txt`.

### Quick Start

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/boehnenelton/NewAgent.git
   cd NewAgent
   ```

2. **Install Required Packages**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Initialize Configuration**:
   Verify configuration templates and populate local environment credentials:
   ```bash
   python3 cliagent.py --version
   ```

### Environment Sourcing Setup

NewAgent sources API credentials and system paths dynamically using a two-tier configuration model:
1. **Secure Credentials**: `/storage/emulated/0/.env/secure/secureenv_file.json` (Contains `GEMINI_KEY_1..25`, `GROQ_KEY_*`, `OPENROUTER_KEY_*`).
2. **User Non-Sensitive Paths**: `/storage/emulated/0/.env/user/paths.json` (Contains `INTERNAL_STORAGE`, `SD_CARD`, `PROJECT_ROOT`, `ADMIN`).

> [!NOTE]
> If the new split environment paths are absent, NewAgent safely falls back to legacy `env_file.json` sourcing without interrupting startup. Blank schema templates are provided in `env_templates/`.

---

## 🚀 Usage & Execution Interfaces

### Interactive CLI Agent (`agent.py`)

Launch the primary interactive CLI agent featuring real-time colored logging, turn history, and action tag execution:

```bash
python3 agent.py
```

- **Interactive Slash Commands**:
  - `/help`: Display operational command menu.
  - `/clear`: Reset current turn history buffer.
  - `/logs2md`: Export active session transcript to timestamped Markdown and ZIP archive.
  - `/model`: View and switch active Gemini catalog tiers.
  - `/budget`: Inspect token consumption and context bubble allocation.

### Web Terminal UI (`webagent.py`)

Launch the responsive web terminal server:

```bash
python3 webagent.py --port 5000
```

- Access the web interface at `http://127.0.0.1:5000`.
- **Authentication**: On first run, `webagent.py` generates a secure access token saved to `config/config.json` (`web_auth_token`). Pass this token via the `X-Auth-Token` header or `?token=` query parameter.

### Headless Scripting Client (`cliagent.py`)

Run single-turn prompt tasks or automated pipeline scripts non-interactively:

```bash
# Execute a single prompt and print output
python3 cliagent.py "Audit lib/lib_bejson_newagent_actions.py for path safety"

# Execute prompt with JSON output formatting
python3 cliagent.py --execute "list_dir Cwd" --json
```

---

## 🛡️ Security & System Hardening

NewAgent incorporates comprehensive security guardrails designed to prevent unauthorized code execution, key leakage, and path traversal vulnerabilities:

### Authentication & Access Control
- **Web Terminal Guard**: `webagent.py` and `JobMaker.py` enforce `X-Auth-Token` authentication with constant-time string comparisons (`hmac.compare_digest`) on all HTTP endpoints.
- **Loopback Binding Default**: Web servers bind to `127.0.0.1` by default to prevent unintended LAN exposure.

### Path Traversal & Execution Safeguards
- **Sub-String Execution Denylist**: Command execution (`do_exec`) checks shell input against an explicit denylist (`rm -rf /`, `mkfs`, `dd`, `chmod 777`) using substring-anywhere matching rather than bypassable prefix checks.
- **Path Containment (`bejson_safe_join`)**: File I/O operations enforce directory boundary checks to prevent `../` directory breakout attacks.

### Environment Credential Isolation
- **API Key Masking**: Raw API key values (`GEMINI_KEY_*`) are loaded exclusively into memory and masked in terminal output and transcript logs (`REDACTED_KEY_PLACEHOLDER`).

---

## 🧰 Included Tool Suites

### NA-CMS (Content Management System)
Located in `tools/NA-CMS/`, **NA-CMS** is a standalone, BEJSON-backed static site generator and management application.
- **Features**: Dynamic theme engine, asset optimization pipeline, automated breadcrumb generation, and HTML sanitization.
- **Execution**: Run via `python3 tools/NA-CMS/Admin.py`.

### NA-WebToolkit & NA-Chunker
- **NA-WebToolkit** (`tools/NA-WebToolkit/`): High-speed, headless scraping engine supporting HTML extraction, markdown conversion, and media downloading using list-form subprocess calls.
- **NA-Chunker** (`tools/NA-Chunker/`): Codebase parsing tool that breaks large Python and JavaScript codebases into token-bounded chunks for LLM consumption.

---

## 🐛 Known Issues & Audit Roadmap

Per the latest security and architecture audit (`AUDIT.md` & `dev/security-notes.md`), the following items are tracked for future iterations:

- [x] **Remediated**: Lock-protected `web_auth_token` generation preventing race conditions during concurrent server boot (PKG110).
- [x] **Remediated**: Strict BEJSON field type validation rejecting non-standard types like `any` (PKG104).
- [x] **Remediated**: Sub-agent signal mailbox implementation and action tag filtering (PKG112).
- [ ] **Roadmap Item 1**: Implement automatic mtime-based caching for context bubble policy reads (`context_bubble.assemble_bubble`).
- [ ] **Roadmap Item 2**: Replace fixed-delay network retries in `engine_rest.py` with exponential backoff and randomized jitter.
- [ ] **Roadmap Item 3**: Standardize all sub-agent file lock routines to use `ResilientPIDLock`.

---

## 🤝 Contributing

Contributions must adhere to the core project policy rules:
1. **Positional Integrity**: Maintain strict alignment between `Fields` and `Values` across all BEJSON operations. Always use field map caching (`bejson_core_get_field_map`).
2. **Header Annotations**: All modified files must maintain single-source `VERSION` variables and updated header annotations (`RELATIONAL_ID`, `Release_Version = 300`).
3. **No Unversioned Deliverables**: Every project update must increment `Project_Version` and `Package_Version` in `.bejson_project.json`.

---

## 📄 License & Author Credits

**NewAgent** is authored and maintained by **Elton Boehnen**. Licensed under the **PolyForm Noncommercial License 1.0.0**.

- **Author**: Elton Boehnen
- **Email**: [boehnenelton2024@gmail.com](mailto:boehnenelton2024@gmail.com)
- **Website**: [boehnenelton2024.pages.dev](https://boehnenelton2024.pages.dev)
- **GitHub**: [github.com/boehnenelton](https://github.com/boehnenelton)

---
*Copyright © 2026 Elton Boehnen. All rights reserved.*
