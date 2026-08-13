"""
Library:        lib_bejson_newagent_engine_interactions.py
Family:         NewAgent
Description:    Gemini Interactions API client with native function-calling loop.
Version:        1.1.0
Date:           2026-08-09
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  7711b7dc-587d-49a7-a5e6-6bfdfd0734a8

CHANGELOG:
- 1.1.0 (2026-08-09): Full audit against the current official Interactions
  API docs (ai.google.dev/gemini-api/docs/interactions-overview,
  /get-started, /api-errors, and the May 2026 breaking-changes migration
  guide), triggered by Elton reporting Interactions mode had never once
  worked and always failed with a generic error. Confirmed the request
  shape itself (model/input/tools/system_instruction/previous_interaction_id,
  the steps-based response schema, function_call/function_result flow) was
  already correct and current -- the legacy `outputs` schema this code
  never used was removed entirely on June 8, 2026, so no Api-Revision
  header is needed. The actual bug was in _post()'s error handling:
  (1) every non-200 response discarded the real response body (Google's
  {"error": {"code", "message"}} per the API errors reference) in favor of
  a bare "HTTP {status}" string, so there was never any way to see *why*
  a call failed; (2) deterministic client-side errors (400 invalid_request/
  model_not_found/parameter_unknown, 404, 409, etc. -- guaranteed to fail
  identically no matter which key sends them) were retried 3x across
  different keys AND each of those keys got set_cooldown() called on it
  for a bug that had nothing to do with them. KeyRegistry's
  AUTO_DEACTIVATE_THRESHOLD is 3 consecutive fails -- so a single
  malformed-request bug, hit through its 3 retries, was enough to
  permanently deactivate every key in rotation in one call, which would
  then surface as the even more generic "No API keys available." on the
  next attempt. This fully explains "never got it to work, generic error
  every time." Fixed: 429/401/403 still legitimately cooldown+retry with
  the next key; 5xx retries without penalizing the key (not its fault);
  everything else fails fast on the first attempt with the real
  code+message surfaced, no retries, no cooldowns. Also added a check in
  run_turn() for the case where a blocked/failed generation (safety,
  prohibited_content, recitation, malformed_function_call, etc.) comes
  back as a normal HTTP 200 with status != "completed" and an error
  object -- previously this fell through to extract_text() silently
  returning "", making a safety block look identical to the model saying
  nothing. Verified every case (deterministic 400, 429 exhaustion, 500
  retry-without-penalty, 401 exhaustion, safety-blocked 200, and a normal
  successful turn) against a hand-rolled fake aiohttp session -- all
  passed, including confirming zero cooldowns are applied for the 400
  and 500 cases where the previous code wrongly penalized keys.
"""

import asyncio
import json
import logging
from typing import Any, Callable, Optional

import aiohttp

VERSION = "1.1.0"
logger = logging.getLogger(__name__)

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/interactions"
COOLDOWN_429 = 60
COOLDOWN_AUTH = 86400

