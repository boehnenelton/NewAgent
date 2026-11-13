#!/data/data/com.termux/files/usr/bin/python3
"""
Script:         run_flask_playwright_suite.py
Family:         NewAgent
Description:    Playwright automated test suite for NewAgent Flask tools
                (webagent.py and JobMaker.py). Tests interactive terminal,
                settings overlay, jobs tab, persistent notes editor, 67-option
                configuration tab across 7 categories and 3 stores, live search
                filtering, BEJSON 104a schema validation, files browser, and
                JobMaker task workflow. Captures snapshots in agds/, mirrors to
                images/flask_snapshots/, and generates 420px responsive images
                in images/screenshots/ for repository documentation.
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Date:           2026-11-13
Version:        2.0.0
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  a7b4c102-5e8f-4d93-9c2b-1a0f8e3d5c7b
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

SCRIPT_DIRECTORY_PATH = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIRECTORY_PATH / "lib"))

import lib_bejson_newagent_config as config_library
from termux_playwright import async_playwright_termux, launch

AGDS_DIRECTORY_PATH = SCRIPT_DIRECTORY_PATH / "agds"
IMAGES_MIRROR_DIRECTORY_PATH = SCRIPT_DIRECTORY_PATH / "images" / "flask_snapshots"
IMAGES_SCREENSHOTS_DIRECTORY_PATH = SCRIPT_DIRECTORY_PATH / "images" / "screenshots"

PORT_WEBAGENT_SERVER: int = 5181
PORT_JOBMAKER_SERVER: int = 5182


def check_is_port_in_use(port_number: int, host_name: str = "127.0.0.1") -> bool:
    """Check if the specified host port is open and accepting TCP connections."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe_socket:
        probe_socket.settimeout(0.5)
        return probe_socket.connect_ex((host_name, port_number)) == 0


def wait_until_endpoint_responsive(
    endpoint_target_url: str,
    timeout_duration_seconds: float = 20.0,
    authorization_header_value: str | None = None,
) -> bool:
    """Poll endpoint_target_url until HTTP response status code indicates server readiness."""
    start_timestamp_seconds = time.time()
    while time.time() - start_timestamp_seconds < timeout_duration_seconds:
        try:
            http_request_object = urllib.request.Request(endpoint_target_url)
            if authorization_header_value:
                http_request_object.add_header("Authorization", authorization_header_value)
            with urllib.request.urlopen(http_request_object, timeout=1.5) as http_response_object:
                if http_response_object.status in (200, 302):
                    return True
        except urllib.error.HTTPError as caught_http_error:
            if caught_http_error.code in (200, 302, 401):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def resize_screenshot_to_responsive_standard(
    source_snapshot_path: Path,
    destination_target_path: Path,
    target_width_pixels: int = 420,
) -> None:
    """Resize captured screenshot to responsive standard width maintaining aspect ratio."""
    with Image.open(source_snapshot_path) as source_image_object:
        original_width, original_height = source_image_object.size
        scaled_height_pixels = int(target_width_pixels / original_width * original_height)
        resized_image_object = source_image_object.resize(
            (target_width_pixels, scaled_height_pixels),
            resample=Image.Resampling.LANCZOS,
        )
        resized_image_object.save(destination_target_path, optimize=True)


