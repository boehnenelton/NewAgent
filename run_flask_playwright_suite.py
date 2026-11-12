#!/data/data/com.termux/files/usr/bin/python3
"""
Script:         run_flask_playwright_suite.py
Family:         NewAgent
Description:    Playwright automated test suite for NewAgent Flask tools.
                Starts webagent.py, JobMaker.py, NewAgent_CMS_Admin.py, and
                NewAgent_CMS_Publisher.py on dedicated ports, tests their routes
                and interactive tabs via termux_playwright, captures snapshots,
                and stores them in agds/.
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
Date:           2026-10-24
Version:        1.0.0
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
import urllib.request
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "lib"))

import lib_bejson_newagent_config as config_lib
from termux_playwright import async_playwright_termux, launch

AGDS_DIR = SCRIPT_DIR / "agds"
IMAGES_MIRROR_DIR = SCRIPT_DIR / "images" / "flask_snapshots"

PORT_WEBAGENT = 5181
PORT_JOBMAKER = 5182
PORT_CMS_ADMIN = 5183
PORT_CMS_PUBLISHER = 5184


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def wait_until_responsive(url: str, timeout: float = 20.0, auth_header: str | None = None) -> bool:
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(url)
            if auth_header:
                req.add_header("Authorization", auth_header)
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status in (200, 302):
                    return True
        except urllib.error.HTTPError as http_err:
            if http_err.code in (200, 302, 401):
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


async def execute_playwright_tests() -> int:
    AGDS_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_MIRROR_DIR.mkdir(parents=True, exist_ok=True)

    config_path = SCRIPT_DIR / "config" / "config.json"
    cfg = config_lib.init_config(config_path)
    web_token = config_lib.get_or_create_web_auth_token(config_path, cfg)

    servers: list[subprocess.Popen] = []
    env_base = os.environ.copy()
    env_base["PYTHONUNBUFFERED"] = "1"
    env_base["CMS_USER"] = "admin"
    env_base["CMS_PASSWORD"] = "changeme"

    print("[1/5] Launching Flask tools...")
    # 1. webagent.py
    proc_webagent = subprocess.Popen(
        [sys.executable, str(SCRIPT_DIR / "webagent.py"), "--host", "127.0.0.1", "--port", str(PORT_WEBAGENT)],
        cwd=str(SCRIPT_DIR),
        env=env_base,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    servers.append(proc_webagent)

    # 2. JobMaker.py
    env_jobmaker = env_base.copy()
    env_jobmaker["JOBMAKER_PORT"] = str(PORT_JOBMAKER)
    proc_jobmaker = subprocess.Popen(
        [sys.executable, str(SCRIPT_DIR / "JobMaker.py")],
        cwd=str(SCRIPT_DIR),
        env=env_jobmaker,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    servers.append(proc_jobmaker)

    # 3. NewAgent_CMS_Admin.py
    env_cms_admin = env_base.copy()
    env_cms_admin["CMS_ADMIN_PORT"] = str(PORT_CMS_ADMIN)
    cms_web_dir = SCRIPT_DIR / "tools" / "NA-CMS" / "src" / "web"
    proc_cms_admin = subprocess.Popen(
        [sys.executable, str(cms_web_dir / "NewAgent_CMS_Admin.py")],
        cwd=str(cms_web_dir),
        env=env_cms_admin,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    servers.append(proc_cms_admin)

    # 4. NewAgent_CMS_Publisher.py
    env_cms_pub = env_base.copy()
    env_cms_pub["CMS_PUBLISHER_PORT"] = str(PORT_CMS_PUBLISHER)
    proc_cms_pub = subprocess.Popen(
        [sys.executable, str(cms_web_dir / "NewAgent_CMS_Publisher.py")],
        cwd=str(cms_web_dir),
        env=env_cms_pub,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    servers.append(proc_cms_pub)

    try:
        print("[2/5] Waiting for Flask servers to respond...")
        basic_auth_val = "Basic YWRtaW46Y2hhbmdlbWU="  # admin:changeme

        assert wait_until_responsive(f"http://127.0.0.1:{PORT_WEBAGENT}/?token={web_token}&skip_boot=1"), "webagent timeout"
        assert wait_until_responsive(f"http://127.0.0.1:{PORT_JOBMAKER}/?token={web_token}"), "JobMaker timeout"
        assert wait_until_responsive(f"http://127.0.0.1:{PORT_CMS_ADMIN}/", auth_header=basic_auth_val), "CMS Admin timeout"
        assert wait_until_responsive(f"http://127.0.0.1:{PORT_CMS_PUBLISHER}/", auth_header=basic_auth_val), "CMS Publisher timeout"
        print(" -> All 4 Flask tools are responsive!")

        print("[3/5] Starting Playwright browser in Termux...")
        snapshots_taken: list[str] = []

        async with async_playwright_termux() as playwright_instance:
            browser = await launch(playwright_instance, headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 840})

            # --- Tool 1: webagent.py ---
            print(" -> Testing Tool 1: webagent.py")
            webagent_url = f"http://127.0.0.1:{PORT_WEBAGENT}/?token={web_token}&skip_boot=1"
            await page.goto(webagent_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_selector("#terminal", timeout=10000)
            snap_1 = str(AGDS_DIR / "01_webagent_terminal.png")
            await page.screenshot(path=snap_1, full_page=True)
            snapshots_taken.append(snap_1)

            # Open Settings overlay
            await page.click("#header-settings-btn")
            await page.wait_for_selector("#gui-overlay", state="visible", timeout=5000)

            # Jobs tab
            await page.click('.tab-button[data-tab="tab-jobs"]')
            await page.wait_for_timeout(400)
            snap_2 = str(AGDS_DIR / "02_webagent_jobs_tab.png")
            await page.screenshot(path=snap_2, full_page=True)
            snapshots_taken.append(snap_2)

            # Notes tab
            await page.click('.tab-button[data-tab="tab-notes"]')
            await page.wait_for_selector("#notes-textarea", timeout=5000)
            await page.fill("#notes-textarea", "Playwright verification active -- NewAgent tool suite verified!")
            await page.wait_for_timeout(400)
            snap_3 = str(AGDS_DIR / "03_webagent_notes_tab.png")
            await page.screenshot(path=snap_3, full_page=True)
            snapshots_taken.append(snap_3)

            # Config tab
            await page.click('.tab-button[data-tab="tab-config"]')
            await page.wait_for_timeout(600)
            snap_4 = str(AGDS_DIR / "04_webagent_config_tab.png")
            await page.screenshot(path=snap_4, full_page=True)
            snapshots_taken.append(snap_4)

            # Close GUI overlay
            await page.click("#close-btn")
            await page.wait_for_timeout(300)

            # --- Tool 2: JobMaker.py ---
            print(" -> Testing Tool 2: JobMaker.py")
            jobmaker_url = f"http://127.0.0.1:{PORT_JOBMAKER}/?token={web_token}"
            await page.goto(jobmaker_url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_selector("#jobName", timeout=10000)
            snap_5 = str(AGDS_DIR / "05_jobmaker_default.png")
            await page.screenshot(path=snap_5, full_page=True)
            snapshots_taken.append(snap_5)

            # Populate JobMaker fields and add tasks
            await page.fill("#jobName", "Playwright Automation Audit Job")
            await page.fill("#jobGoal", "Verify and capture multi-tool Flask browser states on Termux.")
            await page.click("#addTaskBtn")
            await page.wait_for_timeout(200)
            await page.click("#addTaskBtn")
            await page.wait_for_timeout(300)
            snap_6 = str(AGDS_DIR / "06_jobmaker_populated.png")
            await page.screenshot(path=snap_6, full_page=True)
            snapshots_taken.append(snap_6)

            # --- Tool 3: NewAgent_CMS_Admin.py ---
            print(" -> Testing Tool 3: NewAgent_CMS_Admin.py")
            admin_ctx = await browser.new_context(
                http_credentials={"username": "admin", "password": "changeme"},
                viewport={"width": 1280, "height": 840},
            )
            admin_page = await admin_ctx.new_page()

            # Dashboard
            await admin_page.goto(f"http://127.0.0.1:{PORT_CMS_ADMIN}/", timeout=30000, wait_until="domcontentloaded")
            await admin_page.wait_for_timeout(600)
            snap_7 = str(AGDS_DIR / "07_cms_admin_dashboard.png")
            await admin_page.screenshot(path=snap_7, full_page=True)
            snapshots_taken.append(snap_7)

            # Pages / Content
            await admin_page.goto(f"http://127.0.0.1:{PORT_CMS_ADMIN}/pages", timeout=30000, wait_until="domcontentloaded")
            await admin_page.wait_for_timeout(600)
            snap_8 = str(AGDS_DIR / "08_cms_admin_pages.png")
            await admin_page.screenshot(path=snap_8, full_page=True)
            snapshots_taken.append(snap_8)

            # Media library
            await admin_page.goto(f"http://127.0.0.1:{PORT_CMS_ADMIN}/media", timeout=30000, wait_until="domcontentloaded")
            await admin_page.wait_for_timeout(600)
            snap_9 = str(AGDS_DIR / "09_cms_admin_media.png")
            await admin_page.screenshot(path=snap_9, full_page=True)
            snapshots_taken.append(snap_9)

            # Interface / Menus
            await admin_page.goto(f"http://127.0.0.1:{PORT_CMS_ADMIN}/menus", timeout=30000, wait_until="domcontentloaded")
            await admin_page.wait_for_timeout(600)
            snap_10 = str(AGDS_DIR / "10_cms_admin_menus.png")
            await admin_page.screenshot(path=snap_10, full_page=True)
            snapshots_taken.append(snap_10)

            # Site Config
            await admin_page.goto(f"http://127.0.0.1:{PORT_CMS_ADMIN}/config", timeout=30000, wait_until="domcontentloaded")
            await admin_page.wait_for_timeout(600)
            snap_11 = str(AGDS_DIR / "11_cms_admin_config.png")
            await admin_page.screenshot(path=snap_11, full_page=True)
            snapshots_taken.append(snap_11)

            await admin_ctx.close()

            # --- Tool 4: NewAgent_CMS_Publisher.py ---
            print(" -> Testing Tool 4: NewAgent_CMS_Publisher.py")
            pub_ctx = await browser.new_context(
                http_credentials={"username": "admin", "password": "changeme"},
                viewport={"width": 1280, "height": 840},
            )
            pub_page = await pub_ctx.new_page()

            # Publisher Dashboard
            await pub_page.goto(f"http://127.0.0.1:{PORT_CMS_PUBLISHER}/", timeout=30000, wait_until="domcontentloaded")
            await pub_page.wait_for_timeout(600)
            snap_12 = str(AGDS_DIR / "12_cms_publisher_dashboard.png")
            await pub_page.screenshot(path=snap_12, full_page=True)
            snapshots_taken.append(snap_12)

            # Publisher Build Console (/publish)
            await pub_page.goto(f"http://127.0.0.1:{PORT_CMS_PUBLISHER}/publish", timeout=30000, wait_until="domcontentloaded")
            await pub_page.wait_for_timeout(600)
            snap_13 = str(AGDS_DIR / "13_cms_publisher_build.png")
            await pub_page.screenshot(path=snap_13, full_page=True)
            snapshots_taken.append(snap_13)

            await pub_ctx.close()
            await browser.close()

        print("[4/5] Mirroring snapshots to images/flask_snapshots/...")
        for snap_path_str in snapshots_taken:
            shutil.copy2(snap_path_str, IMAGES_MIRROR_DIR / Path(snap_path_str).name)

        print(f"[5/5] Success! Captured {len(snapshots_taken)} snapshots in {AGDS_DIR}/:")
        for idx, s in enumerate(snapshots_taken, 1):
            print(f"  {idx:02d}. {Path(s).name} ({Path(s).stat().st_size} bytes)")

        return 0

    finally:
        print("Tearing down Flask test servers...")
        for proc in servers:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        # Preserve test_web_auth_token_blank shipping hygiene
        try:
            curr_cfg = config_lib.init_config(config_path)
            curr_cfg["web_auth_token"] = ""
            config_lib.save_config(config_path, curr_cfg)
        except Exception:
            pass


if __name__ == "__main__":
    rc = asyncio.run(execute_playwright_tests())
    sys.exit(rc)