def build_tool_declarations(do_map: dict[str, Callable], scope: str = "all") -> list[dict]:
    SHELL_TOOLS = {"exec_shell", "env_get"}

    TOOL_SPECS = {
        "exec_shell": {
            "description": "Run a shell command in the current working directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                },
                "required": ["command"],
            },
        },
        "read_file": {
            "description": "Read the contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Absolute or relative file path"}},
                "required": ["path"],
            },
        },
        "write_file": {
            "description": "Create or overwrite a file with the given content. Backs up existing content first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
        "edit_file": {
            "description": "Find-and-replace inside a file. old_text must match exactly once.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string", "description": "Text to find (must match exactly once)"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
        "list_dir": {
            "description": "List the contents of a directory (type, size, name).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Directory path"}},
                "required": ["path"],
            },
        },
        "tree_view": {
            "description": "Recursive ASCII tree of a directory (depth 4, max 200 nodes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "depth": {"type": "integer", "description": "Max depth (1-4)", "default": 3},
                },
                "required": ["path"],
            },
        },
        "make_dir": {
            "description": "Create a directory and all missing parent directories.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        "delete_file": {
            "description": "Snapshot then delete a file. Recoverable via restore_file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        "copy_file": {
            "description": "Copy src to dst. Snapshots dst if it already exists.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                },
                "required": ["src", "dst"],
            },
        },
        "diff_file": {
            "description": "Show unified diff between current file and its last backup.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
        "restore_file": {
            "description": "Roll a file back to a specific prior backup by backup_id.",
            "parameters": {
                "type": "object",
                "properties": {"backup_id": {"type": "string"}},
                "required": ["backup_id"],
            },
        },
        "http_get": {
            "description": "Fetch a URL body (64 KB cap, 15s timeout, stdlib only).",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
        "find_files": {
            "description": "Find files/dirs by name pattern using fd.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "base": {"type": "string", "description": "Search root (default: cwd)"},
                },
                "required": ["pattern"],
            },
        },
        "search_text": {
            "description": "Search file contents using ripgrep.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "path": {"type": "string", "description": "Search root (default: cwd)"},
                },
                "required": ["pattern"],
            },
        },
        "fuzzy_find": {
            "description": "Fuzzy-match file names via fd piped to fzf.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        "env_get": {
            "description": "Get the value of an environment variable.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Variable name"}},
                "required": ["name"],
            },
        },
        "speak": {
            "description": "Speak text via termux-tts-speak.",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        },
        "checkpoint": {
            "description": "Save all current live backup IDs under a named label for later rollback.",
            "parameters": {
                "type": "object",
                "properties": {"label": {"type": "string"}},
                "required": ["label"],
            },
        },
    }

    active_names = SHELL_TOOLS if scope == "shell_only" else set(TOOL_SPECS.keys())
    available = {
        "exec_shell": "do_exec",
        "read_file": "do_read_file",
        "write_file": "do_write_file",
        "edit_file": "do_edit_file",
        "list_dir": "do_list_dir",
        "tree_view": "do_tree_view",
        "make_dir": "do_make_dir",
        "delete_file": "do_delete_file",
        "copy_file": "do_copy_file",
        "diff_file": "do_diff_file",
        "restore_file": "do_restore_file",
        "http_get": "do_http_get",
        "find_files": "do_find_files",
        "search_text": "do_search_text",
        "fuzzy_find": "do_fuzzy_find",
        "env_get": "do_env_get",
        "speak": "do_speak",
        "checkpoint": "do_checkpoint",
    }

    declarations = []
    for tool_name, spec in TOOL_SPECS.items():
        if tool_name not in active_names:
            continue
        do_fn_name = available.get(tool_name)
        if do_fn_name and do_fn_name not in do_map:
            continue
        declarations.append({
            "type": "function",
            "name": tool_name,
            "description": spec["description"],
            "parameters": spec["parameters"],
        })
    return declarations

def extract_text(data: dict) -> str:
    if "output_text" in data:
        return data["output_text"] or ""
    text = ""
    for step in data.get("steps", []):
        if step.get("type") == "model_output":
            for part in step.get("content", []):
                if part.get("type") == "text":
                    text += part.get("text", "")
    return text

def extract_usage(data: dict) -> dict:
    return data.get("usage", {})

