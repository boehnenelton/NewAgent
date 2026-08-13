"""
Name:         webagent.py
Family:       NewAgent
Description:  Flask-based web terminal wrapper for NewAgent. Serves the
              browser terminal GUI (converted from webagent_Terminal.html
              into this class) and executes commands through the SAME
              do_exec() subprocess engine agent.py's <exec> action tag
              already uses -- no duplicate shell logic. Groundwork only,
              per Elton's instruction: the chat/LLM engine (RestPrompter/
              KeyRegistry/ModelRegistry) is imported and constructed here
              so it is ready, but /api/chat is an intentional stub, not
              wired to a working loop yet. Sits in the same directory as
              agent.py and shares its config/keys/models files -- not a
              separate project.
Version:      0.11.0
Date:         2026-08-09
Author:       Elton Boehnen -- boehnenelton2024@gmail.com
RELATIONAL_ID: 8b0c2e4f-6a8d-4c0e-9f2b-4a6c8e0a2c68

CHANGELOG:
- 0.11.0 (2026-08-09): Renamed Compress/api/compress to Amnesia per
  Elton's follow-up, and split it into two steps matching agent.py's
  /amnesia + /rebirth. POST /api/amnesia compresses+wipes self.history
  unconditionally, persists the recap to Context/amnesia_recap.txt
  (bubble.save_amnesia_recap), and only feeds it straight back in
  ("reborn": true) when self.config["auto_amnesia_memory_retrieval"] is
  True (Config tab checkbox, default True) -- otherwise leaves a true
  blank slate ("reborn": false) for a manual POST /api/rebirth
  (bubble.load_amnesia_recap + seed_history_with_recap) later. Header
  button split into AMNESIA + REBIRTH accordingly. Same fail-closed
  guarantee and on-disk-logs-untouched scope as before. Verified all
  three paths (auto=True immediate rebirth, auto=False blank slate,
  manual /api/rebirth retrieval) against the real Flask test_client.
- 0.10.0 (2026-08-09): Webagent fixes batch. (1) Tab bar: Config moved to
  the last/rightmost position; .tab-bar got explicit flex-wrap:nowrap and
  .tab-button flex-shrink:0 so overflow always scrolls horizontally
  instead of squishing labels. (2) New blank "Command" tab, first
  position -- placeholder only, no behavior yet, per Elton's instruction.
  (2.1) New "Notes" tab (4th, before Config): a single persistent
  free-text note, autosaved ~1.5s after typing stops via /api/notes
  (GET/POST) to notes/webagent_notes.txt -- plain text on disk, no BEJSON
  overhead for one text blob. (3) Fixed unreadable settings inputs: the
  old blanket input[type="text"] rule (meant only for the dark terminal
  command bar) was leaking white-on-white into the white settings
  overlay. Scoped that rule to #cmd-input specifically; added explicit
  red-on-white styling for every input/textarea/select inside .gui-body,
  inverting to a red field with white text only on :focus (while typing);
  tab-panel h2 headers and config-row-name labels now render in brand
  red too. (4) New force-compress/flush command: POST /api/compress
  compresses self.history (live model-facing memory) via the new
  bubble.run_full_session_compression(), then wipes and reseeds it with
  just the recap -- fails closed (history untouched) on any compression
  failure. Never touches the on-disk transcript logger. Wired to a new
  header COMPRESS button with a confirm() prompt (destructive action).
  Verified all four items against the real Flask test_client + a Node
  syntax check of the extracted <script> block: notes GET/POST round-trip
  to disk, compress with empty history (clean refusal), and compress
  with real history (wipe + reseed with the actual recap text) all
  passed.
- 0.9.0 (2026-08-09): Real Jobs tab (renamed from the empty "Tab 3"
  placeholder). Pure UI <-> Flask -- GET /api/jobs lists pending jobs
  (name, goal, task progress, active flag), POST /api/jobs/start and
  /api/jobs/stop set self._active_job_path/_active_job_doc directly on
  click. The AI is never told what's pending and never asked to pick;
  it only sees ACTIVE JOB context on its next turn once a job has
  actually been started from this tab, via the existing active_job
  wiring in api_chat. Per Elton's direct instruction: no AI-mediated
  "here's what's pending" step anywhere in this path.
- 0.8.0 (2026-08-08): Job Creation System groundwork -- jobs/ + jobs/complete/
  created at init, active job state tracked on self (_active_job_path/
  _active_job_doc), injected into build_system_prompt()'s new active_job
  param every request, and re-synced from ctx after run_action_queue so a
  <job_task_done/> completion (which can clear the active job when the
  last task finishes) persists across requests. No slash-command surface
  here (webagent has none) -- starting a job through this UI isn't wired
  yet; use agent.py's /jobstart or cliagent.py for now.
"""

import sys
import asyncio
from datetime import datetime
from pathlib import Path

# Insert lib/ directory into path to resolve lib_bejson_newagent_* correctly
# -- same pattern as agent.py, since this sits in the same directory.
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from flask import Flask, request, jsonify, render_template_string

import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_engine_rest as rest
import lib_bejson_newagent_config as config_lib
import lib_bejson_newagent_context_bubble as bubble
import lib_bejson_newagent_tui as tui
import lib_bejson_newagent_errors as errors
import lib_bejson_newagent_jobs as jobs
from lib_bejson_Core_bejson_env import source_env, get_env_path

# Mandatory environment sourcing (policy Sec 10) -- populates os.environ from
# env_file.py/env_file.json so INTERNAL_STORAGE, SD_CARD, etc. are readable
# via get_env_path() below instead of ever hardcoding a guessed path.
source_env()

VERSION = "0.11.0"

# Directories/paths -- identical layout to agent.py, since webagent.py is a
# sibling entry point sharing the same project, not a separate install.
BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"
CONFIG_PATH = CONFIG_DIR / "config.json"
KEYS_PATH = CONFIG_DIR / "keys.bejson"
STATE_PATH = CONFIG_DIR / "key_state.bejson"
MODELS_PATH = CONFIG_DIR / "models.bejson"
MODEL_CATALOG_PATH = CONFIG_DIR / "gemini_catalog.bejson"
LOGS_DIR = BASE_DIR / "logs"
CONTEXT_DIR = BASE_DIR / "Context"
BACKUPS_DIR = BASE_DIR / "backups"
JOBS_DIR = BASE_DIR / "jobs"
NOTES_DIR = BASE_DIR / "notes"
NOTES_FILE = NOTES_DIR / "webagent_notes.txt"

MAX_AUTO_CONTINUE = 5  # bounded loop cap -- same spirit as the circuit
                       # breaker: bounded, not runaway, even if the model
                       # keeps requesting actions indefinitely.


HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NewAgent - Terminal</title>
    <style>
        :root {
            --black: #000000;
            --white: #FFFFFF;
            --brand-red: #DE2626;
            /* Cubic bezier for snappy, geometric animations */
            --cubic-ease: cubic-bezier(0.86, 0, 0.07, 1);
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body, html {
            width: 100%;
            height: 100%;
            background-color: var(--black);
            color: var(--white);
            font-family: 'Courier New', Courier, monospace;
            overflow: hidden;
        }

        /* Scanline effect (Global) */
        .scanlines {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background: linear-gradient(to bottom, rgba(255,255,255,0), rgba(255,255,255,0) 50%, rgba(0,0,0,0.2) 50%, rgba(0,0,0,0.2));
            background-size: 100% 4px;
            z-index: 99999; /* Highest so it covers everything */
            pointer-events: none;
            opacity: 0.3;
        }

        /* --- Boot Screen --- */
        #boot-screen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-color: var(--black);
            z-index: 10000;
            display: flex;
            justify-content: center;
            align-items: center;
            flex-direction: column;
            transition: opacity 1s ease;
        }

        /* 3D Cubic Theme */
        .scene {
            width: 150px;
            height: 150px;
            perspective: 600px;
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            z-index: 1;
            transition: opacity 0.8s var(--cubic-ease), transform 1s var(--cubic-ease);
        }

        .scene.explode {
            transform: translate(-50%, -50%) scale(5);
            opacity: 0;
        }

        .cube {
            width: 100%;
            height: 100%;
            position: relative;
            transform-style: preserve-3d;
            transform: rotateX(-20deg) rotateY(-45deg);
            opacity: 0;
            animation: 
                fadeInCube 1s var(--cubic-ease) forwards,
                spinCube 6s infinite linear 1s;
        }

        .face {
            position: absolute;
            width: 150px;
            height: 150px;
            /* Red borders on black background - used sparingly */
            border: 2px solid var(--brand-red);
            background: rgba(0, 0, 0, 0.8);
            box-shadow: inset 0 0 20px rgba(222, 38, 38, 0.2);
        }

        .front  { transform: rotateY(  0deg) translateZ(75px); }
        .back   { transform: rotateY(180deg) translateZ(75px); }
        .right  { transform: rotateY( 90deg) translateZ(75px); }
        .left   { transform: rotateY(-90deg) translateZ(75px); }
        .top    { transform: rotateX( 90deg) translateZ(75px); }
        .bottom { transform: rotateX(-90deg) translateZ(75px); }

        @keyframes fadeInCube {
            0% { transform: scale(0.2) rotateX(-20deg) rotateY(-45deg); opacity: 0; }
            100% { transform: scale(1) rotateX(-20deg) rotateY(-45deg); opacity: 1; }
        }

        @keyframes spinCube {
            0% { transform: rotateX(-20deg) rotateY(-45deg); }
            100% { transform: rotateX(340deg) rotateY(315deg); }
        }

        /* Boot Typography & UI */
        .text-container {
            position: absolute;
            z-index: 10;
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
            opacity: 0;
            transform: translateY(20px);
            transition: opacity 1s var(--cubic-ease), transform 1s var(--cubic-ease);
        }

        .text-container.show {
            opacity: 1;
            transform: translateY(0);
        }

        .text-container h1 {
            font-size: 4rem;
            font-weight: 900;
            margin: 0;
            letter-spacing: 0.2rem;
            color: var(--white);
            text-transform: uppercase;
            font-family: system-ui, -apple-system, sans-serif;
            position: relative;
        }

        .text-container h1::after {
            content: '';
            position: absolute;
            bottom: -10px;
            left: 0;
            width: 0%;
            height: 4px;
            background-color: var(--brand-red);
            transition: width 1s var(--cubic-ease) 0.5s;
        }

        .text-container.show h1::after {
            width: 100%;
        }

        .sub-text {
            margin-top: 20px;
            font-size: 0.9rem;
            color: var(--brand-red);
            opacity: 0.8;
            height: 20px;
            letter-spacing: 0.1rem;
        }

        .cursor {
            display: inline-block;
            width: 8px;
            height: 1em;
            background-color: var(--brand-red);
            vertical-align: middle;
            margin-left: 5px;
            animation: blink 1s step-end infinite;
        }

        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0; }
        }

        /* --- Terminal Interface --- */
        #terminal {
            display: none; /* Hidden until boot sequence finishes */
            opacity: 0;
            transition: opacity 1s ease;
            height: 100%;
            padding: 20px;
            color: var(--white);
            flex-direction: column;
            overflow: hidden; /* header/footer are fixed; #log-container
                                  below is the only scrolling region */

            /* Background Image with dark overlay for readability */
            background-image: linear-gradient(rgba(0, 0, 0, 0.75), rgba(0, 0, 0, 0.75)), url('images/NewAgent.png');
            background-size: cover;
            background-position: center;
            background-repeat: no-repeat;
        }

        #log-container {
            flex: 1 1 auto;
            min-height: 0; /* required for flex children to actually shrink
                              and scroll instead of overflowing the parent */
            overflow-y: auto;
        }

        .log {
            white-space: pre-wrap;
            word-wrap: break-word;
            margin-bottom: 8px;
            line-height: 1.4;
        }

        .prompt {
            color: var(--brand-red);
            font-weight: bold;
            user-select: none;
            margin-right: 10px;
        }

        .input-wrapper {
            display: flex;
            align-items: center;
            margin-top: 4px;
        }

        /* --- Agent Header (3 rows): buttons + 2 live status rows --- */
        #agent-header {
            background: transparent; /* same as #terminal's own background --
                                         nothing boxes this off visually */
            border-bottom: 1px solid rgba(255, 255, 255, 0.15);
            padding-bottom: 8px;
            margin-bottom: 10px;
            flex-shrink: 0;
        }

        .header-row {
            display: flex;
            align-items: center;
            font-family: 'Courier New', Courier, monospace;
        }

        .header-row-buttons {
            gap: 10px;
            padding: 6px 0;
        }

        .header-btn {
            background: transparent;
            border: 1px solid transparent;
            color: var(--brand-red);
            font-family: 'Courier New', Courier, monospace;
            font-weight: bold;
            font-size: 0.8rem;
            letter-spacing: 1px;
            padding: 6px 14px;
            cursor: pointer;
            transition: border-color 0.2s ease;
        }

        .header-btn:hover,
        .header-btn:focus {
            border: 1px solid var(--brand-red);
            outline: none;
        }

        .header-row-status {
            font-size: 0.75rem;
            color: var(--white);
            opacity: 0.9;
            gap: 18px;
            padding: 2px 0;
            flex-wrap: wrap;
        }

        .status-label {
            color: var(--brand-red);
            font-weight: bold;
        }

        #status-model-select {
            background: transparent;
            color: var(--white);
            border: none;
            border-bottom: 1px solid rgba(255, 255, 255, 0.3);
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.75rem;
            padding: 1px 2px;
            cursor: pointer;
            max-width: 180px;
        }

        #status-model-select:hover,
        #status-model-select:focus {
            border-bottom-color: var(--brand-red);
            outline: none;
        }

        #status-model-select option {
            background: var(--black);
            color: var(--white);
        }

        /* --- Agent Footer (1 row): current CWD --- */
        #agent-footer {
            flex-shrink: 0;
            border-top: 1px solid rgba(255, 255, 255, 0.15);
            margin-top: 8px;
            padding-top: 6px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.8rem;
            color: var(--white);
            white-space: nowrap;
            overflow-x: auto;
        }

        #agent-footer .status-label {
            margin-right: 8px;
        }

        #cmd-input {
            background: transparent;
            border: none;
            color: var(--white);
            font-family: inherit;
            font-size: 1rem;
            flex: 1;
            outline: none;
            caret-color: var(--white);
        }

        /* --- Full Overlay GUI Window (Settings) --- */
        #gui-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            background-color: var(--white); 
            z-index: 9000;
            flex-direction: column;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }

        .gui-header {
            background-color: var(--brand-red);
            color: var(--white);
            padding: 12px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 1.1rem;
            font-weight: 600;
            letter-spacing: 0.5px;
        }

        .close-btn {
            background: transparent;
            border: none;
            color: var(--white);
            font-size: 1.5rem;
            line-height: 1;
            cursor: pointer;
            font-weight: bold;
        }

        .close-btn:hover {
            opacity: 0.8;
        }

        .gui-body {
            flex: 1;
            background-color: var(--white);
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Tab System */
        .tab-bar {
            display: flex;
            flex-wrap: nowrap;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            background-color: var(--white);
            border-bottom: 1px solid var(--black);
            scrollbar-width: none; 
        }

        .tab-bar::-webkit-scrollbar {
            display: none; 
        }

        .tab-button {
            padding: 12px 24px;
            cursor: pointer;
            border: none;
            background: none;
            font-size: 1rem;
            font-weight: bold;
            color: var(--black);
            white-space: nowrap;
            flex-shrink: 0;
            border-bottom: 3px solid transparent;
            transition: color 0.2s ease, border-color 0.2s ease, background-color 0.2s ease;
        }

        .tab-button:hover {
            background-color: #f0f0f0;
        }

        .tab-button.active {
            color: var(--brand-red);
            border-bottom: 3px solid var(--brand-red);
        }

        .tab-content-container {
            flex: 1;
            overflow: hidden;
            position: relative;
        }

        .tab-panel {
            display: none;
            height: 100%;
            overflow-y: auto;
            padding: 20px;
            color: var(--black);
        }

        .tab-panel h2 {
            margin-bottom: 15px;
        }

        .tab-panel.active {
            display: block;
        }

        /* --- Settings input legibility fix (2026-08-09) ---
           These inputs live inside #gui-overlay's white .gui-body, but with
           no color declared here they were inheriting the dark-terminal
           #cmd-input's white-on-transparent style via the old blanket
           input[type="text"] selector -- white text on a white panel,
           unreadable. Every input/textarea/select in the settings overlay
           now gets an explicit red font on a white field, and header
           labels (h2 section titles + each setting's name label) are red
           too so they read as labels rather than body text. */
        .gui-body input[type="text"],
        .gui-body input[type="number"],
        .gui-body textarea,
        .gui-body select {
            background-color: var(--white);
            color: var(--brand-red);
            border: 1px solid var(--black);
            caret-color: var(--brand-red);
        }

        /* Selection/typing state only: invert to a red field with white
           text, per spec ("only on selection while you're typing"). */
        .gui-body input[type="text"]:focus,
        .gui-body input[type="number"]:focus,
        .gui-body textarea:focus,
        .gui-body select:focus {
            background-color: var(--brand-red);
            color: var(--white);
            caret-color: var(--white);
            outline: none;
        }

        .tab-panel h2 {
            color: var(--brand-red);
        }

        .config-row-name {
            color: var(--brand-red);
        }

        .notes-label {
            color: var(--brand-red);
        }

        #notes-textarea {
            width: 100%;
            height: 65vh;
            min-height: 260px;
            margin-top: 8px;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.95rem;
            padding: 10px;
            resize: vertical;
        }

        /* --- Config Tab --- */
        .config-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #e0e0e0;
            gap: 16px;
        }

        .config-row-info {
            flex: 1;
            min-width: 0;
        }

        .config-row-name {
            font-weight: bold;
            font-size: 0.95rem;
        }

        .config-row-desc {
            font-size: 0.8rem;
            color: #555;
            margin-top: 2px;
        }

        .config-row-control {
            flex-shrink: 0;
        }

        .config-row-control input[type="text"],
        .config-row-control input[type="number"] {
            font-family: 'Courier New', Courier, monospace;
            border: 1px solid var(--black);
            padding: 6px 8px;
            width: 140px;
            font-size: 0.9rem;
        }

        .config-row-control input[type="checkbox"] {
            width: 20px;
            height: 20px;
            accent-color: var(--brand-red);
            cursor: pointer;
        }

        .config-save-flash {
            color: var(--brand-red);
            font-size: 0.75rem;
            margin-left: 8px;
            opacity: 0;
            transition: opacity 0.3s ease;
        }

        .config-save-flash.show {
            opacity: 1;
        }

        /* --- Files Tab --- */
        .file-browser-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }

        .file-breadcrumb {
            font-size: 0.85rem;
            font-weight: bold;
            word-break: break-all;
        }

        .attachment-badge {
            background-color: var(--brand-red);
            color: var(--white);
            padding: 3px 10px;
            font-size: 0.8rem;
            font-weight: bold;
            white-space: nowrap;
        }

        .file-addressbar {
            display: flex;
            gap: 6px;
            margin-bottom: 10px;
        }

        .file-addressbar input[type="text"] {
            flex: 1;
            font-family: 'Courier New', Courier, monospace;
            border: 1px solid var(--black);
            padding: 6px 8px;
            font-size: 0.85rem;
            min-width: 0;
        }

        .file-addressbar button {
            font-family: 'Courier New', Courier, monospace;
            border: 1px solid var(--black);
            background: var(--white);
            color: var(--black);
            padding: 6px 12px;
            font-size: 0.85rem;
            font-weight: bold;
            cursor: pointer;
            white-space: nowrap;
        }

        .file-addressbar button:hover {
            background: var(--brand-red);
            color: var(--white);
            border-color: var(--brand-red);
        }

        .file-quickjumps {
            display: flex;
            gap: 6px;
            margin-bottom: 12px;
            flex-wrap: wrap;
        }

        .file-quickjumps button {
            font-family: 'Courier New', Courier, monospace;
            border: 1px solid #999;
            background: var(--white);
            color: #555;
            padding: 4px 10px;
            font-size: 0.75rem;
            cursor: pointer;
        }

        .file-quickjumps button:hover {
            border-color: var(--brand-red);
            color: var(--brand-red);
        }

        .file-row {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px 4px;
            border-bottom: 1px solid #eee;
            cursor: pointer;
        }

        .file-row:hover {
            background-color: #f7f7f7;
        }

        .file-row .file-name {
            flex: 1;
            font-size: 0.9rem;
        }

        .file-row.is-dir .file-name {
            font-weight: bold;
        }

        .file-row .file-size {
            font-size: 0.75rem;
            color: #777;
        }

        .file-row input[type="checkbox"] {
            width: 18px;
            height: 18px;
            accent-color: var(--brand-red);
            cursor: pointer;
        }

        /* --- Jobs Tab --- */
        .job-tab-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            font-size: 0.85rem;
            font-weight: bold;
        }

        .job-tab-header button {
            font-family: 'Courier New', Courier, monospace;
            border: 1px solid var(--black);
            background: var(--white);
            color: var(--black);
            padding: 4px 10px;
            font-size: 0.8rem;
            cursor: pointer;
        }

        .job-tab-header button:hover {
            background: var(--brand-red);
            color: var(--white);
            border-color: var(--brand-red);
        }

        .job-row {
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 8px;
            border-bottom: 1px solid #eee;
        }

        .job-row.is-active {
            background-color: #fdecec;
            border-left: 3px solid var(--brand-red);
        }

        .job-row .job-info {
            flex: 1;
            min-width: 0;
        }

        .job-row .job-name {
            font-size: 0.9rem;
            font-weight: bold;
        }

        .job-row .job-goal {
            font-size: 0.78rem;
            color: #666;
            word-break: break-word;
        }

        .job-row .job-progress {
            font-size: 0.75rem;
            color: #777;
        }

        .job-row button.job-start-btn {
            font-family: 'Courier New', Courier, monospace;
            border: 1px solid var(--black);
            background: var(--white);
            color: var(--black);
            padding: 6px 12px;
            font-size: 0.8rem;
            font-weight: bold;
            cursor: pointer;
            white-space: nowrap;
        }

        .job-row button.job-start-btn:hover {
            background: var(--brand-red);
            color: var(--white);
            border-color: var(--brand-red);
        }

        .job-row button.job-start-btn:disabled {
            opacity: 0.5;
            cursor: default;
        }
    </style>
