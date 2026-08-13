# NewAgent

**v3.20.2** · Async AI agent terminal client with dual REST and Interactions engines.

Ground-up async agent framework built for Termux/Android and Linux. Dual-engine architecture switches dynamically between a REST prompter and a native Interactions (tool-calling) engine. Ships with a TUI terminal interface, a CLI batch runner, and a Flask web terminal frontend.

---

## Features

- **Dual Engine** — REST and Interactions engines; switches dynamically per turn
- **Context Bubble** — keyword-triggered knowledge injection with configurable cooldowns
- **Job System** — BEJSON 104a job schemas with `/jobstart`, `/jobstop` slash commands; auto-pruned after 7 days
- **Session Logging** — per-session BEJSON + Markdown transcripts
- **Amnesia / Rebirth** — `/amnesia` compresses + wipes history; `/rebirth` re-seeds from recap
- **Web Terminal** — Flask-based browser GUI sharing the same engine/config stack
- **CLI Runner** — `cliagent.py` for non-interactive or scripted prompts
- **Multi-Key Round-Robin** — up to 12 Gemini keys rotated per query
- **BEHTML Knowledge** — built-in `html` context bubble with full BEHTML spec on keyword match

## Structure

```
NewAgent/
├── agent.py              # Main async event loop / TUI orchestrator (v2.15.0)
├── cliagent.py           # Non-interactive CLI runner (v1.2.0)
├── webagent.py           # Flask web terminal (v0.11.0)
├── JobMaker.py           # Job schema builder utility
├── requirements.txt      # Python dependencies
├── config/               # BEJSON config, keys, models, triggers, knowledge pool
├── Context/              # Amnesia recap, persistent context files
├── jobs/                 # Active and completed job schemas
├── lib/                  # lib_bejson_newagent_* and lib_bejson_Core_* libraries
└── tools/                # Tool plugins loaded by the Interactions engine
```

## Quick Start

```bash
# Terminal TUI
python3 agent.py

# CLI batch
python3 cliagent.py --prompt "Hello" --engine rest

# Web terminal (opens http://localhost:5000)
python3 webagent.py
```

## Requirements

```bash
pip install -r requirements.txt
```

Key deps: `google-genai`, `flask`, `rich`, `prompt_toolkit`

## Configuration

Config lives in `config/`. On first run, `config.json` is generated with defaults. Load API keys via the Keys tab (web) or `/keys` command (TUI). Supports up to 12 Gemini key slots with round-robin rotation.

## Engines

| Engine | Mode | Use Case |
|---|---|---|
| REST | `--engine rest` | Fast single-turn completions |
| Interactions | `--engine interactions` | Tool-calling, multi-step agentic runs |

Engine switches automatically mid-session based on task type.

## Author

**Elton Boehnen**
- Email: boehnenelton2024@gmail.com
- Web: [boehnenelton.pages.dev](https://boehnenelton2024.pages.dev)
- GitHub: [github.com/boehnenelton](https://github.com/boehnenelton)

---

*NewAgent v3.20.2 · pkg073 · 2026-08-13*