async def execute_playwright_tests() -> int:
    """Execute end-to-end Playwright tests across webagent.py and JobMaker.py."""
    AGDS_DIRECTORY_PATH.mkdir(parents=True, exist_ok=True)
    IMAGES_MIRROR_DIRECTORY_PATH.mkdir(parents=True, exist_ok=True)
    IMAGES_SCREENSHOTS_DIRECTORY_PATH.mkdir(parents=True, exist_ok=True)

    config_json_file_path = SCRIPT_DIRECTORY_PATH / "config" / "config.json"
    configuration_dictionary = config_library.init_config(config_json_file_path)
    web_authentication_token = config_library.get_or_create_web_auth_token(
        config_json_file_path, configuration_dictionary
    )

    spawned_servers_list: list[subprocess.Popen] = []
    base_process_environment = os.environ.copy()
    base_process_environment["PYTHONUNBUFFERED"] = "1"

    print("[1/5] Launching Flask tools (webagent.py & JobMaker.py)...")
    # 1. webagent.py on PORT_WEBAGENT_SERVER
    process_webagent = subprocess.Popen(
        [
            sys.executable,
            str(SCRIPT_DIRECTORY_PATH / "webagent.py"),
            "--host",
            "127.0.0.1",
            "--port",
            str(PORT_WEBAGENT_SERVER),
        ],
        cwd=str(SCRIPT_DIRECTORY_PATH),
        env=base_process_environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    spawned_servers_list.append(process_webagent)

    # 2. JobMaker.py on PORT_JOBMAKER_SERVER
    jobmaker_process_environment = base_process_environment.copy()
    jobmaker_process_environment["JOBMAKER_PORT"] = str(PORT_JOBMAKER_SERVER)
    process_jobmaker = subprocess.Popen(
        [sys.executable, str(SCRIPT_DIRECTORY_PATH / "JobMaker.py")],
        cwd=str(SCRIPT_DIRECTORY_PATH),
        env=jobmaker_process_environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    spawned_servers_list.append(process_jobmaker)

    try:
        print("[2/5] Waiting for Flask servers to respond...")
        webagent_target_url = (
            f"http://127.0.0.1:{PORT_WEBAGENT_SERVER}/?token={web_authentication_token}&skip_boot=1"
        )
        jobmaker_target_url = (
            f"http://127.0.0.1:{PORT_JOBMAKER_SERVER}/?token={web_authentication_token}"
        )

        assert wait_until_endpoint_responsive(webagent_target_url), "webagent.py startup timeout"
        assert wait_until_endpoint_responsive(jobmaker_target_url), "JobMaker.py startup timeout"
        print(" -> Both Flask servers (webagent & JobMaker) are responsive!")

        print("[3/5] Starting Playwright browser in Termux ARM64...")
        captured_snapshots_list: list[str] = []

        async with async_playwright_termux() as playwright_runtime_instance:
            browser_instance = await launch(playwright_runtime_instance, headless=True)
            browser_page_object = await browser_instance.new_page(
                viewport={"width": 1280, "height": 840}
            )

            # --- Tool 1: webagent.py ---
            print(" -> Testing Tool 1: webagent.py")
            await browser_page_object.goto(
                webagent_target_url, timeout=30000, wait_until="domcontentloaded"
            )
            await browser_page_object.wait_for_selector("#terminal", timeout=10000)

            # 1. WebAgent Terminal Default View
            snapshot_path_01 = str(AGDS_DIRECTORY_PATH / "01_webagent_terminal.png")
            await browser_page_object.screenshot(path=snapshot_path_01, full_page=True)
            captured_snapshots_list.append(snapshot_path_01)

            # Open Settings overlay
            await browser_page_object.click("#header-settings-btn")
            await browser_page_object.wait_for_selector("#gui-overlay", state="visible", timeout=5000)

            # 2. Jobs Tab
            await browser_page_object.click('.tab-button[data-tab="tab-jobs"]')
            await browser_page_object.wait_for_selector("#job-active-badge", timeout=5000)
            await browser_page_object.wait_for_timeout(400)
            snapshot_path_02 = str(AGDS_DIRECTORY_PATH / "02_webagent_jobs_tab.png")
            await browser_page_object.screenshot(path=snapshot_path_02, full_page=True)
            captured_snapshots_list.append(snapshot_path_02)

            # 3. Notes Tab
            await browser_page_object.click('.tab-button[data-tab="tab-notes"]')
            await browser_page_object.wait_for_selector("#notes-textarea", timeout=5000)
            await browser_page_object.fill(
                "#notes-textarea",
                "Playwright automated verification: webagent.py 0.14.0 active with 67 options.",
            )
            await browser_page_object.wait_for_timeout(400)
            snapshot_path_03 = str(AGDS_DIRECTORY_PATH / "03_webagent_notes_tab.png")
            await browser_page_object.screenshot(path=snapshot_path_03, full_page=True)
            captured_snapshots_list.append(snapshot_path_03)

            # 4. Config Tab (ALL Categories - 67 Options)
            await browser_page_object.click('.tab-button[data-tab="tab-config"]')
            await browser_page_object.wait_for_selector("#config-summary-badge", timeout=5000)
            await browser_page_object.wait_for_timeout(600)
            snapshot_path_04 = str(AGDS_DIRECTORY_PATH / "04_webagent_config_tab.png")
            await browser_page_object.screenshot(path=snapshot_path_04, full_page=True)
            captured_snapshots_list.append(snapshot_path_04)

            # 5. Config Tab - Category Filtering (BUB Category)
            await browser_page_object.click('.config-cat-pill:has-text("BUB")')
            await browser_page_object.wait_for_timeout(400)
            snapshot_path_05 = str(AGDS_DIRECTORY_PATH / "05_webagent_config_category.png")
            await browser_page_object.screenshot(path=snapshot_path_05, full_page=True)
            captured_snapshots_list.append(snapshot_path_05)

            # 6. Config Tab - Search Filtering & 104a Validation Diagnostics
            # Reset category to ALL
            await browser_page_object.click('.config-cat-pill:has-text("ALL")')
            await browser_page_object.wait_for_timeout(200)

            await browser_page_object.fill("#config-search-input", "dryrun")
            await browser_page_object.wait_for_timeout(300)
            await browser_page_object.click("#config-validate-btn")
            await browser_page_object.wait_for_selector(
                "#config-diagnostics-box", state="visible", timeout=5000
            )
            await browser_page_object.wait_for_timeout(400)
            snapshot_path_06 = str(AGDS_DIRECTORY_PATH / "06_webagent_config_search.png")
            await browser_page_object.screenshot(path=snapshot_path_06, full_page=True)
            captured_snapshots_list.append(snapshot_path_06)

            # 7. Files Tab (Directory Browser)
            await browser_page_object.click('.tab-button[data-tab="tab-files"]')
            await browser_page_object.wait_for_selector("#file-path-input", timeout=5000)
            await browser_page_object.wait_for_timeout(400)
            snapshot_path_07 = str(AGDS_DIRECTORY_PATH / "07_webagent_files_tab.png")
            await browser_page_object.screenshot(path=snapshot_path_07, full_page=True)
            captured_snapshots_list.append(snapshot_path_07)

            # Close GUI overlay
            await browser_page_object.click("#close-btn")
            await browser_page_object.wait_for_timeout(300)

            # --- Tool 2: JobMaker.py ---
            print(" -> Testing Tool 2: JobMaker.py")
            await browser_page_object.goto(
                jobmaker_target_url, timeout=30000, wait_until="domcontentloaded"
            )
            await browser_page_object.wait_for_selector("#jobName", timeout=10000)
            snapshot_path_08 = str(AGDS_DIRECTORY_PATH / "08_jobmaker_default.png")
            await browser_page_object.screenshot(path=snapshot_path_08, full_page=True)
            captured_snapshots_list.append(snapshot_path_08)

            # Populate JobMaker fields and add tasks
            await browser_page_object.fill("#jobName", "Playwright Verification Audit Job")
            await browser_page_object.fill(
                "#jobGoal",
                "Verify and capture full-screen UI states across webagent.py and JobMaker.py.",
            )
            await browser_page_object.click("#addTaskBtn")
            await browser_page_object.wait_for_timeout(200)
            await browser_page_object.click("#addTaskBtn")
            await browser_page_object.wait_for_timeout(300)
            snapshot_path_09 = str(AGDS_DIRECTORY_PATH / "09_jobmaker_populated.png")
            await browser_page_object.screenshot(path=snapshot_path_09, full_page=True)
            captured_snapshots_list.append(snapshot_path_09)

            await browser_instance.close()

        print("[4/5] Mirroring snapshots & generating 420px responsive screenshots...")
        # Clean up stale CMS files in destinations
        for candidate_stale_path in (
            list(AGDS_DIRECTORY_PATH.glob("*cms*"))
            + list(IMAGES_MIRROR_DIRECTORY_PATH.glob("*cms*"))
            + list(IMAGES_SCREENSHOTS_DIRECTORY_PATH.glob("*cms*"))
        ):
            try:
                candidate_stale_path.unlink()
            except Exception:
                pass

        for raw_snapshot_path_string in captured_snapshots_list:
            source_file_path = Path(raw_snapshot_path_string)
            file_name_string = source_file_path.name

            # Mirror full-resolution copy
            shutil.copy2(source_file_path, IMAGES_MIRROR_DIRECTORY_PATH / file_name_string)

            # Resize to responsive standard width (420px)
            scaled_target_path = IMAGES_SCREENSHOTS_DIRECTORY_PATH / file_name_string
            resize_screenshot_to_responsive_standard(source_file_path, scaled_target_path, 420)

        print(
            f"[5/5] Success! Captured and processed {len(captured_snapshots_list)} snapshots:"
        )
        for snapshot_index_counter, snapshot_file_path_string in enumerate(
            captured_snapshots_list, 1
        ):
            snapshot_file_path = Path(snapshot_file_path_string)
            print(
                f"  {snapshot_index_counter:02d}. {snapshot_file_path.name} "
                f"({snapshot_file_path.stat().st_size} bytes, "
                f"scaled: {(IMAGES_SCREENSHOTS_DIRECTORY_PATH / snapshot_file_path.name).stat().st_size} bytes)"
            )

        return 0

    finally:
        print("Tearing down Flask test servers...")
        for running_server_process in spawned_servers_list:
            try:
                running_server_process.terminate()
                running_server_process.wait(timeout=2)
            except Exception:
                try:
                    running_server_process.kill()
                except Exception:
                    pass

        # Preserve test_web_auth_token_blank shipping hygiene
        try:
            current_configuration_dictionary = config_library.init_config(config_json_file_path)
            current_configuration_dictionary["web_auth_token"] = ""
            config_library.save_config(config_json_file_path, current_configuration_dictionary)
        except Exception:
            pass


if __name__ == "__main__":
    exit_return_code = asyncio.run(execute_playwright_tests())
    sys.exit(exit_return_code)
