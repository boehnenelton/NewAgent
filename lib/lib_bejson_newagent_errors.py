"""
Library:        lib_bejson_newagent_errors.py
Family:         NewAgent
Description:    Custom exception hierarchy distinguishing fatal (unrecoverable,
                 clean-shutdown) errors from recoverable (turn-local, keep the
                 session alive) errors. Error codes follow the numeric-registry
                 convention established in lib_bejson_Core_bejson_errors.py,
                 in a reserved NewAgent block (300-329) that does not collide
                 with any existing Core/MFDB/Nesting/Cognition range.
Version:        1.1.0
Date:           2026-10-13
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  8f1a3c7e-2d4b-4e9a-9c1f-6b7d0a2e5f83
"""

# ---------------------------------------------------------------------------
# NewAgent error codes (300-329) — reserved block, no collision with Core
# ---------------------------------------------------------------------------
E_NEWAGENT_STATE_CORRUPTION   = 300
E_NEWAGENT_REGISTRY_ACCESS    = 301
E_NEWAGENT_BOOTSTRAP_FAILURE  = 302
E_NEWAGENT_ENGINE_PARSE       = 310
E_NEWAGENT_ACTION_TIMEOUT     = 311
E_NEWAGENT_CONTEXT_INJECTION  = 312


class NewAgentException(Exception):
    """Top-level base class for every NewAgent-specific error."""
    error_code: int = 0

    def __init__(self, message: str, *, error_code: int = 0) -> None:
        super().__init__(message)
        self.error_code = error_code or self.error_code


# ---------------------------------------------------------------------------
# Fatal — unrecoverable, must trigger a clean shutdown
# ---------------------------------------------------------------------------
class NewAgentFatalError(NewAgentException):
    """Parent class for terminal failures. Caught in agent.py's main loop —
    triggers a final backup, a logged crash record, and ctx['_exit_requested']
    = True for a clean shutdown rather than continuing on corrupted state."""


class StateCorruptionError(NewAgentFatalError):
    """key_reg / model_reg internally inconsistent (e.g. positional integrity
    lost in a BEJSON-backed registry file)."""
    error_code = E_NEWAGENT_STATE_CORRUPTION


class RegistryAccessError(NewAgentFatalError):
    """Critical config/registry files (keys.bejson, config.json, etc.)
    inaccessible, or an atomic write via bejson_core_atomic_write failed."""
    error_code = E_NEWAGENT_REGISTRY_ACCESS


class BootstrapFailureError(NewAgentFatalError):
    """agent.py's initialization sequence (directories, registries, config,
    logging, backups) failed to establish a working environment."""
    error_code = E_NEWAGENT_BOOTSTRAP_FAILURE


# ---------------------------------------------------------------------------
# Recoverable — turn-local, session stays alive
# ---------------------------------------------------------------------------
class NewAgentRecoverableError(NewAgentException):
    """Parent class for issues that allow the agent to continue. Caught in
    agent.py's main loop — logs the error, shows a TUI warning status, and
    `continue`s to the next turn rather than exiting."""


class EngineParseError(NewAgentRecoverableError):
    """API response body could not be parsed/used as expected (e.g. missing
    candidates/parts shape, or — for a BEJSON-backed engine variant — failed
    validate_bejson structural validation)."""
    error_code = E_NEWAGENT_ENGINE_PARSE


class ActionTimeoutError(NewAgentRecoverableError):
    """A shell command via do_exec/async_run_exec exceeded
    config['exec_timeout_seconds']."""
    error_code = E_NEWAGENT_ACTION_TIMEOUT


# ── Secret redaction ────────────────────────────────────────────────────
# 1.1.0 (2026-10-13): audit remediation -- raw API keys were landing in
# session logs (env drip) and in provider error bodies echoed into logs and
# key_usage reasons. Single shared scrubber so every writer uses one rule.
import re as _re

_SECRET_PATTERNS = (
    _re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),                 # Google API keys
    _re.compile(r"\bAQ\.[0-9A-Za-z_\-]{20,}"),               # Google AQ.* keys
    _re.compile(r"\bsk-[0-9A-Za-z_\-]{20,}"),                # OpenAI/OpenRouter style
    _re.compile(r"\bgsk_[0-9A-Za-z]{20,}"),                  # Groq
    _re.compile(r"\bhf_[0-9A-Za-z]{20,}"),                   # Hugging Face
    _re.compile(r"(?i)(bearer\s+)[0-9A-Za-z._\-]{20,}"),      # Authorization headers
)
SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


def mask_value(value) -> str:
    """first 4 + '...' + last 2 for long values, '***' otherwise."""
    s = str(value)
    return f"{s[:4]}...{s[-2:]}" if len(s) > 12 else "***"


def is_secret_name(name: str, var_type: str = "") -> bool:
    if str(var_type).strip().lower() == "secret":
        return True
    upper = str(name).upper()
    return any(m in upper for m in SECRET_NAME_MARKERS)


def redact_secrets(text):
    """Replaces anything shaped like an API key/token in `text` with a
    masked form. Non-str input is returned unchanged."""
    if not isinstance(text, str) or not text:
        return text
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", text)
    return text


class ContextInjectionError(NewAgentRecoverableError):
    """Context Bubble assembly (assemble_bubble) failed; caller should retry
    the turn with a minimal/default context rather than crash."""
    error_code = E_NEWAGENT_CONTEXT_INJECTION
