"""
Name:         webagent.py
Family:       NewAgent
Description:  Flask-based web terminal wrapper for NewAgent. Serves the
              browser terminal GUI and routes all configuration, shell execution,
              conversational turns, and JobMaker/notes operations through gated
              modular service abstraction layers (lib_bejson_newagent_service_gates.py).
Version:      0.14.0
Date:         2026-11-12
Author:       Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:      PolyForm-Noncommercial-1.0.0
RELATIONAL_ID: bdac0890-8fa2-474f-a6e0-e7e6af0c921b

CHANGELOG:
- 0.14.0 (2026-11-12): Audited taxonomies (<hierarchy>_<group>_<purpose>), separated
  transport routes from domain services via gated modular service controllers
  (ServiceGateConfigurationController, ServiceGateExecutionController,
  ServiceGateConversationController, ServiceGateJobNotesController), and enabled
  full 67-option / 7-category / 3-store BEJSON 104a configuration control via UI.
- 0.13.1 (2026-10-17): Hardening -- Host allow-list, failed-auth throttle (429), non-ASCII token
  no longer 500s, 2 MB request cap, no-store/no-referrer headers, protected config keys,
  notes validation, non-loopback bind requires --allow-remote. See web_routes/.
- 0.13.0 (2026-10-17): DECOMPOSED (audit item 6). The 66 KB inline HTML moved to
  templates/webagent_terminal.html; every route moved into web_routes/ as blueprints.
"""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

# Insert lib/ directory into path to resolve lib_bejson_newagent_* correctly
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

try:
    from flask import Flask
except ImportError:
    sys.exit("webagent.py needs Flask. Install it with:  python3 -m pip install flask")

import lib_bejson_newagent_config as config_lib
import lib_bejson_newagent_context_bubble as bubble
import lib_bejson_newagent_engine_rest as rest
import lib_bejson_newagent_env as newagent_env
import lib_bejson_newagent_jobs as jobs
import lib_bejson_newagent_tui as tui
from lib_bejson_newagent_service_gates import (
    ServiceGateConfigurationController,
    ServiceGateConversationController,
    ServiceGateExecutionController,
    ServiceGateJobNotesController,
)

# Mandatory environment sourcing (Policy §4)
newagent_env.newagent_source_env()

from web_routes.web_common import (  # noqa: E402
    BACKUPS_DIR,
    BASE_DIR,
    CONFIG_DIR,
    CONFIG_PATH,
    CONTEXT_DIR,
    JOBS_DIR,
    KEYS_PATH,
    LOGS_DIR,
    MAX_AUTO_CONTINUE,
    MODEL_CATALOG_PATH,
    MODELS_PATH,
    NOTES_DIR,
    NOTES_FILE,
    STATE_PATH,
    VERSION,
    describe_attachment_path,
    run_async,
)
from web_routes import (  # noqa: E402
    api_chat_routes,
    api_config_routes,
    api_exec_routes,
    api_jobs_routes,
    security,
    ui_routes,
)

__version__ = VERSION
webagent_logger = logging.getLogger(__name__)


