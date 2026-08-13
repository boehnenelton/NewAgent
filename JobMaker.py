"""
Name:           JobMaker.py
Family:         NewAgent
Description:    Offline job creation system for NewAgent's Job Creation System.
                Single, isolated Flask file -- name a job, set a goal, add/
                remove tasks in a scrollable list, and save it as a BEJSON
                104a job schema in jobs/. A combo box at the top switches
                between previously saved jobs in that folder. Jobs saved
                here are picked up by agent.py/webagent.py at startup
                (lib_bejson_newagent_jobs.scan_jobs) and can be started
                explicitly via /jobstart.
Version:        1.0.0
Date:           2026-08-08
Author:         Elton Boehnen — eltonboehnen@gmail.com
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  d4a1f8c2-9b3e-4d6a-8f0c-2e5b7a9c1d43
"""

import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, Response

VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent
JOBS_DIR = BASE_DIR / "jobs"

# Reuse the same Core BEJSON library the rest of NewAgent uses -- no second
# read/write/field-map implementation.
sys.path.insert(0, str(BASE_DIR / "lib"))
from lib_bejson_Core_bejson_core import (
    bejson_core_load_file,
    bejson_core_atomic_write,
    bejson_core_get_field_map,
)

app = Flask(__name__)

_JOB_FIELDS = [
    {"name": "task_id", "type": "string"},
    {"name": "task_order", "type": "integer"},
    {"name": "task_name", "type": "string"},
    {"name": "task_description", "type": "string"},
    {"name": "task_completed", "type": "boolean"},
    {"name": "audit_enabled", "type": "boolean"},
    {"name": "audit_passed", "type": "boolean"},
    {"name": "audit_fail_reason", "type": "string"},
]


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", title.strip()).strip("_").lower()
    return slug or "untitled_job"


def _job_path(name: str) -> Path:
    return JOBS_DIR / f"{_slugify(name)}.bejson"


def _list_job_names() -> list[str]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(f.stem for f in JOBS_DIR.glob("*.bejson") if f.is_file())


def _doc_to_job_dict(doc: dict) -> dict:
    """Convert a loaded BEJSON 104a job doc into the flat shape the UI/JS uses,
    resolving every column strictly through the Field Map Cache -- no
    positional/index-based access, per the BEJSON Core Mandate."""
    fmap = bejson_core_get_field_map(doc)
    tasks = []
    for row in doc.get("Values", []):
        def get(field, default=""):
            idx = fmap.get(field)
            return row[idx] if idx is not None and len(row) > idx else default
        tasks.append({
            "task_id": get("task_id", ""),
            "task_order": get("task_order", 0),
            "task_name": get("task_name", ""),
            "task_description": get("task_description", ""),
            "task_completed": bool(get("task_completed", False)),
            "audit_enabled": bool(get("audit_enabled", False)),
            "audit_passed": bool(get("audit_passed", False)),
            "audit_fail_reason": get("audit_fail_reason", ""),
        })
    tasks.sort(key=lambda t: t["task_order"])
    return {
        "goal": doc.get("Job_Goal", ""),
        "complete": bool(doc.get("Job_Complete", False)),
        "creation_date": doc.get("Creation_Date", ""),
        "completion_date": doc.get("Completion_Date", ""),
        "tasks": tasks,
    }


def _build_job_doc(name: str, goal: str, tasks: list[dict], existing: dict | None) -> dict:
    now = datetime.now().strftime("%Y-%m-%d")
    creation_date = (existing or {}).get("Creation_Date") or now
    values = []
    for i, t in enumerate(tasks):
        tid = (t.get("task_id") or "").strip() or str(uuid.uuid4())
        values.append([
            tid,
            int(t.get("task_order", i + 1)),
            str(t.get("task_name", "")),
            str(t.get("task_description", "")),
            bool(t.get("task_completed", False)),
            bool(t.get("audit_enabled", False)),
            bool(t.get("audit_passed", False)),
            str(t.get("audit_fail_reason", "")),
        ])
    all_done = bool(values) and all(v[4] is True for v in values)
    return {
        "Format": "BEJSON",
        "Format_Version": "104a",
        "Format_Creator": "Elton Boehnen",
        "Schema_Name": "Job Schema",
        "Schema_Version": "1.0",
        "Schema_Description": "Custom job schema for the NewAgent task creation and tracking system, managing individual task states and optional auditing.",
        "Job_Goal": goal,
        "Job_Complete": all_done,
        "Creation_Date": creation_date,
        "Completion_Date": (datetime.now().strftime("%Y-%m-%d") if all_done else ""),
        "Records_Type": ["JobTask"],
        "Fields": _JOB_FIELDS,
        "Values": values,
    }


# ── API ───────────────────────────────────────────────────────────────────

@app.route("/api/jobs", methods=["GET"])
def api_list_jobs():
    return jsonify({"jobs": _list_job_names()})


