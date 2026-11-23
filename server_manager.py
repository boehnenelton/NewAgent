#!/data/data/com.termux/files/usr/bin/python3
"""
Script:         server_manager.py
Family:         NewAgent
Description:    Asynchronous server lifecycle manager for the NewAgent web terminal
                (webagent.py) with automated Termux clipboard synchronization,
                Google Chrome browser auto-dispatch via Android Activity Manager,
                PID tracking (.server.pid), and 49-column mobile portrait TUI controls
                per System Invariants.
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Date Created:   2026-11-13
Version:        1.0.0
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  7c2f814d-91b3-4f9e-a856-12e4f0a9b3d5
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT_DIRECTORY_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT_DIRECTORY_PATH / "lib"))

import lib_bejson_newagent_config as config_library

PID_FILE_PATH = PROJECT_ROOT_DIRECTORY_PATH / ".server.pid"
LOG_FILE_PATH = PROJECT_ROOT_DIRECTORY_PATH / "server.log"
CONFIG_FILE_PATH = PROJECT_ROOT_DIRECTORY_PATH / "config" / "config.json"

DEFAULT_SERVER_PORT: int = 5001
DEFAULT_SERVER_HOST: str = "127.0.0.1"

DIVIDER_49: str = "=" * 49
SUBDIVIDER_49: str = "-" * 49


def check_is_process_alive(process_id_number: int) -> bool:
    """Check if the process associated with process_id_number is currently running."""
    if process_id_number <= 0:
        return False
    try:
        os.kill(process_id_number, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def read_tracked_process_id() -> int:
    """Read the active server process identifier from the PID file."""
    if not PID_FILE_PATH.exists():
        return 0
    try:
        file_content_text = PID_FILE_PATH.read_text(encoding="utf-8").strip()
        return int(file_content_text) if file_content_text.isdigit() else 0
    except Exception:
        return 0


def copy_url_to_termux_clipboard(target_url_string: str) -> bool:
    """Copy target URL to Termux clipboard via termux-clipboard-set if available."""
    try:
        clipboard_subprocess = subprocess.run(
            ["termux-clipboard-set"],
            input=target_url_string,
            text=True,
            capture_output=True,
            timeout=3,
        )
        return clipboard_subprocess.returncode == 0
    except Exception:
        return False


def dispatch_chrome_browser(target_url_string: str) -> bool:
    """
    Launch Google Chrome as the mandatory primary browser via Android Activity Manager
    per System Invariants, falling back to standard Termux and Linux URL openers.
    """
    copy_url_to_termux_clipboard(target_url_string)

    # 1. Primary: Chrome via Activity Manager
    try:
        activity_manager_command = [
            "am",
            "start",
            "-n",
            "com.android.chrome/com.google.android.apps.chrome.Main",
            "-d",
            target_url_string,
        ]
        activity_subprocess = subprocess.run(
            activity_manager_command,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if activity_subprocess.returncode == 0:
            print("[OK] Chrome launched via Activity Manager.")
            return True
    except Exception:
        pass

    # 2. Secondary fallback: Termux and Linux openers
    for fallback_executable_name in ("termux-open-url", "termux-open", "xdg-open"):
        try:
            fallback_subprocess = subprocess.run(
                [fallback_executable_name, target_url_string],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if fallback_subprocess.returncode == 0:
                print(f"[OK] Browser launched via {fallback_executable_name}.")
                return True
        except Exception:
            continue

    print(f"[NOTE] Please open URL: {target_url_string}")
    return False


def resolve_web_authentication_token() -> str:
    """Read or initialize the web authentication token from config/config.json."""
    try:
        configuration_map = config_library.init_config(CONFIG_FILE_PATH)
        return config_library.get_or_create_web_auth_token(CONFIG_FILE_PATH, configuration_map)
    except Exception:
        return ""


def start_server_daemon(
    host_address_string: str = DEFAULT_SERVER_HOST,
    port_number: int = DEFAULT_SERVER_PORT,
    auto_open_browser_flag: bool = True,
) -> bool:
    """Start webagent.py in the background, record PID, and dispatch Chrome."""
    existing_process_id = read_tracked_process_id()
    if existing_process_id and check_is_process_alive(existing_process_id):
        print(f"[INFO] Server already running (PID: {existing_process_id})")
        token_string = resolve_web_authentication_token()
        target_server_url = f"http://{host_address_string}:{port_number}/?token={token_string}"
        copy_url_to_termux_clipboard(target_server_url)
        if auto_open_browser_flag:
            dispatch_chrome_browser(target_server_url)
        return True

    print(f"[*] Starting webagent on http://{host_address_string}:{port_number}...")
    log_file_handle = open(LOG_FILE_PATH, "a", encoding="utf-8")
    server_process_environment = os.environ.copy()
    server_process_environment["PYTHONUNBUFFERED"] = "1"

    webagent_script_path = PROJECT_ROOT_DIRECTORY_PATH / "webagent.py"
    launched_subprocess = subprocess.Popen(
        [
            sys.executable,
            str(webagent_script_path),
            "--host",
            host_address_string,
            "--port",
            str(port_number),
            "--no-browser",  # Handled directly by server_manager
        ],
        cwd=str(PROJECT_ROOT_DIRECTORY_PATH),
        env=server_process_environment,
        stdout=log_file_handle,
        stderr=log_file_handle,
        start_new_session=True,
    )
    time.sleep(0.6)

    if check_is_process_alive(launched_subprocess.pid):
        PID_FILE_PATH.write_text(str(launched_subprocess.pid), encoding="utf-8")
        print(f"[OK] webagent started (PID: {launched_subprocess.pid})")

        token_string = resolve_web_authentication_token()
        target_server_url = f"http://{host_address_string}:{port_number}/?token={token_string}"
        copy_url_to_termux_clipboard(target_server_url)
        print(f"[OK] URL copied to clipboard.")

        if auto_open_browser_flag:
            dispatch_chrome_browser(target_server_url)

        return True
    else:
        print("[FAIL] webagent failed to start. Check server.log.")
        return False


def stop_server_daemon() -> None:
    """Gracefully terminate the background webagent server process."""
    tracked_process_id = read_tracked_process_id()
    if not tracked_process_id or not check_is_process_alive(tracked_process_id):
        if PID_FILE_PATH.exists():
            PID_FILE_PATH.unlink(missing_ok=True)
        print("[INFO] webagent is not currently running.")
        return

    print(f"[*] Stopping webagent (PID {tracked_process_id})...")
    try:
        os.kill(tracked_process_id, signal.SIGTERM)
        time.sleep(0.5)
        if check_is_process_alive(tracked_process_id):
            os.kill(tracked_process_id, signal.SIGKILL)
    except Exception:
        pass

    PID_FILE_PATH.unlink(missing_ok=True)
    print("[OK] webagent stopped.")


def restart_server_daemon(
    host_address_string: str = DEFAULT_SERVER_HOST,
    port_number: int = DEFAULT_SERVER_PORT,
    auto_open_browser_flag: bool = True,
) -> bool:
    """Restart the background webagent server process."""
    stop_server_daemon()
    time.sleep(0.3)
    return start_server_daemon(
        host_address_string=host_address_string,
        port_number=port_number,
        auto_open_browser_flag=auto_open_browser_flag,
    )


def print_server_status_table(
    host_address_string: str = DEFAULT_SERVER_HOST,
    port_number: int = DEFAULT_SERVER_PORT,
) -> None:
    """Print the server status table adhering to the 49-character viewport ceiling."""
    tracked_process_id = read_tracked_process_id()
    is_alive_flag = check_is_process_alive(tracked_process_id)
    token_string = resolve_web_authentication_token()

    print(DIVIDER_49)
    print(" NEWAGENT WEB TERMINAL STATUS".center(49))
    print(DIVIDER_49)
    status_label_text = f"RUNNING (PID {tracked_process_id})" if is_alive_flag else "STOPPED"
    print(f" Status:    {status_label_text}")
    print(f" Host/Port: {host_address_string}:{port_number}")
    if is_alive_flag and token_string:
        print(f" Web Token: {token_string[:16]}...")
        print(f" URL:       http://{host_address_string}:{port_number}/")
    print(DIVIDER_49)


def print_server_logs_tail(number_of_lines_count: int = 20) -> None:
    """Print the most recent log output lines from server.log."""
    print(DIVIDER_49)
    print(" SERVER LOG (TAIL)".center(49))
    print(DIVIDER_49)
    if not LOG_FILE_PATH.exists():
        print(" (No log file created yet)")
    else:
        try:
            log_lines_collection = LOG_FILE_PATH.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            display_slice = log_lines_collection[-number_of_lines_count:]
            for single_log_line in display_slice:
                # Wrap or truncate to 49 columns
                print(single_log_line[:49])
        except Exception as read_error:
            print(f" Error reading log: {read_error}")
    print(DIVIDER_49)


def run_interactive_terminal_menu() -> None:
    """Interactive 49-column mobile portrait TUI management menu."""
    while True:
        tracked_process_id = read_tracked_process_id()
        is_alive_flag = check_is_process_alive(tracked_process_id)
        status_string = f"RUNNING [{tracked_process_id}]" if is_alive_flag else "STOPPED"

        print()
        print(DIVIDER_49)
        print(" NEWAGENT WEB TERMINAL MANAGER".center(49))
        print(DIVIDER_49)
        print(f" Current State: {status_string}")
        print(SUBDIVIDER_49)
        print(" [1] Start Server & Launch Chrome")
        print(" [2] Stop Server")
        print(" [3] Restart Server")
        print(" [4] Check Status")
        print(" [5] View Recent Logs")
        print(" [6] Open Chrome Browser")
        print(" [0] Exit Menu")
        print(DIVIDER_49)

        try:
            user_menu_selection = input(" Enter selection [0-6]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break

        if user_menu_selection == "1":
            start_server_daemon(auto_open_browser_flag=True)
        elif user_menu_selection == "2":
            stop_server_daemon()
        elif user_menu_selection == "3":
            restart_server_daemon(auto_open_browser_flag=True)
        elif user_menu_selection == "4":
            print_server_status_table()
        elif user_menu_selection == "5":
            print_server_logs_tail()
        elif user_menu_selection == "6":
            token_string = resolve_web_authentication_token()
            target_url_string = (
                f"http://{DEFAULT_SERVER_HOST}:{DEFAULT_SERVER_PORT}/?token={token_string}"
            )
            dispatch_chrome_browser(target_url_string)
        elif user_menu_selection in ("0", "q", "exit"):
            print(" Exiting manager. Server remains in its current state.")
            break
        else:
            print(" [!] Invalid option. Please select 0-6.")


def main() -> int:
    """CLI argument dispatch entry point."""
    command_line_argument_parser = argparse.ArgumentParser(
        description="NewAgent Web Terminal Server Manager"
    )
    command_line_argument_parser.add_argument(
        "--start", action="store_true", help="Start webagent background server"
    )
    command_line_argument_parser.add_argument(
        "--stop", action="store_true", help="Stop webagent background server"
    )
    command_line_argument_parser.add_argument(
        "--restart", action="store_true", help="Restart webagent background server"
    )
    command_line_argument_parser.add_argument(
        "--status", action="store_true", help="Display server running status"
    )
    command_line_argument_parser.add_argument(
        "--logs", action="store_true", help="View recent server log output"
    )
    command_line_argument_parser.add_argument(
        "--open", action="store_true", help="Open Chrome browser to webagent URL"
    )
    command_line_argument_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not auto-launch browser on server start",
    )
    command_line_argument_parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SERVER_PORT,
        help=f"Server port (default: {DEFAULT_SERVER_PORT})",
    )
    command_line_argument_parser.add_argument(
        "--host",
        default=DEFAULT_SERVER_HOST,
        help=f"Server host (default: {DEFAULT_SERVER_HOST})",
    )

    parsed_arguments = command_line_argument_parser.parse_args()

    # If specific flags are supplied, execute non-interactively
    if parsed_arguments.status:
        print_server_status_table(
            host_address_string=parsed_arguments.host,
            port_number=parsed_arguments.port,
        )
        return 0

    if parsed_arguments.logs:
        print_server_logs_tail()
        return 0

    if parsed_arguments.open:
        token_string = resolve_web_authentication_token()
        target_url_string = (
            f"http://{parsed_arguments.host}:{parsed_arguments.port}/?token={token_string}"
        )
        dispatch_chrome_browser(target_url_string)
        return 0

    if parsed_arguments.stop:
        stop_server_daemon()
        return 0

    if parsed_arguments.restart:
        restart_server_daemon(
            host_address_string=parsed_arguments.host,
            port_number=parsed_arguments.port,
            auto_open_browser_flag=not parsed_arguments.no_browser,
        )
        print_server_status_table(
            host_address_string=parsed_arguments.host,
            port_number=parsed_arguments.port,
        )
        return 0

    if parsed_arguments.start:
        start_server_daemon(
            host_address_string=parsed_arguments.host,
            port_number=parsed_arguments.port,
            auto_open_browser_flag=not parsed_arguments.no_browser,
        )
        print_server_status_table(
            host_address_string=parsed_arguments.host,
            port_number=parsed_arguments.port,
        )
        return 0

    # Default action when invoked with no arguments: start server and launch Chrome
    # (Matches user expectation "run webagent make sure browser auto loads chrome")
    start_server_daemon(
        host_address_string=parsed_arguments.host,
        port_number=parsed_arguments.port,
        auto_open_browser_flag=not parsed_arguments.no_browser,
    )
    print_server_status_table(
        host_address_string=parsed_arguments.host,
        port_number=parsed_arguments.port,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