</head>
<body>

    <!-- Global Scanlines -->
    <div class="scanlines"></div>

    <!-- BOOT SEQUENCE SCREEN -->
    <div id="boot-screen">
        <div class="scene" id="cube-scene">
            <div class="cube">
                <div class="face front"></div>
                <div class="face back"></div>
                <div class="face right"></div>
                <div class="face left"></div>
                <div class="face top"></div>
                <div class="face bottom"></div>
            </div>
        </div>

        <div class="text-container" id="main-ui">
            <h1 id="title-text"></h1>
            <div class="sub-text">
                <span id="console-text"></span><span class="cursor"></span>
            </div>
        </div>
    </div>

    <!-- MAIN TERMINAL SYSTEM -->
    <div id="terminal">
        <div id="agent-header">
            <div class="header-row header-row-buttons">
                <button class="header-btn" id="header-settings-btn">&#9881; SETTINGS</button>
                <button class="header-btn" id="header-clear-btn">&#10005; CLEAR</button>
                <button class="header-btn" id="header-amnesia-btn">&#8987; AMNESIA</button>
                <button class="header-btn" id="header-rebirth-btn">&#9851; REBIRTH</button>
            </div>
            <div class="header-row header-row-status" id="header-status-1">
                <span><span class="status-label">MODEL:</span> <select id="status-model-select"><option>--</option></select></span>
                <span><span class="status-label">ENGINE:</span> <span id="status-engine">--</span></span>
                <span><span class="status-label">KEYS:</span> <span id="status-keys">--</span></span>
            </div>
            <div class="header-row header-row-status" id="header-status-2">
                <span><span class="status-label">TURNS:</span> <span id="status-turns">0</span></span>
                <span><span class="status-label">EXECS:</span> <span id="status-execs">0</span></span>
                <span><span class="status-label">STATUS:</span> <span id="status-state">READY</span></span>
            </div>
        </div>
        <div id="log-container">
            <div class="log" style="color: var(--brand-red); font-weight: bold; font-size: 1.2rem; margin-bottom: 8px;">NewAgent - Commands:</div>
            <div class="log">- /help</div>
            <div class="log" style="margin-bottom: 12px;">- /settings</div>
        </div>
        <div class="input-wrapper">
            <span class="prompt">user@termux:~$</span>
            <input type="text" id="cmd-input" autocomplete="off" spellcheck="false">
        </div>
        <div id="agent-footer">
            <span class="status-label">CWD:</span><span id="footer-cwd">/</span>
        </div>
    </div>

    <!-- SETTINGS GUI OVERLAY -->
    <div id="gui-overlay">
        <div class="gui-header">
            <span class="window-title">Settings</span>
            <button class="close-btn" id="close-btn" aria-label="Close settings">✕</button>
        </div>
        <div class="gui-body">
            <div class="tab-bar">
                <button class="tab-button active" data-tab="tab-command">Command</button>
                <button class="tab-button" data-tab="tab-files">Files</button>
                <button class="tab-button" data-tab="tab-jobs">Jobs</button>
                <button class="tab-button" data-tab="tab-notes">Notes</button>
                <button class="tab-button" data-tab="tab-config">Config</button>
            </div>
            <div class="tab-content-container">
                <div class="tab-panel active" id="tab-command">
                    <h2>Command</h2>
                </div>
                <div class="tab-panel" id="tab-files">
                    <h2>Files</h2>
                    <div class="file-browser-header">
                        <span class="file-breadcrumb" id="file-breadcrumb">/</span>
                        <span class="attachment-badge" id="attachment-badge">0 attached</span>
                    </div>
                    <div class="file-addressbar">
                        <input type="text" id="file-path-input" placeholder="/storage/emulated/0 or any absolute path...">
                        <button id="file-go-btn">Go</button>
                    </div>
                    <div class="file-quickjumps" id="file-quickjumps"><em>Loading quick jumps...</em></div>
                    <div id="file-list"><em>Loading...</em></div>
                </div>
                <div class="tab-panel" id="tab-jobs">
                    <h2>Jobs</h2>
                    <div class="job-tab-header">
                        <span id="job-active-badge">No active job</span>
                        <button id="job-stop-btn" style="display:none;">Stop</button>
                    </div>
                    <div id="job-list"><em>Loading...</em></div>
                </div>
                <div class="tab-panel" id="tab-notes">
                    <h2>Notes</h2>
                    <div class="notes-label" id="notes-status">Loading...</div>
                    <textarea id="notes-textarea" placeholder="Type here -- autosaves a couple seconds after you stop typing."></textarea>
                </div>
                <div class="tab-panel" id="tab-config">
                    <h2>Configuration</h2>
                    <div id="config-list"><em>Loading...</em></div>
                </div>
            </div>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', () => {
            
            // --- BOOT SEQUENCE LOGIC ---
            const bootScreen = document.getElementById('boot-screen');
            const consoleText = document.getElementById('console-text');
            const titleText = document.getElementById('title-text');
            const cubeScene = document.getElementById('cube-scene');
            const mainUI = document.getElementById('main-ui');
            const terminalScreen = document.getElementById('terminal');
            const cmdInput = document.getElementById('cmd-input');

            const bootSequence = [
                "MOUNTING BEJSON SCHEMA 104a...",
                "CHECKING FILE HASHES...",
                "LOADING MCP PROTOCOLS...",
                "INITIALIZING NEURAL PATHWAYS...",
                "SYSTEM READY."
            ];
            const finalTitle = "NewAgent";
            
            async function typeText(element, text, speed = 30) {
                element.innerText = "";
                for (let i = 0; i < text.length; i++) {
                    element.innerText += text.charAt(i);
                    await new Promise(r => setTimeout(r, speed));
                }
            }

            async function scrambleText(element, targetText, duration = 1000) {
                const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*";
                let iterations = 0;
                const maxIterations = 15;
                
                return new Promise(resolve => {
                    const interval = setInterval(() => {
                        element.innerText = targetText.split('').map((letter, index) => {
                            if (index < (iterations / maxIterations) * targetText.length) {
                                return targetText[index];
                            }
                            return chars[Math.floor(Math.random() * chars.length)];
                        }).join('');
                        
                        iterations++;
                        if (iterations > maxIterations) {
                            clearInterval(interval);
                            element.innerText = targetText;
                            resolve();
                        }
                    }, duration / maxIterations);
                });
            }

            async function runTimeline() {
                // Phase 1: Boot sequence text (Bottom)
                await new Promise(r => setTimeout(r, 1200));

                for (let i = 0; i < bootSequence.length - 1; i++) {
                    await typeText(consoleText, bootSequence[i], 20);
                    await new Promise(r => setTimeout(r, 400));
                }

                // Phase 2: Explode cube and reveal title
                cubeScene.classList.add('explode');
                mainUI.classList.add('show');
                
                // Final boot message
                typeText(consoleText, bootSequence[bootSequence.length - 1], 50);

                // Phase 3: Scramble/Glitch the main title
                await new Promise(r => setTimeout(r, 300));
                await scrambleText(titleText, finalTitle, 800);

                // Phase 4: Transition to Terminal
                await new Promise(r => setTimeout(r, 1200)); // Linger on the title for a moment
                bootScreen.style.opacity = '0';
                
                setTimeout(() => {
                    bootScreen.style.display = 'none';
                    terminalScreen.style.display = 'flex';
                    
                    // Trigger a reflow to ensure the CSS transition fires
                    void terminalScreen.offsetWidth; 
                    terminalScreen.style.opacity = '1';
                    
                    // Focus the terminal input immediately upon entering
                    cmdInput.focus(); 
                }, 1000); // Matches the 1s CSS opacity transition
            }

            // Start boot timeline immediately
            runTimeline();


            // --- TERMINAL & GUI LOGIC ---
            const terminal = document.getElementById('terminal');
            const logContainer = document.getElementById('log-container');
            const guiOverlay = document.getElementById('gui-overlay');
            const closeBtn = document.getElementById('close-btn');
            let currentPromptCwd = null; // updated from server after each /api/exec call
            let attachedFiles = new Set(); // paths checked in the Files tab; cleared on first send
            let currentBrowsePath = null;
            let isSending = false; // guards the 4s status poll from overwriting the sending animation
            let sendingAnimTimer = null;
            let lastSent = null; // { mode: 'chat'|'raw', text: '...' } -- for /last
            let currentAbortController = null; // for /stop

            // Force focus back to input when clicking anywhere in the terminal
            document.addEventListener('click', (e) => {
                if (guiOverlay.style.display !== 'flex' && bootScreen.style.display === 'none') {
                    cmdInput.focus();
                }
            });

            // Command execution engine
            cmdInput.addEventListener('keydown', async (e) => {
                if (e.key === 'Enter') {
                    const command = cmdInput.value.trim();
                    if (command) {
                        appendCommandEcho(command);
                        cmdInput.value = '';
                        cmdInput.disabled = true;
                        await processCommand(command);
                        cmdInput.disabled = false;
                        cmdInput.focus();
                    }
                    cmdInput.value = '';
                    scrollToBottom();
                }
            });

            // Router for terminal input. /settings, /help, and clear stay
            // local. A leading '!' is an explicit raw-shell escape hatch
            // (runs via /api/exec, bypassing the agent entirely) for power
            // users who genuinely want direct bash. Everything else is a
            // PROMPT to the actual NewAgent agent loop via /api/chat -- the
            // agent itself decides what, if anything, to run. This is the
            // corrected default: plain input is not a bash shell.
            async function processCommand(cmd) {
                const normalizedCmd = cmd.toLowerCase();

                const validSettingsCommands = [
                    '/settings',
                    'settings',
                    'g "settings"',
                    "g 'settings'",
                    'g settings'
                ];

                if (validSettingsCommands.includes(normalizedCmd)) {
                    openGUI();
                } else if (normalizedCmd === '/help' || normalizedCmd === 'help') {
                    appendLog('Type a prompt to talk to NewAgent (it decides what to run). Prefix with ! to run a raw shell command directly, e.g. !ls -la. /last resends your last message, /stop cancels an in-flight request. Other commands: /settings, clear.');
                } else if (normalizedCmd === 'clear') {
                    logContainer.innerHTML = '';
                } else if (normalizedCmd === '/stop') {
                    if (currentAbortController) {
                        currentAbortController.abort();
                        appendLog('[stopping current request...]');
                    } else {
                        appendLog('[nothing in flight to stop]');
                    }
                } else if (normalizedCmd === '/last') {
                    if (!lastSent) {
                        appendLog('[no previous message to resend]');
                    } else if (lastSent.mode === 'raw') {
                        appendCommandEcho('!' + lastSent.text);
                        await sendRawExec(lastSent.text);
                    } else {
                        appendCommandEcho(lastSent.text);
                        await sendChatPrompt(lastSent.text);
                    }
                } else if (cmd.startsWith('!')) {
                    await sendRawExec(cmd.slice(1).trim());
                } else {
                    await sendChatPrompt(cmd);
                }
                scrollToBottom();
            }

            // Explicit raw-shell escape hatch (!command) -- bypasses the
            // agent entirely, runs directly via do_exec through /api/exec.
            async function sendRawExec(cmd) {
                if (!cmd) return;
                lastSent = { mode: 'raw', text: cmd };
                // Copy to clipboard immediately before sending -- if the
                // request fails, it's already sitting in the clipboard to
                // paste back in, no need to retype it.
                try { await navigator.clipboard.writeText(cmd); } catch (err) { /* clipboard not available -- not fatal */ }

                const attachmentsToSend = Array.from(attachedFiles);
                currentAbortController = new AbortController();
                startSendingAnimation();
                try {
                    const resp = await fetch('/api/exec', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ command: cmd, cwd: currentPromptCwd, attachments: attachmentsToSend }),
                        signal: currentAbortController.signal,
                    });
                    const data = await resp.json();
                    if (data.output) appendLog(data.output);
                    if (data.cwd) { currentPromptCwd = data.cwd; updateCwdDisplay(data.cwd); }
                    if (!resp.ok) appendLog(`bash: ${cmd}: ${data.error || 'request failed'}`);
                } catch (err) {
                    if (err.name === 'AbortError') {
                        appendLog(`[stopped] ${cmd}`);
                    } else {
                        appendLog(`bash: ${cmd}: connection to NewAgent backend failed (${err})`);
                    }
                } finally {
                    currentAbortController = null;
                    stopSendingAnimation();
                    if (attachmentsToSend.length > 0) clearAttachmentsAfterSend();
                }
            }

            // Default path: send the typed text as a PROMPT to the actual
            // NewAgent agent loop (/api/chat), which assembles context, calls
            // the engine, and executes any action tags the model itself
            // requests -- rendering the mixed text/action transcript in order.
            async function sendChatPrompt(message) {
                lastSent = { mode: 'chat', text: message };
                try { await navigator.clipboard.writeText(message); } catch (err) { /* clipboard not available -- not fatal */ }

                const attachmentsToSend = Array.from(attachedFiles);
                currentAbortController = new AbortController();
                startSendingAnimation();
                try {
                    const resp = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ message, attachments: attachmentsToSend }),
                        signal: currentAbortController.signal,
                    });
                    const data = await resp.json();
                    if (!resp.ok) {
                        appendLog(`[error] ${data.error || 'request failed'}`);
                        return;
                    }
                    (data.turn_log || []).forEach(entry => {
                        if (entry.type === 'text') {
                            appendLog(entry.content);
                        } else if (entry.type === 'action') {
                            appendCommandEcho(entry.source);
                            if (entry.output) appendLog(entry.output);
                        }
                    });
                    if (data.cwd) { currentPromptCwd = data.cwd; updateCwdDisplay(data.cwd); }
                    if (data.hit_iteration_cap) {
                        appendLog(`[NewAgent stopped after ${data.iterations} automatic steps -- send another prompt to continue]`);
                    }
                } catch (err) {
                    if (err.name === 'AbortError') {
                        appendLog(`[stopped] ${message}`);
                    } else {
                        appendLog(`[error] connection to NewAgent backend failed (${err})`);
                    }
                } finally {
                    currentAbortController = null;
                    stopSendingAnimation();
                    if (attachmentsToSend.length > 0) clearAttachmentsAfterSend();
                }
            }

            function appendLog(text) {
                const logEntry = document.createElement('div');
                logEntry.className = 'log';
                logEntry.textContent = text;
                logContainer.appendChild(logEntry);
            }

            function appendCommandEcho(commandText) {
                const logEntry = document.createElement('div');
                logEntry.className = 'log';
                
                const promptSpan = document.createElement('span');
                promptSpan.className = 'prompt';
                promptSpan.textContent = 'user@termux:~$';
                
                const textSpan = document.createElement('span');
                textSpan.style.color = 'var(--white)';
                textSpan.textContent = commandText;
                
                logEntry.appendChild(promptSpan);
                logEntry.appendChild(textSpan);
                logContainer.appendChild(logEntry);
            }

            function scrollToBottom() {
                terminal.scrollTop = terminal.scrollHeight;
            }

            function openGUI() {
                guiOverlay.style.display = 'flex';
                cmdInput.blur();
                loadConfig();
                loadFiles(currentBrowsePath);
                loadJobs();
                loadNotes();
            }

            function closeGUI() {
                guiOverlay.style.display = 'none';
                cmdInput.focus();
            }

            // --- Config Tab ---
            async function loadConfig() {
                const listEl = document.getElementById('config-list');
                try {
                    const resp = await fetch('/api/config');
                    const data = await resp.json();
                    renderConfig(data.config || []);
                } catch (err) {
                    listEl.innerHTML = `<em>Failed to load config: ${err}</em>`;
                }
            }

            function renderConfig(rows) {
                const listEl = document.getElementById('config-list');
                listEl.innerHTML = '';
                rows.forEach(row => {
                    const rowEl = document.createElement('div');
                    rowEl.className = 'config-row';

                    const info = document.createElement('div');
                    info.className = 'config-row-info';
                    const nameEl = document.createElement('div');
                    nameEl.className = 'config-row-name';
                    nameEl.textContent = row.name;
                    const descEl = document.createElement('div');
                    descEl.className = 'config-row-desc';
                    descEl.textContent = row.description || '';
                    info.appendChild(nameEl);
                    info.appendChild(descEl);

                    const control = document.createElement('div');
                    control.className = 'config-row-control';

                    const flash = document.createElement('span');
                    flash.className = 'config-save-flash';
                    flash.textContent = 'saved';

                    let input;
                    if (row.type === 'bool') {
                        input = document.createElement('input');
                        input.type = 'checkbox';
                        input.checked = !!row.value;
                        input.addEventListener('change', () => saveConfigValue(row.name, input.checked, flash));
                    } else if (row.type === 'int' || row.type === 'float') {
                        input = document.createElement('input');
                        input.type = 'number';
                        input.value = row.value;
                        if (row.type === 'float') input.step = 'any';
                        input.addEventListener('change', () => saveConfigValue(row.name, input.value, flash));
                    } else {
                        input = document.createElement('input');
                        input.type = 'text';
                        input.value = row.value;
                        input.addEventListener('change', () => saveConfigValue(row.name, input.value, flash));
                    }

                    control.appendChild(input);
                    control.appendChild(flash);
                    rowEl.appendChild(info);
                    rowEl.appendChild(control);
                    listEl.appendChild(rowEl);
                });
            }

            async function saveConfigValue(name, value, flashEl) {
                try {
                    const resp = await fetch('/api/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name, value }),
                    });
                    if (resp.ok) {
                        flashEl.classList.add('show');
                        setTimeout(() => flashEl.classList.remove('show'), 900);
                    } else {
                        const data = await resp.json();
                        flashEl.textContent = data.error || 'save failed';
                        flashEl.classList.add('show');
                    }
                } catch (err) {
                    flashEl.textContent = 'save failed';
                    flashEl.classList.add('show');
                }
            }

            // --- Files Tab ---
            async function loadFiles(path) {
                const listEl = document.getElementById('file-list');
                try {
                    const url = path ? `/api/files/browse?path=${encodeURIComponent(path)}` : '/api/files/browse';
                    const resp = await fetch(url);
                    const data = await resp.json();
                    if (!resp.ok) {
                        listEl.innerHTML = `<em>${data.error || 'failed to browse'}</em>`;
                        return;
                    }
                    currentBrowsePath = data.path;
                    document.getElementById('file-breadcrumb').textContent = data.path;
                    document.getElementById('file-path-input').value = data.path;
                    renderFiles(data);
                } catch (err) {
                    listEl.innerHTML = `<em>Failed to load files: ${err}</em>`;
                }
            }

            function renderFiles(data) {
                const listEl = document.getElementById('file-list');
                listEl.innerHTML = '';

                if (data.parent) {
                    const upRow = document.createElement('div');
                    upRow.className = 'file-row is-dir';
                    upRow.innerHTML = '<span class="file-name">.. (parent directory)</span>';
                    upRow.addEventListener('click', () => loadFiles(data.parent));
                    listEl.appendChild(upRow);
                }

                (data.entries || []).forEach(entry => {
                    const row = document.createElement('div');
                    row.className = 'file-row' + (entry.is_dir ? ' is-dir' : '');

                    if (entry.is_dir) {
                        row.innerHTML = `<span class="file-name">${entry.name}/</span>`;
                        row.addEventListener('click', () => loadFiles(entry.path));
                    } else {
                        const checkbox = document.createElement('input');
                        checkbox.type = 'checkbox';
                        checkbox.checked = attachedFiles.has(entry.path);
                        checkbox.addEventListener('click', (e) => e.stopPropagation());
                        checkbox.addEventListener('change', () => toggleAttachment(entry.path, checkbox.checked));

                        const nameSpan = document.createElement('span');
                        nameSpan.className = 'file-name';
                        nameSpan.textContent = entry.name;

                        const sizeSpan = document.createElement('span');
                        sizeSpan.className = 'file-size';
                        sizeSpan.textContent = entry.size != null ? `${entry.size}B` : '';

                        row.appendChild(checkbox);
                        row.appendChild(nameSpan);
                        row.appendChild(sizeSpan);
                        row.addEventListener('click', () => { checkbox.checked = !checkbox.checked; toggleAttachment(entry.path, checkbox.checked); });
                    }
                    listEl.appendChild(row);
                });
            }

            function toggleAttachment(path, checked) {
                if (checked) {
                    attachedFiles.add(path);
                } else {
                    attachedFiles.delete(path);
                }
                updateAttachmentBadge();
            }

            function updateAttachmentBadge() {
                document.getElementById('attachment-badge').textContent = `${attachedFiles.size} attached`;
            }

            // Clears every checked attachment box and the underlying state.
            // Called once a command carrying attachments has actually been
            // sent -- "unchecks on first send", not a persistent selection.
            function clearAttachmentsAfterSend() {
                attachedFiles.clear();
                updateAttachmentBadge();
                document.querySelectorAll('#file-list .file-row:not(.is-dir) input[type="checkbox"]').forEach(cb => { cb.checked = false; });
            }

            closeBtn.addEventListener('click', closeGUI);

            // Header buttons (row 1): Settings opens the same overlay /settings
            // does; Clear wipes the log the same way typing "clear" does.
            document.getElementById('header-settings-btn').addEventListener('click', openGUI);
            document.getElementById('header-clear-btn').addEventListener('click', () => {
                logContainer.innerHTML = '';
            });
            document.getElementById('header-amnesia-btn').addEventListener('click', async () => {
                // Distinct from Clear (which only wipes the on-screen log
                // display): this actually compresses+wipes the agent's
                // real server-side memory. On-disk logs are never touched.
                // Whether the recap is fed straight back in ("reborn") or
                // left waiting for a manual Rebirth click depends on the
                // auto_amnesia_memory_retrieval setting (Config tab).
                if (!confirm('Compress and wipe the agent\'s session memory?\n\nThis replaces its entire working memory with a single compressed recap. Depending on the Config tab\'s "auto_amnesia_memory_retrieval" setting, the recap is either fed straight back in or left waiting for a manual Rebirth. Your on-disk logs are not affected.')) {
                    return;
                }
                appendLog('[amnesia] Compressing session memory...');
                try {
                    const resp = await fetch('/api/amnesia', { method: 'POST' });
                    const data = await resp.json();
                    if (data.ok) {
                        appendLog(data.reborn
                            ? `[amnesia] Done -- memory wiped and recap (${data.recap_chars} chars) reborn immediately.`
                            : `[amnesia] Done -- true blank slate. Recap (${data.recap_chars} chars) saved; click Rebirth when ready.`);
                    } else {
                        appendLog(`[amnesia] ${data.error}`);
                    }
                } catch (err) {
                    appendLog(`[amnesia] Failed: ${err}`);
                }
            });
            document.getElementById('header-rebirth-btn').addEventListener('click', async () => {
                appendLog('[rebirth] Retrieving last compressed recap...');
                try {
                    const resp = await fetch('/api/rebirth', { method: 'POST' });
                    const data = await resp.json();
                    if (data.ok) {
                        appendLog(`[rebirth] Done -- recap (${data.recap_chars} chars) fed back into memory.`);
                    } else {
                        appendLog(`[rebirth] ${data.error}`);
                    }
                } catch (err) {
                    appendLog(`[rebirth] Failed: ${err}`);
                }
            });

            function updateCwdDisplay(cwd) {
                if (cwd) document.getElementById('footer-cwd').textContent = cwd;
            }

            // Header rows 2-3: live client/session status, polled periodically
            // so it stays current without needing a page reload.
            async function loadStatus() {
                try {
                    const resp = await fetch('/api/status');
                    const data = await resp.json();
                    document.getElementById('status-model').textContent = data.active_model || '--';
                    document.getElementById('status-engine').textContent = (data.engine || 'rest').toUpperCase();
                    document.getElementById('status-keys').textContent =
                        `${data.keys_available ?? '--'}/${data.key_count ?? '--'}`;
                    document.getElementById('status-turns').textContent = data.turns ?? 0;
                    document.getElementById('status-execs').textContent = data.execs ?? 0;
                    if (!isSending) document.getElementById('status-state').textContent = 'READY';
                    updateCwdDisplay(data.cwd);

                    // Keep the model dropdown's current selection in sync with
                    // server state (e.g. if changed via a chat prompt or CLI)
                    // without fighting the user mid-interaction with the list.
                    const modelSelect = document.getElementById('status-model-select');
                    if (data.active_model && modelSelect.value !== data.active_model && document.activeElement !== modelSelect) {
                        modelSelect.value = data.active_model;
                    }
                } catch (err) {
                    if (!isSending) document.getElementById('status-state').textContent = 'OFFLINE';
                }
            }
            loadStatus();
            setInterval(loadStatus, 4000);
            loadModelSelector();

            // Model selector (header row 2): populated from the real catalog,
            // changes call the same set_active() path the /model command uses.
            async function loadModelSelector() {
                const select = document.getElementById('status-model-select');
                try {
                    const resp = await fetch('/api/models');
                    const data = await resp.json();
                    select.innerHTML = '';
                    (data.models || []).forEach(m => {
                        const opt = document.createElement('option');
                        opt.value = m.model_string;
                        opt.textContent = m.display_name || m.model_string;
                        select.appendChild(opt);
                    });
                    if (data.active_model) select.value = data.active_model;
                } catch (err) {
                    select.innerHTML = '<option>--</option>';
                }
            }
            document.getElementById('status-model-select').addEventListener('change', async (e) => {
                const newModel = e.target.value;
                try {
                    await fetch('/api/models', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ model: newModel }),
                    });
                    appendLog(`[model switched to ${newModel}]`);
                } catch (err) {
                    appendLog(`[failed to switch model: ${err}]`);
                }
            });

            // Sending animation: a single dot that bounces 1 -> 2 -> 3 -> 2 -> 1
            // in the STATUS field while waiting for a response, per Elton's spec.
            function startSendingAnimation() {
                isSending = true;
                const el = document.getElementById('status-state');
                const frames = ['.', '..', '...', '..'];
                let i = 0;
                el.textContent = frames[0];
                sendingAnimTimer = setInterval(() => {
                    i = (i + 1) % frames.length;
                    el.textContent = frames[i];
                }, 400);
            }

            function stopSendingAnimation() {
                isSending = false;
                if (sendingAnimTimer) {
                    clearInterval(sendingAnimTimer);
                    sendingAnimTimer = null;
                }
                document.getElementById('status-state').textContent = 'READY';
            }

            // File browser: address bar lets the user jump to ANY absolute
            // path the process can read -- internal storage, SD card,
            // anywhere -- not just where clicking through folders can reach.
            const filePathInput = document.getElementById('file-path-input');
            const fileGoBtn = document.getElementById('file-go-btn');
            fileGoBtn.addEventListener('click', () => {
                const p = filePathInput.value.trim();
                if (p) loadFiles(p);
            });
            filePathInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    fileGoBtn.click();
                }
            });
            loadQuickjumps();

            // Fetched from the server, which resolves these from Elton's
            // actual env_file.json (INTERNAL_STORAGE, SD_CARD, etc.) via
            // get_env_path() -- never hardcoded here.
            async function loadQuickjumps() {
                const container = document.getElementById('file-quickjumps');
                try {
                    const resp = await fetch('/api/files/quickjumps');
                    const data = await resp.json();
                    container.innerHTML = '';
                    (data.quickjumps || []).forEach(jump => {
                        const btn = document.createElement('button');
                        btn.textContent = jump.label;
                        btn.title = jump.path;
                        btn.addEventListener('click', () => loadFiles(jump.path));
                        container.appendChild(btn);
                    });
                    if (!data.quickjumps || data.quickjumps.length === 0) {
                        container.innerHTML = '<em>No quick-jump paths resolved from env_file.json</em>';
                    }
                } catch (err) {
                    container.innerHTML = '<em>Failed to load quick jumps</em>';
                }
            }

            // --- Jobs Tab ---
            // Direct UI <-> Flask round trip. Starting/stopping a job here
            // never goes through the chat/AI at all -- the agent only
            // learns a job is active on its *next* turn, via the server-
            // side ctx["_active_job_doc"] this endpoint sets.
            async function loadJobs() {
                const listEl = document.getElementById('job-list');
                try {
                    const resp = await fetch('/api/jobs');
                    const data = await resp.json();
                    renderJobs(data.jobs || [], data.active || null);
                } catch (err) {
                    listEl.innerHTML = `<em>Failed to load jobs: ${err}</em>`;
                }
            }

            function renderJobs(jobList, activeName) {
                const listEl = document.getElementById('job-list');
                const badge = document.getElementById('job-active-badge');
                const stopBtn = document.getElementById('job-stop-btn');

                badge.textContent = activeName ? ('Active job: ' + activeName) : 'No active job';
                stopBtn.style.display = activeName ? 'inline-block' : 'none';

                listEl.innerHTML = '';
                if (jobList.length === 0) {
                    listEl.innerHTML = '<em>No pending jobs in jobs/. Create one with JobMaker.py.</em>';
                    return;
                }
                jobList.forEach(job => {
                    const row = document.createElement('div');
                    row.className = 'job-row' + (job.active ? ' is-active' : '');

                    const info = document.createElement('div');
                    info.className = 'job-info';
                    const nameEl = document.createElement('div');
                    nameEl.className = 'job-name';
                    nameEl.textContent = job.job_name;
                    const goalEl = document.createElement('div');
                    goalEl.className = 'job-goal';
                    goalEl.textContent = job.goal || '';
                    const progEl = document.createElement('div');
                    progEl.className = 'job-progress';
                    progEl.textContent = job.completed_count + ' / ' + job.task_count + ' tasks done';
                    info.appendChild(nameEl);
                    info.appendChild(goalEl);
                    info.appendChild(progEl);

                    const btn = document.createElement('button');
                    btn.className = 'job-start-btn';
                    if (job.active) {
                        btn.textContent = 'Active';
                        btn.disabled = true;
                    } else {
                        btn.textContent = 'Start';
                        btn.addEventListener('click', () => startJob(job.job_name));
                    }

                    row.appendChild(info);
                    row.appendChild(btn);
                    listEl.appendChild(row);
                });
            }

            async function startJob(name) {
                try {
                    const resp = await fetch('/api/jobs/start', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ name }),
                    });
                    const data = await resp.json();
                    if (!resp.ok) {
                        alert(data.error || 'Failed to start job.');
                        return;
                    }
                    loadJobs();
                } catch (err) {
                    alert('Failed to start job: ' + err);
                }
            }

            async function stopJob() {
                try {
                    await fetch('/api/jobs/stop', { method: 'POST' });
                } finally {
                    loadJobs();
                }
            }

            document.getElementById('job-stop-btn').addEventListener('click', stopJob);

            // --- Notes Tab ---
            // Autosaves ~1.5s after the user stops typing (debounced, not
            // on every keystroke) to a plain-text file under notes/.
            let notesLoaded = false;
            let notesSaveTimer = null;

            async function loadNotes() {
                if (notesLoaded) return; // don't clobber in-progress edits on repeat opens
                const statusEl = document.getElementById('notes-status');
                const ta = document.getElementById('notes-textarea');
                try {
                    const resp = await fetch('/api/notes');
                    const data = await resp.json();
                    ta.value = data.text || '';
                    notesLoaded = true;
                    statusEl.textContent = 'Saved';
                } catch (err) {
                    statusEl.textContent = 'Failed to load notes: ' + err;
                }
            }

            function scheduleNotesSave() {
                const statusEl = document.getElementById('notes-status');
                statusEl.textContent = 'Typing...';
                if (notesSaveTimer) clearTimeout(notesSaveTimer);
                notesSaveTimer = setTimeout(saveNotes, 1500);
            }

            async function saveNotes() {
                const statusEl = document.getElementById('notes-status');
                const ta = document.getElementById('notes-textarea');
                statusEl.textContent = 'Saving...';
                try {
                    const resp = await fetch('/api/notes', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ text: ta.value }),
                    });
                    statusEl.textContent = resp.ok ? 'Saved' : 'Save failed';
                } catch (err) {
                    statusEl.textContent = 'Save failed: ' + err;
                }
            }

            document.getElementById('notes-textarea').addEventListener('input', scheduleNotesSave);

            // Tab Switching Logic
            const tabButtons = document.querySelectorAll('.tab-button');
            const tabPanels = document.querySelectorAll('.tab-panel');

            tabButtons.forEach(button => {
                button.addEventListener('click', () => {
                    tabButtons.forEach(btn => btn.classList.remove('active'));
                    tabPanels.forEach(panel => panel.classList.remove('active'));

                    button.classList.add('active');
                    const targetId = button.getAttribute('data-tab');
                    document.getElementById(targetId).classList.add('active');
                });
            });

        });
    </script>