@app.route("/api/jobs/<name>", methods=["GET"])
def api_get_job(name):
    path = _job_path(name)
    if not path.is_file():
        return jsonify({"error": f"No job named '{name}'."}), 404
    doc = bejson_core_load_file(str(path))
    if not isinstance(doc, dict):
        return jsonify({"error": f"Could not load {path.name} as BEJSON."}), 500
    return jsonify(_doc_to_job_dict(doc))


@app.route("/api/jobs", methods=["POST"])
def api_save_job():
    body = request.get_json(force=True, silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Job name is required."}), 400
    goal = body.get("goal", "")
    tasks = body.get("tasks", [])
    if not isinstance(tasks, list):
        return jsonify({"error": "tasks must be a list."}), 400

    path = _job_path(name)
    existing = bejson_core_load_file(str(path)) if path.is_file() else None
    doc = _build_job_doc(name, goal, tasks, existing)

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    if not bejson_core_atomic_write(str(path), doc):
        return jsonify({"error": f"Failed to save {path.name}."}), 500
    return jsonify({"ok": True, "name": _slugify(name), "job": _doc_to_job_dict(doc)})


# ── UI ────────────────────────────────────────────────────────────────────

_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JobMaker — NewAgent</title>
<style>
  @font-face {{ font-family: 'Inter'; src: local('Inter'); }}
  :root {{
    --bg: #FFFFFF;
    --fg: #000000;
    --red: #DE2626;
    --border: #000000;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--fg);
    font-family: 'Inter', system-ui, sans-serif;
    min-height: 100vh;
  }}
  header {{
    background: #000000; color: #FFFFFF;
    padding: 16px 20px;
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 10px;
  }}
  header h1 {{ font-size: 1.1rem; margin: 0; letter-spacing: 0.02em; }}
  header .sub {{ color: #CCCCCC; font-size: 0.8rem; }}
  main {{ max-width: 720px; margin: 0 auto; padding: 20px 16px 60px; }}
  label {{ display: block; font-weight: 600; margin: 18px 0 6px; }}
  input[type=text], textarea, select {{
    width: 100%; background: #FFFFFF; color: #000000;
    border: 1px solid var(--border); border-radius: 4px;
    padding: 10px; font-family: inherit; font-size: 1rem;
  }}
  textarea {{ resize: vertical; min-height: 60px; }}
  .job-picker {{ display: flex; gap: 8px; align-items: center; }}
  .job-picker select {{ flex: 1; }}
  .task-list {{
    max-height: 360px; overflow-y: auto;
    border: 1px solid var(--border); border-radius: 6px;
    padding: 8px; margin-top: 8px; background: #FFFFFF;
  }}
  .task-row {{
    display: flex; gap: 8px; align-items: flex-start;
    padding: 8px; border-bottom: 1px solid #DDDDDD;
  }}
  .task-row:last-child {{ border-bottom: none; }}
  .task-row .fields {{ flex: 1; display: flex; flex-direction: column; gap: 6px; }}
  .task-row input[type=checkbox] {{ margin-top: 12px; width: 18px; height: 18px; }}
  .del-btn {{
    background: transparent; color: #000000; border: 1px solid var(--border);
    border-radius: 4px; width: 32px; height: 32px; font-weight: bold;
    cursor: pointer; flex-shrink: 0;
  }}
  .del-btn:hover {{ background: var(--red); color: #FFFFFF; border-color: var(--red); }}
  button.action {{
    background: #FFFFFF; color: #000000; border: 1px solid var(--border);
    border-radius: 4px; padding: 10px 16px; font-weight: 600;
    cursor: pointer; font-family: inherit;
  }}
  button.action:hover {{ background: var(--red); color: #FFFFFF; border-color: var(--red); }}
  .row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-top: 14px; }}
  .status {{ margin-top: 10px; font-size: 0.9rem; min-height: 1.2em; }}
  .status.ok {{ color: #0a7a0a; }}
  .status.err {{ color: var(--red); }}
  footer {{
    text-align: center; font-size: 0.75rem; color: #555555;
    padding: 20px 16px 30px;
  }}
  code {{ font-family: 'Source Code Pro', monospace; }}
</style>
</head>
<body>
<header>
  <h1>JobMaker</h1>
  <span class="sub">NewAgent Job Creation System · v{version}</span>
</header>
<main>
  <label for="jobPicker">Existing Jobs</label>
  <div class="job-picker">
    <select id="jobPicker"><option value="">-- New Job --</option></select>
    <button class="action" id="loadBtn">Load</button>
  </div>

  <label for="jobName">Job Name</label>
  <input type="text" id="jobName" placeholder="e.g. Refactor Chunker CLI">

  <label for="jobGoal">Goal</label>
  <textarea id="jobGoal" placeholder="What should the agent accomplish?"></textarea>

  <label>Tasks</label>
  <div class="task-list" id="taskList"></div>

  <div class="row">
    <button class="action" id="addTaskBtn">+ Add Task</button>
    <button class="action" id="saveBtn">Save</button>
  </div>
  <div class="status" id="statusLine"></div>
</main>
<footer>
  Elton Boehnen · eltonboehnen@gmail.com · boehnenelton2024.pages.dev ·
  github.com/boehnenelton · JobMaker v{version}
</footer>

<script>
let tasks = [];

function renderTasks() {{
  const el = document.getElementById('taskList');
  el.innerHTML = '';
  if (tasks.length === 0) {{
    el.innerHTML = '<div style="padding:10px;color:#777;">No tasks yet -- click "+ Add Task".</div>';
    return;
  }}
  tasks.forEach((t, i) => {{
    const row = document.createElement('div');
    row.className = 'task-row';
    row.innerHTML = `
      <input type="checkbox" data-i="${{i}}" class="doneCb" ${{t.task_completed ? 'checked' : ''}} title="task_completed">
      <div class="fields">
        <input type="text" class="taskName" data-i="${{i}}" placeholder="Task name" value="${{t.task_name.replace(/"/g,'&quot;')}}">
        <textarea class="taskDesc" data-i="${{i}}" placeholder="Task description">${{t.task_description}}</textarea>
      </div>
      <button class="del-btn" data-i="${{i}}" title="Delete task">×</button>
    `;
    el.appendChild(row);
  }});
  el.querySelectorAll('.del-btn').forEach(b => b.addEventListener('click', e => {{
    tasks.splice(parseInt(e.target.dataset.i), 1);
    renderTasks();
  }}));
  el.querySelectorAll('.taskName').forEach(inp => inp.addEventListener('input', e => {{
    tasks[parseInt(e.target.dataset.i)].task_name = e.target.value;
  }}));
  el.querySelectorAll('.taskDesc').forEach(inp => inp.addEventListener('input', e => {{
    tasks[parseInt(e.target.dataset.i)].task_description = e.target.value;
  }}));
  el.querySelectorAll('.doneCb').forEach(cb => cb.addEventListener('change', e => {{
    tasks[parseInt(e.target.dataset.i)].task_completed = e.target.checked;
  }}));
}}

function addTask() {{
  tasks.push({{
    task_id: '', task_order: tasks.length + 1, task_name: '', task_description: '',
    task_completed: false, audit_enabled: false, audit_passed: false, audit_fail_reason: ''
  }});
  renderTasks();
}}

function setStatus(msg, ok) {{
  const s = document.getElementById('statusLine');
  s.textContent = msg;
  s.className = 'status ' + (ok ? 'ok' : 'err');
}}

async function refreshJobList(selectName) {{
  const res = await fetch('/api/jobs');
  const data = await res.json();
  const picker = document.getElementById('jobPicker');
  picker.innerHTML = '<option value="">-- New Job --</option>';
  data.jobs.forEach(name => {{
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    picker.appendChild(opt);
  }});
  if (selectName) picker.value = selectName;
}}

async function loadSelectedJob() {{
  const name = document.getElementById('jobPicker').value;
  if (!name) {{
    document.getElementById('jobName').value = '';
    document.getElementById('jobGoal').value = '';
    tasks = [];
    renderTasks();
    setStatus('', true);
    return;
  }}
  const res = await fetch('/api/jobs/' + encodeURIComponent(name));
  if (!res.ok) {{ setStatus('Could not load job.', false); return; }}
  const data = await res.json();
  document.getElementById('jobName').value = name;
  document.getElementById('jobGoal').value = data.goal || '';
  tasks = data.tasks || [];
  renderTasks();
  setStatus('Loaded "' + name + '".', true);
}}

async function saveJob() {{
  const name = document.getElementById('jobName').value.trim();
  if (!name) {{ setStatus('Job name is required.', false); return; }}
  tasks.forEach((t, i) => t.task_order = i + 1);
  const payload = {{ name: name, goal: document.getElementById('jobGoal').value, tasks: tasks }};
  const res = await fetch('/api/jobs', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(payload)
  }});
  const data = await res.json();
  if (!res.ok) {{ setStatus(data.error || 'Save failed.', false); return; }}
  tasks = data.job.tasks;
  renderTasks();
  setStatus('Saved "' + data.name + '".', true);
  await refreshJobList(data.name);
}}

document.getElementById('addTaskBtn').addEventListener('click', addTask);
document.getElementById('saveBtn').addEventListener('click', saveJob);
document.getElementById('loadBtn').addEventListener('click', loadSelectedJob);
renderTasks();
refreshJobList();
</script>
</body>
</html>
"""


@app.route("/", methods=["GET"])
def index():
    return Response(_PAGE.format(version=VERSION), mimetype="text/html")


if __name__ == "__main__":
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"JobMaker v{VERSION} -- Elton Boehnen -- serving jobs/ at {JOBS_DIR}")
    app.run(host="0.0.0.0", port=5055, debug=False)