class WebAgentTerminal:
    """
    Class-based Flask wrapper around the NewAgent browser terminal with gated
    modular service controllers for configuration, execution, conversation, and jobs.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 5001,
        allow_remote: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        is_loopback_bind = (
            host in ("127.0.0.1", "localhost", "::1") or host.startswith("127.")
        )
        if not is_loopback_bind and not allow_remote:
            sys.exit(
                f"Refusing to bind {host}: the web terminal can run shell commands. "
                "Pass --allow-remote if you really mean to expose it beyond localhost."
            )
        self.allowed_hosts = (
            {"127.0.0.1", "localhost", "[::1]", host.lower()}
            if is_loopback_bind
            else None
        )
        self.app = Flask(__name__)
        self.app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB request cap

        # Thread-safe state mutex for single-session terminal state
        self._state_lock = threading.Lock()

        self._cwd = str(BASE_DIR)
        self._shell_env = None
        jobs.ensure_job_dirs(JOBS_DIR)
        jobs.cleanup_old_completed_jobs(JOBS_DIR)
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        self._active_job_path = None
        self._active_job_doc = None

        # Shared BEJSON 104a configuration
        self.config = config_lib.init_config(CONFIG_PATH)
        self.web_token = config_lib.get_or_create_web_auth_token(
            CONFIG_PATH, self.config
        )
        webagent_logger.info(
            "[webagent] Auth token ready. Listening on http://%s:%d/?token=%s",
            host,
            port,
            self.web_token,
        )

        # Synchronize API keys from canonical environment sources and initialize registries
        rest.sync_keys_from_env_sources(KEYS_PATH, self.config)
        self.key_reg = rest.KeyRegistry(KEYS_PATH, STATE_PATH)
        self.model_reg = rest.ModelRegistry(MODELS_PATH)
        self.rest_prompter = rest.RestPrompter(
            self.key_reg,
            self.model_reg,
            MODEL_CATALOG_PATH,
            self.config,
            logs_dir=LOGS_DIR,
        )

        # Conversational turn state
        self.history: list[dict] = []
        self.turn_count = 0
        self.trigger_cooldowns: dict[str, float] = {}
        self.key_call_counts: dict[str, int] = {}
        self.stats = tui.SessionStats(key_total=len(self.key_reg.keys), engine="rest")
        for runtime_directory in (CONTEXT_DIR, BACKUPS_DIR, LOGS_DIR):
            runtime_directory.mkdir(parents=True, exist_ok=True)
        bubble.init_context_bubble(CONTEXT_DIR, CONFIG_DIR, LOGS_DIR)

        # Instantiate gated modular service abstraction layers
        self.config_service_gate = ServiceGateConfigurationController(
            terminal_state_holder=self,
            project_root_dir_path=BASE_DIR,
            main_config_file_path=CONFIG_PATH,
            model_catalog_file_path=MODEL_CATALOG_PATH,
            runtime_version_string=VERSION,
        )
        self.exec_service_gate = ServiceGateExecutionController(
            terminal_state_holder=self,
            project_root_dir_path=BASE_DIR,
            async_runner_callable=run_async,
        )
        self.chat_service_gate = ServiceGateConversationController(
            terminal_state_holder=self,
            config_dir_path=CONFIG_DIR,
            context_dir_path=CONTEXT_DIR,
            backups_dir_path=BACKUPS_DIR,
            jobs_dir_path=JOBS_DIR,
            max_auto_continue_iterations=MAX_AUTO_CONTINUE,
            async_runner_callable=run_async,
            attachment_describer_callable=describe_attachment_path,
        )
        self.jobs_notes_service_gate = ServiceGateJobNotesController(
            terminal_state_holder=self,
            jobs_dir_path_getter=lambda: JOBS_DIR,
            notes_dir_path_getter=lambda: NOTES_DIR,
            notes_file_path_getter=lambda: NOTES_FILE,
            notes_max_chars_getter=lambda: api_jobs_routes.NOTES_MAX_CHARS,
        )

        self._register_routes()

    def _register_routes(self) -> None:
        """Install the authentication/security gate and register route blueprints."""
        security.register_security(self.app, self)
        for route_module in (
            ui_routes,
            api_exec_routes,
            api_config_routes,
            api_chat_routes,
            api_jobs_routes,
        ):
            self.app.register_blueprint(route_module.create_blueprint(self))

    def run(self, debug: bool = False) -> None:
        self.app.run(host=self.host, port=self.port, debug=debug)


if __name__ == "__main__":
    import argparse

    cli_argument_parser = argparse.ArgumentParser(description="NewAgent web terminal")
    cli_argument_parser.add_argument("--host", default="127.0.0.1")
    cli_argument_parser.add_argument("--port", type=int, default=5001)
    cli_argument_parser.add_argument(
        "--allow-remote",
        action="store_true",
        help="permit a non-loopback --host (exposes shell execution to the network)",
    )
    parsed_cli_arguments = cli_argument_parser.parse_args()
    WebAgentTerminal(
        host=parsed_cli_arguments.host,
        port=parsed_cli_arguments.port,
        allow_remote=parsed_cli_arguments.allow_remote,
    ).run()