</body>
</html>



"""


class WebAgentTerminal:
    """
    Class-based Flask wrapper around the NewAgent browser terminal.

    Groundwork only (per Elton's instruction -- "lay the groundwork for now,
    we'll come back to it later"):

    - /api/exec is REAL and working: it reuses actions.do_exec(), the exact
      same async subprocess engine agent.py's <exec> action tag already
      uses and that is already tested elsewhere in this project. No second
      shell-execution implementation was written for this.
    - The LLM chat engine (KeyRegistry, ModelRegistry, RestPrompter) is
      constructed in __init__ so it is ready to use, sharing the same
      config/keys/models files agent.py reads -- but /api/chat is an
      intentional stub (501 Not Implemented) rather than a guessed-at chat
      loop, since that behavior was explicitly deferred.
    - State (cwd, shell env) is held on the instance, single-session --
      there is no per-browser-tab isolation yet. That is a known, accepted
      groundwork limitation, not an oversight: a second client connecting
      would share the same cwd/env as the first. Revisit if/when this needs
      to support more than one concurrent user.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 5001):
        self.host = host
        self.port = port
        self.app = Flask(__name__)

        # Single-session state (see class docstring -- known groundwork
        # limitation, not multi-user safe yet).
        self._cwd = str(BASE_DIR)
        self._shell_env = None
        jobs.ensure_job_dirs(JOBS_DIR)
        jobs.cleanup_old_completed_jobs(JOBS_DIR)
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        self._active_job_path = None
        self._active_job_doc = None

        # Config -- shared with agent.py, not a separate config file.
        self.config = config_lib.init_config(CONFIG_PATH)

        # Chat/LLM engine -- reuses the exact same classes agent.py uses.
        # Sync keys FROM the canonical env_file.json before constructing
        # KeyRegistry -- agent.py already does this at bootstrap; webagent.py
        # was missing it entirely, meaning it could run on a stale/incomplete
        # keys.bejson instead of the real source of truth. keys.bejson is a
        # derived, regenerable cache -- never hand-maintained, never the
        # actual source.
        rest.sync_keys_from_env_file(KEYS_PATH, Path(self.config.get("env_file_path", "")))
        self.key_reg = rest.KeyRegistry(KEYS_PATH, STATE_PATH)
        self.model_reg = rest.ModelRegistry(MODELS_PATH)
        self.rest_prompter = rest.RestPrompter(
            self.key_reg, self.model_reg, MODEL_CATALOG_PATH, self.config, logs_dir=LOGS_DIR
        )

        # Agent turn-loop state -- mirrors agent.py's own main() state, since
        # /api/chat runs the real NewAgent turn loop (assemble bubble -> call
        # engine -> parse action tags -> run_action_queue), not a raw shell
        # passthrough. Single-session (see class docstring).
        self.history: list[dict] = []
        self.turn_count = 0
        self.trigger_cooldowns: dict[str, float] = {}
        self.key_call_counts: dict[str, int] = {}
        self.stats = tui.SessionStats(key_total=len(self.key_reg.keys), engine="rest")
        for d in (CONTEXT_DIR, BACKUPS_DIR, LOGS_DIR):
            d.mkdir(parents=True, exist_ok=True)
        bubble.init_context_bubble(CONTEXT_DIR, CONFIG_DIR, LOGS_DIR)

        self._register_routes()

    def _register_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return render_template_string(HTML)

        @app.route("/api/exec", methods=["POST"])
        def api_exec():
            data = request.get_json(force=True, silent=True) or {}
            command = (data.get("command") or "").strip()
            attachments = data.get("attachments") or []
            if not command:
                return jsonify({"output": "", "cwd": self._cwd, "exit_code": 0})

            code, out, new_cwd, new_env = asyncio.run(
                actions.do_exec(
                    command,
                    self._cwd,
                    timeout=self.config.get("exec_timeout_seconds", 60),
                    shell_env=self._shell_env,
                )
            )
            self._cwd = new_cwd
            if new_env is not None:
                self._shell_env = new_env
            self.stats.execs += 1

            # Groundwork only: attachments are acknowledged and logged here,
            # not fed into any deeper context yet -- there is no chat/context
            # assembly built to feed them into (see /api/chat below). This
            # proves the selection -> send -> uncheck round-trip end to end
            # without pretending attachment content is being used for
            # anything yet.
            if attachments:
                names = ", ".join(Path(a).name for a in attachments)
                out = f"[Attached {len(attachments)} file(s): {names}]\n" + out

            return jsonify({
                "output": out,
                "cwd": self._cwd,
                "exit_code": code,
                "attachments_received": len(attachments),
            })

        @app.route("/api/config", methods=["GET"])
        def api_config_get():
            desc_map = {name: desc for name, _, desc in config_lib.DEFAULT_CONFIG}
            rows = []
            for name, value in self.config.items():
                rows.append({
                    "name": name,
                    "value": value,
                    "type": type(value).__name__,
                    "description": desc_map.get(name, ""),
                })
            return jsonify({"config": rows})

        @app.route("/api/config", methods=["POST"])
        def api_config_set():
            data = request.get_json(force=True, silent=True) or {}
            name = data.get("name")
            value = data.get("value")
            if name is None or name not in self.config:
                return jsonify({"error": f"unknown config key: {name}"}), 400

            existing = self.config[name]
            try:
                if isinstance(existing, bool):
                    value = bool(value)
                elif isinstance(existing, int):
                    value = int(value)
                elif isinstance(existing, float):
                    value = float(value)
                else:
                    value = str(value)
            except (TypeError, ValueError):
                return jsonify({"error": f"could not set {name}: value does not match expected type {type(existing).__name__}"}), 400

            self.config[name] = value
            config_lib.save_config(CONFIG_PATH, self.config)
            return jsonify({"name": name, "value": value, "saved": True})

        @app.route("/api/files/quickjumps", methods=["GET"])
        def api_files_quickjumps():
            # Driven by Elton's actual env_file.json values (via source_env()
            # + get_env_path()), not hardcoded guesses like /storage/emulated/0
            # or /sdcard -- those were wrong on principle even when they
            # happened to be right on a given device. Only surfaced if the
            # resolved path actually exists, so a dead/unset env var doesn't
            # produce a button that goes nowhere.
            candidates = [
                ("Internal Storage", get_env_path("INTERNAL_STORAGE", "")),
                ("SD Card", get_env_path("SD_CARD", "")),
                ("Project Root", get_env_path("PROJECT_ROOT", "")),
                ("Home", str(Path.home())),
                ("/ (filesystem root)", "/"),
            ]
            jumps = []
            seen_paths = set()
            for label, path in candidates:
                if not path:
                    continue
                p = Path(path)
                if p.is_dir() and str(p) not in seen_paths:
                    jumps.append({"label": label, "path": str(p)})
                    seen_paths.add(str(p))
            return jsonify({"quickjumps": jumps})

        @app.route("/api/files/browse", methods=["GET"])
        def api_files_browse():
            raw_path = request.args.get("path") or str(BASE_DIR)
            try:
                target = Path(raw_path).expanduser().resolve()
            except Exception:
                return jsonify({"error": f"invalid path: {raw_path}"}), 400

            if not target.exists():
                return jsonify({"error": f"path does not exist: {target}"}), 404
            if not target.is_dir():
                return jsonify({"error": f"not a directory: {target}"}), 400

            entries = []
            try:
                for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                    try:
                        is_dir = child.is_dir()
                        size = None if is_dir else child.stat().st_size
                        entries.append({
                            "name": child.name,
                            "path": str(child),
                            "is_dir": is_dir,
                            "size": size,
                        })
                    except OSError:
                        continue  # unreadable entry (permission, broken symlink) -- skip, don't fail the whole listing
            except PermissionError:
                return jsonify({"error": f"permission denied: {target}"}), 403

            parent = str(target.parent) if target.parent != target else None
            return jsonify({"path": str(target), "parent": parent, "entries": entries})

        @app.route("/api/chat", methods=["POST"])
        def api_chat():
            """
            Runs an actual NewAgent turn -- the same loop agent.py's own
            main() runs (assemble Context Bubble -> build system prompt ->
            call the REST engine -> parse <exec>/<write_file>/etc action
            tags from the response -> execute them via run_action_queue,
            reusing the exact same do_exec()-backed pipeline /api/exec
            uses) -- not a raw bash passthrough. The model decides what,
            if anything, to run; the human types a prompt, not a command.
            """
            data = request.get_json(force=True, silent=True) or {}
            user_msg = (data.get("message") or "").strip()
            attachments = data.get("attachments") or []
            if not user_msg:
                return jsonify({"error": "empty message"}), 400

            # Attachments are read-only reference pointers -- only the paths
            # are surfaced to the model, never file contents. The model can
            # choose to inspect them itself (e.g. via its own <exec>/
            # bejson_fields tags) if it decides to; this endpoint never reads
            # or alters attachment content on its own.
            if attachments:
                names = "\n".join(f"  - {a}" for a in attachments)
                user_msg = f"{user_msg}\n\n[Attached reference file(s) -- for you to study if relevant, do not alter:\n{names}\n]"

            ts = datetime.now().strftime("%H:%M:%S")
            self.history.append({"role": "user", "content": user_msg, "_ts": ts})

            ctx = {
                "_cwd": self._cwd,
                "_shell_env": self._shell_env,
                "config": self.config,
                "_backups_dir": BACKUPS_DIR,
                "_config_dir": CONFIG_DIR,
                "_jobs_dir": JOBS_DIR,
                "_active_job_path": self._active_job_path,
                "_active_job_doc": self._active_job_doc,
                "_continue_requested": False,
                "stats": self.stats,
                "key_call_counts": self.key_call_counts,
            }

            turn_log = []  # ordered {"type": "text"|"action", ...} entries for this HTTP call
            iterations = 0

            while iterations < MAX_AUTO_CONTINUE:
                iterations += 1

                try:
                    bubble_result = bubble.assemble_bubble(
                        CONTEXT_DIR, CONFIG_DIR, user_msg,
                        turn=self.turn_count + 1, cooldown_state=self.trigger_cooldowns,
                        cwd=ctx["_cwd"], env_file_path=self.config.get("env_file_path", ""),
                    )
                except errors.ContextInjectionError:
                    bubble_result = bubble.build_minimal_bubble(CONTEXT_DIR, CONFIG_DIR)

                system_instruction = actions.build_system_prompt(
                    ctx["_cwd"], bubble_result["text"],
                    active_job=jobs.build_job_context_block(ctx.get("_active_job_doc")),
                )

                try:
                    response_text, usage = self.rest_prompter.prompt(self.history, system_instruction)
                except errors.NewAgentFatalError as exc:
                    return jsonify({"error": f"[FATAL] {exc}", "turn_log": turn_log}), 500
                except Exception as exc:
                    return jsonify({"error": str(exc), "turn_log": turn_log}), 502

                self.turn_count += 1
                self.stats.turns += 1
                self.history.append({"role": "model", "content": response_text, "_ts": ts})
                turn_log.append({"type": "text", "content": response_text})

                parsed_actions = actions.parse_actions(response_text)
                if not parsed_actions:
                    break  # turn genuinely complete -- model didn't request any actions

                results = asyncio.run(actions.run_action_queue(parsed_actions, ctx))
                self._active_job_path = ctx.get("_active_job_path")
                self._active_job_doc = ctx.get("_active_job_doc")
                for r in results:
                    turn_log.append({
                        "type": "action",
                        "action_type": r.action_type,
                        "source": r.source,
                        "output": r.output,
                        "exit_code": r.exit_code,
                    })

                payload = actions.assemble_results_payload(results)
                self.history.append({"role": "user", "content": payload, "_ts": ts})

                if not self.config.get("auto_continue_enabled", True):
                    break  # one action round only -- human sends again to continue

            # Sync cwd/shell_env back from ctx -- an <exec> tag may have
            # changed them, and /api/exec's raw shell should see the same
            # state the agent just left things in, and vice versa.
            self._cwd = ctx["_cwd"]
            if ctx.get("_shell_env") is not None:
                self._shell_env = ctx["_shell_env"]

            return jsonify({
                "turn_log": turn_log,
                "cwd": self._cwd,
                "iterations": iterations,
                "hit_iteration_cap": iterations >= MAX_AUTO_CONTINUE,
            })

        @app.route("/api/models", methods=["GET"])
        def api_models_get():
            catalog_rows = rest.load_model_catalog(MODEL_CATALOG_PATH)
            models = [
                {"model_string": r.get("model_string"), "display_name": r.get("display_name") or r.get("model_string")}
                for r in catalog_rows if r.get("model_string")
            ]
            return jsonify({"models": models, "active_model": self.model_reg.active})

        @app.route("/api/models", methods=["POST"])
        def api_models_set():
            data = request.get_json(force=True, silent=True) or {}
            model_string = (data.get("model") or "").strip()
            if not model_string:
                return jsonify({"error": "missing 'model'"}), 400
            self.model_reg.set_active(model_string)
            return jsonify({"active_model": self.model_reg.active})

        @app.route("/api/status")
        def api_status():
            keys_available = sum(1 for k in self.key_reg.keys if self.key_reg._is_available(k))
            return jsonify({
                "version": VERSION,
                "cwd": self._cwd,
                "active_model": self.model_reg.active,
                "key_count": len(self.key_reg.keys),
                "keys_available": keys_available,
                "engine": self.stats.engine,
                "turns": self.stats.turns,
                "execs": self.stats.execs,
            })

        # --- Jobs Tab ---
        # UI-driven, not chat/AI-driven: the agent is never told what's in
        # jobs/ and never asked to pick one. Listing and starting a job here
        # is pure client <-> Flask, same as the Files/Config tabs -- the
        # active job only enters the AI's context (build_system_prompt's
        # active_job param, wired in api_chat below) once this endpoint has
        # actually set it.
        @app.route("/api/jobs", methods=["GET"])
        def api_jobs_list():
            job_list = jobs.scan_jobs(JOBS_DIR)
            active_name = Path(self._active_job_path).stem if self._active_job_path else None
            for j in job_list:
                j["active"] = (j["job_name"] == active_name)
            return jsonify({"jobs": job_list, "active": active_name})

        @app.route("/api/jobs/start", methods=["POST"])
        def api_jobs_start():
            data = request.get_json(force=True, silent=True) or {}
            name = (data.get("name") or "").strip()
            if not name:
                return jsonify({"error": "missing 'name'"}), 400
            picked = jobs.get_job_path(JOBS_DIR, name)
            if not picked:
                return jsonify({"error": f"No job named '{name}' found in jobs/."}), 404
            doc = jobs.load_job(picked)
            if not doc:
                return jsonify({"error": f"Could not load {picked.name} as BEJSON."}), 500
            self._active_job_path = picked
            self._active_job_doc = doc
            return jsonify({"ok": True, "active": picked.stem})

        @app.route("/api/jobs/stop", methods=["POST"])
        def api_jobs_stop():
            self._active_job_path = None
            self._active_job_doc = None
            return jsonify({"ok": True, "active": None})

        # --- Notes Tab ---
        # A single persistent free-text note, autosaved from the client a
        # couple seconds after the user stops typing. Deliberately dumb --
        # plain text on disk, not BEJSON, since there's no tabular structure
        # here to justify Field Map Cache overhead for one text blob.
        @app.route("/api/notes", methods=["GET"])
        def api_notes_get():
            text = NOTES_FILE.read_text(encoding="utf-8") if NOTES_FILE.is_file() else ""
            return jsonify({"text": text})

        @app.route("/api/notes", methods=["POST"])
        def api_notes_save():
            data = request.get_json(force=True, silent=True) or {}
            text = data.get("text", "")
            NOTES_DIR.mkdir(parents=True, exist_ok=True)
            tmp = NOTES_FILE.with_suffix(".tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(NOTES_FILE)
            return jsonify({"ok": True})

        # --- Amnesia / Rebirth ---
        # Amnesia: compresses self.history (the live in-memory turns
        # actually sent to the model) to a single dense recap, then always
        # wipes self.history. Whether the recap is fed straight back in
        # ("rebirth") right away, or left waiting on disk for a manual
        # /api/rebirth call, is the auto_amnesia_memory_retrieval config
        # toggle -- same behavior/naming as agent.py's /amnesia + /rebirth.
        # Never touches the on-disk transcript logger -- nothing in logs/
        # is deleted, only the agent's live prompting memory. Fails closed:
        # a failed/empty compression call leaves self.history untouched.
        # Flask's dev server is sync/single-request here, so no event-loop
        # concern like agent.py's asyncio.to_thread wrapper -- this call is
        # just made directly.
        @app.route("/api/amnesia", methods=["POST"])
        def api_amnesia():
            if not self.history:
                return jsonify({"ok": False, "error": "Nothing to compress -- history is already empty."})
            recap = bubble.run_full_session_compression(self.history, self.rest_prompter)
            if not recap:
                return jsonify({"ok": False, "error": "Compression call failed or returned nothing -- history left untouched."})
            bubble.save_amnesia_recap(CONTEXT_DIR, recap)
            auto_rebirth = self.config.get("auto_amnesia_memory_retrieval", True)
            if auto_rebirth:
                bubble.seed_history_with_recap(self.history, recap)
                return jsonify({"ok": True, "reborn": True, "recap_chars": len(recap)})
            else:
                self.history.clear()
                return jsonify({"ok": True, "reborn": False, "recap_chars": len(recap)})

        @app.route("/api/rebirth", methods=["POST"])
        def api_rebirth():
            recap = bubble.load_amnesia_recap(CONTEXT_DIR)
            if not recap:
                return jsonify({"ok": False, "error": "No compressed recap available -- run Amnesia first."})
            bubble.seed_history_with_recap(self.history, recap)
            return jsonify({"ok": True, "recap_chars": len(recap)})

    def run(self, debug: bool = False) -> None:
        self.app.run(host=self.host, port=self.port, debug=debug)


if __name__ == "__main__":
    WebAgentTerminal().run()