class InteractionsPrompter:
    def __init__(
        self,
        key_reg,
        model_reg,
        do_map: dict[str, Callable],
        tool_scope: str = "all",
        max_rounds: int = 10,
        timeout: int = 90,
    ) -> None:
        self.key_reg = key_reg
        self.model_reg = model_reg
        self.do_map = do_map
        self.tool_scope = tool_scope
        self.max_rounds = max_rounds
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self._prev_id: Optional[str] = None

    def reset_session(self) -> None:
        self._prev_id = None

    @property
    def previous_interaction_id(self) -> Optional[str]:
        return self._prev_id

    async def run_turn(
        self,
        user_input: str,
        system_instruction: str = "",
        denylist: Optional[list[str]] = None,
        dryrun: bool = False,
    ) -> tuple[str, dict, list[dict]]:
        tools = build_tool_declarations(self.do_map, self.tool_scope)
        call_log: list[dict] = []
        current_input: Any = user_input
        last_data: dict = {}
        total_usage: dict = {}

        for round_num in range(self.max_rounds):
            data = await self._post(current_input, tools, system_instruction)
            last_data = data

            usage = extract_usage(data)
            for k, v in usage.items():
                if isinstance(v, (int, float)):
                    total_usage[k] = total_usage.get(k, 0) + v
                else:
                    total_usage[k] = v

            fn_calls = [s for s in data.get("steps", []) if s.get("type") == "function_call"]
            if not fn_calls:
                break

            fn_results = []
            for fc in fn_calls:
                name = fc.get("name", "")
                call_id = fc.get("id", "")
                arguments = fc.get("arguments", {})

                result_text, ok = await self._execute_tool(
                    name, arguments, denylist=denylist, dryrun=dryrun
                )
                call_log.append({
                    "name": name, "args": arguments,
                    "result": result_text, "ok": ok,
                })

                fn_results.append({
                    "type": "function_result",
                    "name": name,
                    "call_id": call_id,
                    "result": [{"type": "text", "text": result_text}],
                })

            current_input = fn_results

        # BUGFIX (2026-08-09): a blocked/failed generation (safety,
        # prohibited_content, recitation, malformed_function_call, etc.)
        # comes back as a normal HTTP 200 with status != "completed" and an
        # "error" object -- there's no non-200 status to catch this at the
        # _post() level. Previously this fell straight through to
        # extract_text(), which finds no model_output step and silently
        # returns "" -- the turn would just look like the model said
        # nothing, with no indication anything went wrong at all.
        status = last_data.get("status")
        if status not in (None, "completed"):
            err = last_data.get("error", {})
            code = err.get("code", status) if isinstance(err, dict) else status
            message = err.get("message", "") if isinstance(err, dict) else ""
            raise RuntimeError(
                f"Interactions API returned status '{status}' ({code}) -- {message or 'no message provided'}"
            )

        return extract_text(last_data), total_usage, call_log

    async def _post(self, inp: Any, tools: list[dict], si: str) -> dict:
        model = self.model_reg.active

        body: dict = {"model": model, "input": inp}
        if tools:
            body["tools"] = tools
        if si:
            body["system_instruction"] = si
        if self._prev_id:
            body["previous_interaction_id"] = self._prev_id

        # BUGFIX (2026-08-09): the previous version of this method treated
        # every non-200 response identically -- retry up to 3x with a
        # different key, cooldown whichever key just got used, and discard
        # the response body entirely in favor of a bare "HTTP {status}"
        # string. That's wrong on two counts, and together they explain why
        # Interactions mode could fail every single time with only a
        # generic error and no way to diagnose it:
        #
        # 1. Google's error body (per ai.google.dev/gemini-api/docs/api-errors)
        #    is {"error": {"code": "...", "message": "..."}} -- a real,
        #    specific, human-readable reason. Discarding it and reporting
        #    only "HTTP 400" hides the actual cause completely.
        #
        # 2. A 400/404/409/416 (invalid_request, model_not_found,
        #    parameter_unknown, etc.) is a deterministic problem with THIS
        #    request's shape or a bad model name -- it will fail identically
        #    no matter which key sends it. Retrying it 3x against 3
        #    different keys is pure waste, and worse, calling
        #    set_cooldown() on each of those keys for a request-shape bug
        #    that has nothing to do with them increments their fail count.
        #    KeyRegistry.AUTO_DEACTIVATE_THRESHOLD is 3 -- so a single
        #    malformed-request bug, hit once, was enough to cooldown (and
        #    with a couple of retries, potentially permanently deactivate)
        #    every key in rotation, surfacing later as the even more
        #    misleading "No API keys available." This is likely exactly
        #    what happened across both prior attempts.
        #
        # Fixed behavior, by actual HTTP status:
        #   429              -> rate/quota limit: legitimately worth cooling
        #                       this key and retrying with the next one.
        #   401 / 403        -> auth/permission problem with THIS key:
        #                       legitimately worth cooling it and retrying
        #                       with the next one.
        #   5xx              -> transient server-side problem, not this
        #                       key's fault: retry, but do NOT cooldown or
        #                       penalize the key.
        #   everything else  -> deterministic client-side error (bad
        #                       model name, bad schema, bad parameter,
        #                       etc.): do NOT retry with a different key
        #                       and do NOT touch any key's cooldown/fail
        #                       count -- surface the real message
        #                       immediately, since retrying cannot help.
        last_error = ""
        for attempt in range(3):
            key = self.key_reg.next_key()
            if not key:
                raise RuntimeError("No API keys available.")

            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": key,
            }

            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.post(
                        ENDPOINT, headers=headers, json=body
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            self._prev_id = data.get("id")
                            return data

                        body_txt = await resp.text()
                        code, message = self._parse_error_body(body_txt)
                        detail = f"{code}: {message}" if code else (message or f"HTTP {resp.status}")

                        if resp.status == 429:
                            self.key_reg.set_cooldown(key, COOLDOWN_429)
                            last_error = f"Rate-limited (429) -- {detail}"
                            continue
                        elif resp.status in (401, 403):
                            self.key_reg.set_cooldown(key, COOLDOWN_AUTH)
                            last_error = f"Auth error ({resp.status}) -- {detail}"
                            continue
                        elif 500 <= resp.status < 600:
                            # Transient, not this key's fault -- retry
                            # without penalizing the key at all.
                            last_error = f"Server error ({resp.status}) -- {detail}"
                            continue
                        else:
                            # Deterministic client-side error. Retrying with
                            # a different key cannot fix a bad request body,
                            # and this key did nothing wrong -- fail fast
                            # with the real reason instead of burning the
                            # rest of the key pool on a guaranteed repeat.
                            raise RuntimeError(
                                f"Interactions API request rejected (HTTP {resp.status}) -- {detail}"
                            )
            except asyncio.TimeoutError:
                last_error = "Request timed out"
            except aiohttp.ClientError as exc:
                last_error = f"Connection error: {exc}"

        raise RuntimeError(f"Interactions API exhausted after retries. Last error: {last_error}")

    @staticmethod
    def _parse_error_body(body_txt: str) -> tuple[str, str]:
        """Extract (code, message) from Google's {"error": {"code", "message"}}
        error shape. Returns ("", "") if the body isn't in that shape (e.g.
        an upstream proxy/HTML error page) so callers can fall back safely."""
        try:
            parsed = json.loads(body_txt)
            err = parsed.get("error", {})
            if isinstance(err, dict):
                return str(err.get("code", "")), str(err.get("message", ""))
        except (json.JSONDecodeError, AttributeError):
            pass
        return "", body_txt[:300] if body_txt else ""

    async def _execute_tool(
        self,
        name: str,
        arguments: dict,
        denylist: Optional[list[str]] = None,
        dryrun: bool = False,
    ) -> tuple[str, bool]:
        _name_map = {
            "exec_shell": "do_exec",
            "read_file": "do_read_file",
            "write_file": "do_write_file",
            "edit_file": "do_edit_file",
            "list_dir": "do_list_dir",
            "tree_view": "do_tree_view",
            "make_dir": "do_make_dir",
            "delete_file": "do_delete_file",
            "copy_file": "do_copy_file",
            "diff_file": "do_diff_file",
            "restore_file": "do_restore_file",
            "http_get": "do_http_get",
            "find_files": "do_find_files",
            "search_text": "do_search_text",
            "fuzzy_find": "do_fuzzy_find",
            "env_get": "do_env_get",
            "speak": "do_speak",
            "checkpoint": "do_checkpoint",
        }

        fn_key = _name_map.get(name)
        if not fn_key or fn_key not in self.do_map:
            return f"[ERROR] Unknown tool: {name}", False

        fn = self.do_map[fn_key]

        if name == "exec_shell" and denylist:
            cmd = arguments.get("command", "")
            for blocked in denylist:
                if cmd.strip().startswith(blocked):
                    return f"[BLOCKED] Command matches denylist: {blocked}", False

        if dryrun:
            return f"[DRYRUN] Would call {name}({arguments})", True

        try:
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**arguments)
            else:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(None, lambda: fn(**arguments))
            if fn_key == "do_speak" and isinstance(result, tuple):
                speak_ok, speak_msg = result
                return speak_msg, speak_ok
            return str(result), True
        except Exception as exc:
            logger.error("[INT] Tool %s failed: %s", name, exc)
            return f"[ERROR] {name}: {exc}", False
