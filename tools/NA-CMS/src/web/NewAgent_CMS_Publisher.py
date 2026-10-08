"""
SCRIPT_NAME:    NewAgent_CMS_Publisher
SCRIPT_VERSION: 18.1
RELATIONAL_ID:  5c8a2e1f-9b4d-4f7a-8e3c-1d6b9f2a5c7e
AUTHOR:         Elton Boehnen
CHANGE (2026-09-11): audit V106-04 -- /reset/confirm rmtree'd MFDB_DIR,
DEFAULT_OUT_DIR, EXPORTS_DIR, and UPLOAD_TMP with no backup step, unlike
Admin's equivalent route (F-15). Now mirrors F-15 exactly: zips
site_master/pages_db/assets/standalone_apps into EXPORTS_DIR first, aborts
the whole reset if that backup fails, and excludes EXPORTS_DIR from the
wipe list so the backup survives it.
CHANGE (2026-08-24): Dynamic Skeleton Loader integration. Deleted the
SkeletonBuilder class (270 lines of skeleton HTML baked as Python string
literals, force=True-overwritten from resources/templates/*.html) and
replaced it with lib_bejson_NewAgentCMS_cms_skeletons.py's SkeletonLoader
-- skeleton markup now lives only on disk under
resources/templates/default/ (moved there from the old flat
resources/templates/ layout), with resources/skeleton_registry.json (a
BEJSON 104a document, tag contracts seeded from an actual regex scan of
the real files) as the single source of truth for what's registered and
what {{tags}} each skeleton requires. _read_skel() now routes through
_skeleton_loader.get() with theme-aware resolution and tag-contract
validation (raises SkeletonContractError, caught and logged, rather than
silently shipping a page with a literal unreplaced {{tag}} in it).
_execute() gained a pre-publish validation gate: aborts the build with a
clear per-skeleton error list if any wired-up registered skeleton is
missing a required tag, before touching the filesystem. /publish/regen
(force-regenerate-from-literals) renamed to /publish/reset-theme (a plain
file copy from resources/templates/_factory/default/, never code).
Caught and fixed a real bug during integration testing: the first version
of the pre-publish gate exact-matched the requested theme against
registry rows seeded under theme='default', silently validating zero
skeletons for any other theme name and reporting "clean" even against a
deliberately corrupted file -- fixed to mirror the same theme->default
fallback used by _resolve_path() and SkeletonRegistry.get(), re-verified
with the same sabotage test afterward. See
docs/proposals/Dynamic_Skeleton_Loader-Proposal-V1.docx for the full
design rationale and docs/SKELETON_LOADER.md for the operator how-to.
CHANGE (2026-08-23): BEHTML theme rebuild. Added a new behtml.css theme
(Ry=32px Y-axis quantization, X0-X7 octal lane grid, BEM behtml- namespace,
tri-color palette -- see resources/styles/behtml.css header for full
detail) and set it as the new default site theme (_state["stylesheet"]).
Rewrote all 7 SkeletonBuilder templates (Global/Article/App/Home/Category/
Author/Apps_Feed) to use real behtml-grid__row/behtml-grid__cell BEM
markup: header/footer are quantized to 2*Ry/3*Ry, main-layout is a genuine
75%/25% octal split (X0..X5 content / X6..X7 sidebar) instead of a plain
flex row. Moved Home_Skeleton's/Author_Skeleton's/App_Skeleton's
previously inline per-page <style> blocks and inline element styles into
the shared stylesheet layer (added equivalent .home-hero/.hero-tag/
.author-profile-header/.source-code-block/.behtml-control__button rules to
dark.css and light.css too, using literal-matching values) so BEHTML's
external stylesheet doesn't lose a DOM-source-order cascade fight against
a page-embedded <style> block, and so dark/light themes keep rendering
identically to before this change. Extended _write_default_stylesheets()
to also seed behtml.css on a fresh install (embedded as the new
_BEHTML_CSS literal, kept in exact sync with the file on disk).
CHANGE (2026-08-05): Variable naming remediation pass (Part 2/Part 3 items
13,14,27,31,34,35,36,37,43,44,45) - renamed generic single/short-letter
locals (out, css, env, apps, cats, body, link, text, path, unit, line, cmd)
to self-describing PascalCase names per Sec 3.3. No logic changes.
CHANGE (2026-07-07): Fixed the admin dashboard forcing horizontal scroll.
Root cause: three spots display a raw absolute path (output_dir, SKEL_DIR,
STYLESHEETS_DIR) inside <code> tags with no word-break - a long unbroken
path (no spaces to wrap at) forces its container wider than the viewport.
One of the three is also the last cell in a table row, where a CSS rule
(td:last-child{white-space:nowrap}) actively blocks wrapping regardless of
word-break, so that one needed an inline white-space:normal override too
(inline style beats the external rule). In this sandbox the paths are
short (~30 chars) so the overflow doesn't show, but on the actual Android
deployment (long storage paths, extracted folder names) they're easily
long enough to trigger it - confirmed the mechanism even without
reproducing the visual symptom here.
CHANGE (2026-07-07): Added _generate_excerpt() - pages had no feed summary
because the only description source was an optional meta_description field
nothing in the UI sets, so it was always empty. Falls back to a 30-word
auto-excerpt of the actual page content with a trailing "..." when
truncated. Also fixed app-card images looking zoomed-in/cropped compared
to pages: both used identical object-fit:cover, but app images are
typically square icons vs. pages' wide banners, so cover cropped them
hard. App-type cards now use object-fit:contain instead.
CHANGE (2026-07-07): Removed a 61-line dead _CSS_SHARED assignment (367-427)
that was fully shadowed by a second assignment 8 lines later (475) before
ever being read - confirmed via full-file usage scan, only 2 reads exist
(both after line 475). Also fixed a real bug in the surviving block: the
CSS property "box-box: border-box" is not valid CSS (should be
"box-sizing"), meaning every published site built by this tool had that
line silently do nothing.
DESCRIPTION:    Flask conversion merging:
                  - BEJSON_Web_Publisher.py  (Tkinter GUI removed)
                  - Cleanup_Tool.py          (Tkinter GUI removed)
                  - BEJSON_Skeleton_Builder  (SkeletonBuilder class kept, __main__ block removed)

                HTML Skeleton files (HTML_Skeletons/*.html) stay separate on disk, unchanged.
                Stylesheet files (Stylesheets/*.css) are exported on first launch.
                  - light.css  : default light theme (copy to build your own)
                  - dark.css   : dark theme alternative
                Selected stylesheet is copied to output/style.css on each build.
                BEJSON database structures are never modified.
                Page editing functionality removed — publisher is build-only.

REQUIRES (same directory or on sys.path):
    BEJSON_Standard_Lib.py
    BEJSON_Extended_Lib.py
    HTML_Skeletons/   <- directory of skeleton HTML files
    Stylesheets/      <- auto-created with light.css + dark.css on launch

RUNS ON: http://localhost:5001
"""

import os
import re
import json
import html
import random
import shutil
import threading
import http.server
import socketserver
import subprocess
import zipfile
from datetime import datetime
from flask import Flask, request, redirect, url_for, jsonify, render_template_string

# ==============================================================================
# CLOUDFLARE CONFIG
# ==============================================================================
CF_KEYS = {"ACCOUNT_ID": "", "API_TOKEN": ""}
CF_KEYS_PATH = os.path.expanduser("~/.env/cloudflare_keys.bejson")
if os.path.exists(CF_KEYS_PATH):
    try:
        with open(CF_KEYS_PATH, "r") as f:
            cf_data = json.load(f)
            CF_KEYS = {row[0]: row[1] for row in cf_data["Values"]}
    except Exception:
        pass

# ==============================================================================
# PATHS  (identical to the originals)
# ==============================================================================

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORAGE_ROOT = os.path.join(PROJECT_ROOT, "storage")
MFDB_DIR = os.path.join(STORAGE_ROOT, "mfdb")
MANIFEST_PATH = os.path.join(MFDB_DIR, "site_master", "104a.mfdb.bejson")
PAGES_DB_DIR = os.path.join(MFDB_DIR, "pages_db")
APPS_STORAGE = os.path.join(MFDB_DIR, "standalone_apps")
ASSETS_SRC = os.path.join(MFDB_DIR, "assets")
EXPORTS_DIR = os.path.join(STORAGE_ROOT, "exports")
DEFAULT_OUT_DIR = os.path.join(STORAGE_ROOT, "builds")

# Must match NewAgent_CMS_Shared.py's DEFAULT_FEATURED_IMAGE exactly -- duplicated
# here rather than imported, matching this file's existing standalone-constant
# pattern (it already recomputes PROJECT_ROOT etc. independently rather than
# importing from the blueprint apps). If the seeded default image filename
# ever changes, update it in both places.
DEFAULT_FEATURED_IMAGE = "default_page_image.webp"

RESOURCES_ROOT = os.path.join(PROJECT_ROOT, "resources")
SKEL_DIR = os.path.join(RESOURCES_ROOT, "templates")
STYLESHEETS_DIR = os.path.join(RESOURCES_ROOT, "styles")

for d in [MFDB_DIR, PAGES_DB_DIR, APPS_STORAGE, ASSETS_SRC, EXPORTS_DIR, DEFAULT_OUT_DIR, SKEL_DIR, STYLESHEETS_DIR]:
    os.makedirs(d, exist_ok=True)

# Import BEJSON Libraries
# Import New MFDB Orchestrator
import sys
# (Duplicate PROJECT_ROOT removed by patch_cms.py)
# 2026-08-24: rerouted per NewAgent's shared-vs-tool-specific lib policy.
# Core/shared libs (bejson_core, path_guard, etc.) now come from
# NewAgent's own top-level lib/ instead of a private per-tool copy under
# src/lib -- that copy had drifted stale (path_guard 1.0.0 here vs 1.1.0
# shared, missing a real sibling-directory traversal fix). CMS-specific
# libs (cms_core/cms_mfdb/cms_config/cms_ports/cms_skeletons -- meaningful
# only to this tool, not shared with anything else) moved to
# tools_lib/na-cms/ instead of staying embedded in this tool's own
# folder, per the same policy.
SHARED_LIB_DIR = os.path.normpath(os.path.join(PROJECT_ROOT, "..", "..", "lib"))
TOOL_LIB_DIR = os.path.normpath(os.path.join(PROJECT_ROOT, "..", "..", "tools_lib", "na-cms"))
for _dir in (SHARED_LIB_DIR, TOOL_LIB_DIR):
    if _dir not in sys.path:
        sys.path.append(_dir)
import lib_bejson_NewAgentCMS_cms_core as CMSCore
import lib_bejson_NewAgentCMS_cms_ports as CMSPorts
import lib_bejson_NewAgentCMS_cms_skeletons as CMSSkeletons
from lib_bejson_NewAgentCMS_cms_skeletons import SkeletonContractError

CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")
PUBLISHER_PORT = CMSPorts.get_port(CONFIG_PATH, "publisher_port", "CMS_PUBLISHER_PORT")
SKELETON_REGISTRY_PATH = os.path.join(RESOURCES_ROOT, "skeleton_registry.json")
FACTORY_SKEL_DIR = os.path.join(SKEL_DIR, "_factory", "default")
_skeleton_loader = CMSSkeletons.SkeletonLoader(SKEL_DIR, SKELETON_REGISTRY_PATH)

# ==============================================================================
# FLASK APP
# ==============================================================================

app = Flask(__name__)
db = CMSCore.CMSCore(MANIFEST_PATH)

from NewAgent_CMS_Shared import _check_auth, _unauthorized


@app.before_request
def _enforce_auth_everywhere():
    # SECURITY FIX: this standalone app (factory reset, live publish/build,
    # preview server control) had zero authentication -- every route
    # completely open, including /reset/confirm which wipes the live
    # database. Matches the same before_request gate NewAgent_CMS_Admin.py
    # already enforces on its four blueprints.
    Request_Basic_Auth_Header = request.authorization
    if not Request_Basic_Auth_Header or not _check_auth(Request_Basic_Auth_Header.username, Request_Basic_Auth_Header.password):
        return _unauthorized()


def _safe_slug(value, fallback="unknown"):
    """Guard against None values becoming the literal string 'None' in path components."""
    if value is None or str(value).lower() == "none" or str(value).strip() == "":
        return fallback
    return str(value).strip()

if os.path.exists(MANIFEST_PATH): db.mount()
app.secret_key = os.environ.get('CMS_SECRET_KEY') or os.urandom(24).hex()  # Set CMS_SECRET_KEY env var

# ==============================================================================
# GLOBAL RUNTIME STATE
# ==============================================================================

_state = {
    "output_dir":    DEFAULT_OUT_DIR,
    "build_log":     [],
    "build_running": False,
    "srv_running":   False,
    "srv_port":      8000,
    "httpd":         None,
    "stylesheet":    "behtml.css",
}

# FIX (2026-08-27, audit F-12): _state is read/written from the build
# thread, the preview-server thread, and every Flask request handler
# concurrently. The GIL prevents memory corruption of the dict itself,
# but not logic races: two routes (r_build below, and the Cloudflare
# deploy route further down) each do `if not build_running: set it True`
# -- a classic check-then-act race, not atomic on its own. Two concurrent
# requests could both pass the `if not` check before either sets the
# flag, and both start a build/deploy at once. A lock around just the
# check-and-set itself (not the whole build, which already correctly
# runs in its own background thread outside this lock) is enough to
# close that specific race.
_state_lock = threading.Lock()

# ==============================================================================
# SKELETON LOADER (2026-08-24: replaces the old SkeletonBuilder)
# Skeleton HTML previously lived twice -- as Python string literals here
# AND as files under resources/templates/ -- with a force=True regen
# route that silently overwrote hand-edited files from the literals. That
# two-sources-of-truth pattern is gone: skeleton markup now lives only on
# disk under resources/templates/default/ (or a per-theme override
# folder), resolved and validated through _skeleton_loader
# (lib_bejson_NewAgentCMS_cms_skeletons.py, instantiated near the top of
# this file). See Dynamic_Skeleton_Loader-Proposal-V1.docx for the full
# design rationale and docs/SKELETON_LOADER.md for the operator-facing
# how-to (draft/diff/promote workflow via newagent-manage.py).
# ==============================================================================


# ==============================================================================
# STYLESHEET MANAGER
# Writes light.css and dark.css to Stylesheets/ on first launch.
# Users copy and customise these to build their own themes.
# ==============================================================================

_LIGHT_ROOT = """\
:root {
    --bg-body: #FFFFFF;
    --bg-nav: #FFFFFF;
    --bg-card: #FFFFFF;
    --bg-footer: #F8F9FA;
    --text-main: #121212;
    --text-muted: #555555;
    --accent-color: #DE2626;
    --border-color: #E5E5E5;
    --card-border: #EEEEEE;
    --shadow-hover: 0 10px 30px rgba(0,0,0,0.08);
    --font-main: 'Inter', sans-serif;
    --container-width: 1100px;
    --radius: 0px;
    --code-bg: #F4F4F4;
    --code-text: #111111;
    --img-placeholder: #f0f0f0;
    --social-bg: #FFFFFF;
    --social-border: #DDDDDD;
}
"""

_DARK_ROOT = """\
:root {
    --bg-body: #050505;
    --bg-nav: rgba(10, 10, 10, 0.8);
    --bg-card: #0F0F0F;
    --bg-footer: #080808;
    --text-main: #FFFFFF;
    --text-muted: #888888;
    --accent-color: #DE2626;
    --border-color: #1A1A1A;
    --card-border: #151515;
    --shadow-hover: 0 20px 40px rgba(0,0,0,0.6);
    --font-main: 'Inter', sans-serif;
    --container-width: 1200px;
    --radius: 4px;
    --code-bg: #0A0A0A;
    --code-text: #E0E0E0;
    --img-placeholder: #111111;
    --social-bg: #121212;
    --social-border: #222222;
}
"""

_CSS_SHARED = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: var(--font-main); background-color: var(--bg-body); color: var(--text-main); line-height: 1.6; min-height: 100vh; display: flex; flex-direction: column; font-size: 16px; overflow-x: hidden; -webkit-font-smoothing: antialiased; }
a { color: inherit; text-decoration: none; transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1); }
a:hover { color: var(--accent-color); }
ul { list-style: none; }
img { max-width: 100%; height: auto; display: block; }

.container { width: 100%; max-width: var(--container-width); margin: 0 auto; padding: 0 30px; }

.site-header { background: var(--bg-nav); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); color: var(--text-main); height: 80px; display: flex; align-items: center; position: sticky; top: 0; z-index: 100; border-bottom: 1px solid var(--border-color); }
.nav-wrap { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.logo { font-weight: 900; font-size: 1.6rem; color: var(--text-main); letter-spacing: -1.5px; text-transform: uppercase; }
.logo span { color: var(--accent-color); }
.nav-menu { display: flex; gap: 40px; align-items: center; }
.nav-menu a { color: var(--text-main); font-weight: 700; font-size: 0.85rem; text-transform: uppercase; letter-spacing: 1.5px; opacity: 0.7; }
.nav-menu a:hover { opacity: 1; color: var(--accent-color); }

.nav-dropdown { position: relative; }
.nav-dropdown .chevron { font-size: 0.6rem; margin-left: 5px; opacity: 0.5; vertical-align: middle; }
.dropdown-content { position: absolute; top: 100%; left: 0; background: var(--bg-card); border: 1px solid var(--border-color); min-width: 220px; box-shadow: var(--shadow-hover); opacity: 0; visibility: hidden; transform: translateY(10px); transition: all 0.3s ease; z-index: 1000; padding: 15px 0; border-radius: var(--radius); }
.nav-dropdown:hover .dropdown-content { opacity: 1; visibility: visible; transform: translateY(0); }
.dropdown-content li a { display: block; padding: 10px 25px; font-size: 0.8rem; text-transform: none; opacity: 0.8; letter-spacing: 0.5px; }
.dropdown-content li a:hover { background: rgba(222, 38, 38, 0.1); opacity: 1; color: var(--accent-color); padding-left: 30px; }

.main-layout { display: flex; gap: 60px; margin-top: 40px; }
.main-content { flex: 1; min-width: 0; text-align: left; }
.sidebar { width: 320px; flex-shrink: 0; text-align: left; }

/* Collapsible Sidebar Styles */
.sidebar-collapsible { margin-bottom: 30px; border: 1px solid var(--border-color); border-radius: var(--radius); background: var(--bg-card); overflow: hidden; }
.collapse-trigger { width: 100%; padding: 15px 20px; background: none; border: none; color: var(--accent-color); font-weight: 900; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 2px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; transition: background 0.3s; }
.collapse-trigger:hover { background: rgba(222, 38, 38, 0.05); }
.collapse-trigger .chevron { transition: transform 0.3s ease; font-size: 0.6rem; }
.sidebar-collapsible.active .collapse-trigger .chevron { transform: rotate(180deg); }
.collapse-content { max-height: 0; overflow: hidden; transition: max-height 0.4s cubic-bezier(0, 1, 0, 1); background: var(--bg-body); }
.sidebar-collapsible.active .collapse-content { max-height: 1000px; transition: max-height 0.4s cubic-bezier(1, 0, 1, 0); }
.category-list { padding: 10px 0; }
.category-list li a { display: block; padding: 12px 20px; font-weight: 700; font-size: 0.85rem; border-bottom: 1px solid var(--border-color); opacity: 0.8; }
.category-list li:last-child a { border-bottom: none; }
.category-list a:hover { opacity: 1; color: var(--accent-color); background: rgba(255,255,255,0.02); padding-left: 25px; }

.card { background: var(--bg-card); border: 1px solid var(--card-border); border-radius: var(--radius); display: flex; flex-direction: column; transition: all 0.3s ease; height: 100%; overflow: hidden; text-align: left; }
.card:hover { transform: translateY(-8px); border-color: var(--accent-color); box-shadow: var(--shadow-hover); }
.card-img-container { width: 100%; height: 220px; background: var(--img-placeholder); overflow: hidden; position: relative; border-bottom: 1px solid var(--border-color); }
.card-img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.6s cubic-bezier(0.165, 0.84, 0.44, 1); }
.card:hover .card-img { transform: scale(1.08); }
.card-content { padding: 30px; flex: 1; display: flex; flex-direction: column; }
.card-type { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 2px; color: var(--accent-color); font-weight: 900; margin-bottom: 12px; }
.card h3 { margin-bottom: 12px; font-size: 1.4rem; line-height: 1.2; color: var(--text-main); font-weight: 800; }
.card-meta { margin-top: auto; font-size: 0.8rem; color: var(--text-muted); padding-top: 20px; border-top: 1px solid var(--border-color); display: flex; justify-content: space-between; }

.article-header { margin-bottom: 50px; }
.article-title { font-size: clamp(2.5rem, 6vw, 4rem); line-height: 1; margin-bottom: 20px; color: var(--text-main); font-weight: 900; letter-spacing: -2px; }
.article-meta { color: var(--accent-color); font-size: 0.85rem; font-weight: 800; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 15px; display: block; }
.article-body { font-size: 1.2rem; line-height: 1.8; color: rgba(255,255,255,0.9); }
.article-body h2 { margin-top: 60px; margin-bottom: 25px; font-size: 2.2rem; font-weight: 900; color: #FFF; letter-spacing: -1px; }
.article-body p { margin-bottom: 30px; }

.sidebar-widget { margin-bottom: 50px; }
.widget-title { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 3px; color: var(--accent-color); font-weight: 900; margin-bottom: 25px; display: flex; align-items: center; gap: 15px; }
.widget-title::after { content: ""; height: 1px; background: var(--border-color); flex: 1; }
.category-list li { margin-bottom: 12px; }
.category-list a { display: block; padding: 10px 15px; background: var(--bg-card); border: 1px solid var(--border-color); font-weight: 700; font-size: 0.9rem; border-radius: var(--radius); }
.category-list a:hover { background: var(--accent-color); border-color: var(--accent-color); color: white; transform: translateX(5px); }

.site-footer { background: var(--bg-footer); color: var(--text-muted); padding: 80px 0; border-top: 1px solid var(--border-color); margin-top: auto; }
.footer-content { display: flex; justify-content: space-between; align-items: center; }
.copyright strong { color: var(--text-main); }

.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(350px, 1fr)); gap: 40px; }

@media (max-width: 1024px) {
    .main-layout { flex-direction: column; }
    .sidebar { width: 100%; order: 2; }
}
"""


# BEHTML theme (2026-08-23): Ry=32px quantization, X0-X7 octal grid, BEM
# behtml- namespace, tri-color palette. Self-contained -- unlike
# light.css/dark.css it does not build on a shared _CSS_SHARED block,
# since BEHTML's rules (control-height derivation, octal lane widths,
# tri-color-only palette) are specific enough that sharing would mean
# fighting the shared rules rather than reusing them. Kept in exact sync
# with resources/styles/behtml.css -- if you edit one, edit the other, or
# regenerate this file from that one before shipping.
_BEHTML_CSS = """\
/*
Name:           behtml.css
Description:    BEHTML theme for the published site -- Ry=32px Y-axis
                quantization (Master Spec SS2 / Rules Reference SS3), the
                X0-X7 octal lane grid (Master Spec SS3 / Rules Reference
                SS4), BEM behtml- namespaced components (Rules Reference
                SS6), and the tri-color palette + First Law contrast guard
                (Master Spec SS5 / Rules Reference SS7).
                Existing site classnames (.site-header, .card, .grid,
                .main-layout, etc.) generated by NewAgent_CMS_Publisher.py's
                Python card/sidebar/ad helpers are restyled in place here
                rather than renamed, since renaming them would require
                rewriting those Python generators too -- this stylesheet
                still applies genuine Ry quantization and octal-lane math
                to every one of them. The Global/Home/Category/Author/
                Apps_Feed/Article/App skeleton *markup* (which this
                stylesheet's authors DO fully control) uses real
                .behtml-grid / .behtml-grid__row / .behtml-grid__cell BEM
                blocks throughout.
Version:        1
Date Created:   2026-08-23
Author:         Elton Boehnen
RELATIONAL_ID:  2a7e5c1f-8b4d-4e6a-9f3c-1d8e5a2b7c4f
*/

:root {
    /* ---- Universal Spatial Constant (Rules Reference SS3) ---- */
    --behtml-ry: 32px;
    --behtml-control-pad-y: 2px;
    /* Derived: 32px - (2px * 2) = 28px -- the "28px Paradox" (Master Spec
       SS2.2). A control looks 28px tall but its DOM footprint is still
       exactly 1 * Ry, so the vertical matrix stays unbroken. */
    --behtml-control-h: calc(var(--behtml-ry) - (2 * var(--behtml-control-pad-y)));

    /* ---- Tri-Color Palette (Master Spec SS5 / Rules Reference SS7) ---- */
    --behtml-white: #FFFFFF;
    --behtml-black: #000000;
    --behtml-red:   #DE2626;

    /* Ethereal (mathematical-boundary) vs tangible (physical-object)
       border language -- Master Spec SS5.3. */
    --behtml-ethereal-line: rgba(222, 38, 38, 0.15);
    --behtml-tangible-glow: inset 0 0 8px rgba(222, 38, 38, 0.18),
                            0 0 10px rgba(222, 38, 38, 0.12);

    --font-main: 'Inter', sans-serif;
    --container-width: 1152px; /* 36 * Ry -- not load-bearing, just a nod */
    --radius: 0px; /* BEHTML is orthogonal; no rounded corners in-theme */
    --img-placeholder: #F2F2F2;
}

/* ==============================================================
   BASE / RESET
   ============================================================== */
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: var(--font-main);
    background: var(--behtml-white);
    color: var(--behtml-black);
    line-height: 1.6;
    min-height: 100vh;
    display: flex; flex-direction: column;
    font-size: 16px;
    overflow-x: hidden;
    -webkit-font-smoothing: antialiased;
}
a { color: inherit; text-decoration: none; transition: color 0.2s ease; }
a:hover { color: var(--behtml-red); }
ul { list-style: none; }
/* iframe included alongside these per the 2026-08-23 width-containment
   fix -- see CHANGELOG / .bejson_project.json. */
img, pre, code, table, div, iframe { max-width: 100% !important; }
img { height: auto !important; display: block; }
pre, code, table, div, iframe { overflow-x: auto; }
iframe { display: block; }

.container { width: 100%; max-width: var(--container-width); margin: 0 auto; padding: 0 30px; }

/* ==============================================================
   BEHTML GRID PRIMITIVES (Rules Reference SS4, SS6)
   .behtml-grid       Block -- the root spatial boundary
   .behtml-grid__row  Element -- one Y-axis row, height = k * Ry
   .behtml-grid__cell Element -- one or more of the 8 X-lanes
   Modifiers below are exhaustive per the octal table in the Master Spec.
   ============================================================== */
.behtml-grid { width: 100%; }
.behtml-grid__row {
    display: flex;
    width: 100%;
    min-height: var(--behtml-ry);
    position: relative;
}
.behtml-grid__row--2r { min-height: calc(var(--behtml-ry) * 2); }
.behtml-grid__row--3r { min-height: calc(var(--behtml-ry) * 3); }
.behtml-grid__row--4r { min-height: calc(var(--behtml-ry) * 4); }
.behtml-grid__row--6r { min-height: calc(var(--behtml-ry) * 6); }

.behtml-grid__cell { display: flex; align-items: center; min-width: 0; overflow-x: auto; }
.behtml-grid__cell--w-12-5 { width: 12.5%; }
.behtml-grid__cell--w-25   { width: 25%; }
.behtml-grid__cell--w-37-5 { width: 37.5%; }
.behtml-grid__cell--w-50   { width: 50%; }
.behtml-grid__cell--w-62-5 { width: 62.5%; }
.behtml-grid__cell--w-75   { width: 75%; }
.behtml-grid__cell--w-100  { width: 100%; }

/* Ethereal row/column guides -- dotted, mathematical-boundary-only.
   Applied only where explicitly opted in via --ethereal, never globally,
   since a public content site drowning in visible grid lines would hurt
   readability -- Master Spec SS5.3 describes this as an IDE/debug
   convention, used here sparingly as a visual signature instead. */
.behtml-grid__row--ethereal { border-bottom: 1px dashed var(--behtml-ethereal-line); }

/* Tangible / "live" state -- solid glowing red outline, Master Spec SS5.3 */
.behtml-is-active,
.behtml-grid__cell--active-column {
    outline: 2px solid var(--behtml-red);
    box-shadow: var(--behtml-tangible-glow);
}

/* ==============================================================
   BEHTML CONTROL PRIMITIVES (Master Spec SS2.2, Rules Reference SS6)
   ============================================================== */
.behtml-control {
    height: var(--behtml-control-h);
    display: inline-flex; align-items: center;
}
.behtml-control__button {
    height: var(--behtml-control-h);
    padding: 0 16px;
    border: 1px solid var(--behtml-black);
    background: var(--behtml-white);
    color: var(--behtml-black);
    font-weight: 700;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    cursor: pointer;
    display: inline-flex; align-items: center; justify-content: center;
}
.behtml-control__button:hover { border-color: var(--behtml-red); color: var(--behtml-red); }
/* First Law (Rules Reference SS7): a red background NEVER carries black
   text -- always white. */
.behtml-control__button--accent {
    background: var(--behtml-red);
    border-color: var(--behtml-red);
    color: var(--behtml-white);
}
.behtml-control__button--accent:hover { background: var(--behtml-black); border-color: var(--behtml-black); color: var(--behtml-white); }

/* ==============================================================
   SITE HEADER -- 2*Ry (64px), Primary Dark (Master Spec SS5.1: black is
   "the structural anchor for toolbars, headers").
   ============================================================== */
.site-header {
    background: var(--behtml-black);
    color: var(--behtml-white);
    height: calc(var(--behtml-ry) * 2);
    display: flex; align-items: center;
    position: sticky; top: 0; z-index: 100;
    border-bottom: 2px dashed var(--behtml-ethereal-line);
}
.nav-wrap { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.logo { font-weight: 900; font-size: 1.4rem; color: var(--behtml-white); letter-spacing: -1px; text-transform: uppercase; }
.logo span { color: var(--behtml-red); }
.nav-menu { display: flex; height: 100%; gap: 4px; align-items: center; }
.nav-menu > li { height: 100%; display: flex; align-items: center; }
.nav-menu a {
    display: flex; align-items: center; height: var(--behtml-control-h);
    padding: 0 14px;
    color: var(--behtml-white);
    font-weight: 700; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 1px;
    opacity: 0.85;
}
.nav-menu a:hover { opacity: 1; color: var(--behtml-red); }

.nav-dropdown { position: relative; height: 100%; }
.nav-dropdown .chevron { font-size: 0.6rem; margin-left: 6px; opacity: 0.6; }
.dropdown-content {
    position: absolute; top: 100%; left: 0;
    background: var(--behtml-black);
    border: 1px solid var(--behtml-red);
    min-width: 220px;
    opacity: 0; visibility: hidden; transform: translateY(6px);
    transition: all 0.2s ease;
    z-index: 1000;
}
.nav-dropdown:hover .dropdown-content { opacity: 1; visibility: visible; transform: translateY(0); }
.dropdown-content li a {
    display: flex; align-items: center; height: var(--behtml-ry);
    padding: 0 20px; font-size: 0.78rem; text-transform: none; opacity: 0.85; letter-spacing: 0.4px;
    color: var(--behtml-white);
}
.dropdown-content li a:hover { background: rgba(222, 38, 38, 0.15); opacity: 1; color: var(--behtml-white); }

.mobile-menu-toggle { display: none; background: none; border: none; color: var(--behtml-white); font-size: 1.4rem; cursor: pointer; }

/* ==============================================================
   MAIN LAYOUT -- octal split: content = X0..X5 (75%), sidebar = X6..X7
   (25%). Rules Reference SS4 percentage table, applied at page scale.
   ============================================================== */
.main-layout {
    display: flex;
    width: 100%;
    max-width: var(--container-width);
    margin: 0 auto;
    gap: 0;
    align-items: flex-start;
    border-left: 2px dashed var(--behtml-ethereal-line);
    border-right: 2px dashed var(--behtml-ethereal-line);
}
.main-content {
    width: 75%; /* X0..X5 */
    min-width: 0;
    padding: calc(var(--behtml-ry) * 1.25) calc(var(--behtml-ry)) ;
    text-align: left;
    border-right: 1px dashed var(--behtml-ethereal-line);
}
.sidebar {
    width: 25%; /* X6..X7 */
    flex-shrink: 0;
    text-align: left;
    padding: calc(var(--behtml-ry) * 1.25) var(--behtml-ry);
}

/* Collapsible sidebar sections -- each trigger is exactly 1*Ry tall */
.sidebar-collapsible { margin-bottom: var(--behtml-ry); border: 1px solid var(--behtml-black); }
.collapse-trigger {
    width: 100%; height: var(--behtml-ry);
    padding: 0 16px;
    background: var(--behtml-black); color: var(--behtml-white);
    border: none;
    font-weight: 800; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 2px;
    display: flex; justify-content: space-between; align-items: center;
    cursor: pointer;
}
.collapse-trigger:hover { color: var(--behtml-red); }
.collapse-trigger .chevron { transition: transform 0.25s ease; font-size: 0.6rem; }
.sidebar-collapsible.active .collapse-trigger .chevron { transform: rotate(180deg); }
.collapse-content { max-height: 0; overflow: hidden; transition: max-height 0.3s ease; background: var(--behtml-white); }
.sidebar-collapsible.active .collapse-content { max-height: 1200px; }
.category-list li a {
    display: flex; align-items: center; height: var(--behtml-ry);
    padding: 0 16px; font-weight: 700; font-size: 0.85rem;
    border-bottom: 1px dashed var(--behtml-ethereal-line);
}
.category-list li:last-child a { border-bottom: none; }
.category-list a:hover { color: var(--behtml-red); padding-left: 20px; }

/* Sidebar widgets (ad block, etc.) */
.sidebar-widget { margin-bottom: calc(var(--behtml-ry) * 1.5); }
.widget-title {
    height: var(--behtml-ry); display: flex; align-items: center; gap: 12px;
    font-size: 0.72rem; text-transform: uppercase; letter-spacing: 2px; font-weight: 900; color: var(--behtml-red);
}
.widget-title::after { content: ""; height: 1px; background: var(--behtml-black); flex: 1; }

/* ==============================================================
   CARDS -- fixed chrome pieces quantized to Ry multiples; the flexible
   prose/title area inside is left fluid (Master Spec SS2 governs
   *structural* nodes -- headers, dividers, controls -- not arbitrarily
   flowing body text).
   ============================================================== */
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: calc(var(--behtml-ry) * 0.75);
}
.card {
    background: var(--behtml-white);
    border: 1px solid var(--behtml-black);
    display: flex; flex-direction: column;
    height: 100%; overflow: hidden; text-align: left;
    transition: box-shadow 0.2s ease, border-color 0.2s ease;
}
.card:hover { border-color: var(--behtml-red); box-shadow: var(--behtml-tangible-glow); }
/* 6 * Ry = 192px -- a quantized banner height instead of an arbitrary 220px */
.card-img-container { width: 100%; height: calc(var(--behtml-ry) * 6); background: var(--img-placeholder); overflow: hidden; position: relative; border-bottom: 1px solid var(--behtml-black); }
.card-img { width: 100%; height: 100%; object-fit: cover; transition: transform 0.5s ease; }
.card:hover .card-img { transform: scale(1.05); }
.card-content { padding: var(--behtml-ry); flex: 1; display: flex; flex-direction: column; }
/* card-type label row: 1 * Ry */
.card-type { height: var(--behtml-ry); display: flex; align-items: center; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 2px; color: var(--behtml-red); font-weight: 900; }
.card h3 { margin: 4px 0 12px; font-size: 1.3rem; line-height: 1.2; font-weight: 800; }
.card-desc { flex: 1; }
/* card-meta footer row: 1 * Ry */
.card-meta { height: var(--behtml-ry); margin-top: auto; font-size: 0.78rem; color: #555; display: flex; align-items: center; justify-content: space-between; border-top: 1px dashed var(--behtml-ethereal-line); }

/* ==============================================================
   ARTICLE / CONTENT BODY
   ============================================================== */
.article-header { margin-bottom: calc(var(--behtml-ry) * 1.5); border-bottom: 2px dashed var(--behtml-ethereal-line); padding-bottom: var(--behtml-ry); }
/* article-meta row quantized to 1*Ry regardless of font metrics */
.article-meta { height: var(--behtml-ry); display: flex; align-items: center; color: var(--behtml-red); font-size: 0.82rem; font-weight: 800; text-transform: uppercase; letter-spacing: 2px; }
.article-title { font-size: clamp(2.2rem, 5vw, 3.6rem); line-height: 1.05; margin: 4px 0; font-weight: 900; letter-spacing: -1.5px; }
.article-body { font-size: 1.15rem; line-height: 1.8; }
.article-body h2 { margin-top: calc(var(--behtml-ry) * 1.5); margin-bottom: var(--behtml-ry); font-size: 2rem; font-weight: 900; letter-spacing: -0.5px; }
.article-body p { margin-bottom: var(--behtml-ry); }
.article-body a { color: var(--behtml-red); text-decoration: underline; }

/* ==============================================================
   HOME HERO
   ============================================================== */
.home-hero {
    padding: calc(var(--behtml-ry) * 3) 0 calc(var(--behtml-ry) * 2);
    text-align: left;
    border-bottom: 2px dashed var(--behtml-ethereal-line);
    margin-bottom: calc(var(--behtml-ry) * 1.5);
}
/* hero-tag chip: exactly 1*Ry tall */
.hero-tag {
    display: inline-flex; align-items: center; height: var(--behtml-ry);
    padding: 0 14px;
    background: var(--behtml-red); color: var(--behtml-white);
    font-size: 0.68rem; font-weight: 900; text-transform: uppercase; letter-spacing: 2px;
    margin-bottom: calc(var(--behtml-ry) * 0.75);
}
.hero-title { font-size: clamp(2.6rem, 7vw, 5.2rem); font-weight: 900; line-height: 0.95; letter-spacing: -3px; margin-bottom: var(--behtml-ry); }
.hero-desc { font-size: 1.3rem; color: #444; max-width: 700px; line-height: 1.4; }

.section-divider { display: flex; align-items: center; gap: 16px; height: var(--behtml-ry); margin-bottom: var(--behtml-ry); }
.section-label { font-size: 0.75rem; font-weight: 900; text-transform: uppercase; letter-spacing: 3px; color: var(--behtml-red); white-space: nowrap; }
.label-line { height: 1px; background: var(--behtml-black); flex: 1; }

/* ==============================================================
   FOOTER -- 3*Ry (96px), the exact "3-row block" callback from the
   Starter example in the Consolidated Reference.
   ============================================================== */
.site-footer {
    background: var(--behtml-black); color: rgba(255,255,255,0.7);
    min-height: calc(var(--behtml-ry) * 3);
    display: flex; align-items: center;
    border-top: 2px dashed var(--behtml-ethereal-line);
    margin-top: auto;
}
.footer-content { display: flex; justify-content: space-between; align-items: center; width: 100%; flex-wrap: wrap; gap: 12px; }
.copyright strong { color: var(--behtml-white); }
.footer-links a { color: rgba(255,255,255,0.7); }
.footer-links a:hover { color: var(--behtml-red); }

/* ==============================================================
   AUTHOR PROFILE / APP DOC BLOCKS
   ============================================================== */
.author-profile-header {
    text-align: center; padding: calc(var(--behtml-ry) * 1.5) var(--behtml-ry);
    background: var(--behtml-black); color: var(--behtml-white);
    margin-bottom: calc(var(--behtml-ry) * 1.5);
    border-bottom: 4px solid var(--behtml-red);
}
.author-profile-header img { margin: 0 auto var(--behtml-ry); border: 2px solid var(--behtml-red); }
.author-profile-header h1 { font-size: 2.2rem; font-weight: 900; margin: var(--behtml-ry) 0 12px; }
.author-profile-header p { max-width: 600px; margin: 0 auto; color: rgba(255,255,255,0.8); }
.section-heading {
    height: var(--behtml-ry); display: flex; align-items: center;
    margin-bottom: var(--behtml-ry); color: var(--behtml-red); font-weight: 900;
    text-transform: uppercase; letter-spacing: 2px; font-size: 0.9rem;
}
.source-code-block {
    background: var(--behtml-white); border: 1px solid var(--behtml-black);
    padding: var(--behtml-ry); margin-bottom: calc(var(--behtml-ry) * 1.25);
}
.source-code-block h3 { margin-bottom: calc(var(--behtml-ry) * 0.5); font-size: 1rem; text-transform: uppercase; letter-spacing: 1px; }
.source-code-block textarea {
    width: 100%; height: calc(var(--behtml-ry) * 5);
    background: var(--behtml-white); border: 1px solid #ccc;
    padding: 12px; font-family: monospace; font-size: 0.85rem;
}

/* ==============================================================
   LIGHTBOX
   ============================================================== */
.lightbox { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.92); z-index: 2000; align-items: center; justify-content: center; }
.lightbox-content { max-width: 90vw; max-height: 90vh; object-fit: contain; border: 2px solid var(--behtml-red); }
.lightbox-close { position: absolute; top: var(--behtml-ry); right: var(--behtml-ry); color: var(--behtml-white); font-size: 2rem; cursor: pointer; }

/* ==============================================================
   RESPONSIVE
   BEHTML's Y-axis quantum (Ry) and X-axis octal percentages are both
   scale-invariant by design (Master Spec SS2/SS3), so nothing here
   needs to change at narrow widths *except* collapsing the two-column
   octal split back to a single 100%-wide stack -- a mobile viewport
   physically cannot host a readable 25%-wide sidebar column.
   ============================================================== */
@media (max-width: 1024px) {
    .main-layout { flex-direction: column; border-left: none; border-right: none; }
    .main-content, .sidebar { width: 100%; padding-left: var(--behtml-ry); padding-right: var(--behtml-ry); }
    .main-content { border-right: none; border-bottom: 1px dashed var(--behtml-ethereal-line); }
    .sidebar { order: 2; }
    .nav-menu { display: none; }
    .mobile-menu-toggle { display: block; }
    .nav-menu.active { display: flex; flex-direction: column; position: absolute; top: 100%; left: 0; width: 100%; background: var(--behtml-black); height: auto; }
    .nav-menu.active > li { height: var(--behtml-ry); width: 100%; }
    .nav-menu.active a { width: 100%; }
}
"""


def _write_default_stylesheets():
    """Write light.css, dark.css, and behtml.css to Stylesheets/ only if
    they don't already exist."""
    os.makedirs(STYLESHEETS_DIR, exist_ok=True)
    light_path  = os.path.join(STYLESHEETS_DIR, "light.css")
    dark_path   = os.path.join(STYLESHEETS_DIR, "dark.css")
    behtml_path = os.path.join(STYLESHEETS_DIR, "behtml.css")
    if not os.path.exists(light_path):
        with open(light_path, 'w', encoding='utf-8') as f:
            f.write(_LIGHT_ROOT + _CSS_SHARED)
        print(f"[STYLESHEETS] Written: {light_path}")
    if not os.path.exists(dark_path):
        with open(dark_path, 'w', encoding='utf-8') as f:
            f.write(_DARK_ROOT + _CSS_SHARED)
        print(f"[STYLESHEETS] Written: {dark_path}")
    if not os.path.exists(behtml_path):
        with open(behtml_path, 'w', encoding='utf-8') as f:
            f.write(_BEHTML_CSS)
        print(f"[STYLESHEETS] Written: {behtml_path}")


def _list_stylesheets():
    """Return list of .css filenames from STYLESHEETS_DIR."""
    if not os.path.exists(STYLESHEETS_DIR):
        return []
    return sorted(f for f in os.listdir(STYLESHEETS_DIR) if f.endswith('.css'))


# ==============================================================================
# WEB PUBLISHER — build helpers
# Ported verbatim from BEJSON_Web_Publisher.WebPublisher methods.
# ==============================================================================

def _log(msg):
    Formatted_Log_Line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    _state["build_log"].append(Formatted_Log_Line)
    # FIX (2026-08-29, audit F-28): the /publish/log endpoint only ever
    # sliced the last 300 entries for its own response -- the underlying
    # list itself was never trimmed, so it grew for the entire life of
    # the process across every build ever run. Trimmed here at the
    # append site itself (every log line goes through this one function)
    # rather than only at read time, so the unbounded-growth path is
    # closed regardless of how build_log is read from elsewhere.
    _BUILD_LOG_MAX_LINES = 1000
    if len(_state["build_log"]) > _BUILD_LOG_MAX_LINES:
        del _state["build_log"][: len(_state["build_log"]) - _BUILD_LOG_MAX_LINES]
    print(Formatted_Log_Line)


def _apply_tags(html, tags):
    # FIX (2026-08-30, audit F-24): sequential str.replace() calls, one
    # tag at a time, meant the ORDER tags happened to iterate in
    # determined whether a value substituted early could itself contain
    # literal {{another_tag}} text that a later iteration would then
    # replace again -- e.g. a blog post's own html_body containing the
    # literal text "{{site_title}}" (writing about templating syntax,
    # a pasted code example, anything) would get silently corrupted into
    # the actual site title if site_title's replace() ran after
    # article_body's. A single-pass regex substitution, matching every
    # known tag name in ONE expression, processes the ORIGINAL string
    # exactly once: each {{tag}} in the source is looked up and replaced
    # a single time, and the replacement text itself is never re-scanned
    # for further {{tag}} occurrences, regardless of what it contains or
    # what order the tags dict happens to iterate in.
    if not html: return ""
    if not tags: return html
    pattern = re.compile("|".join(r"\{\{" + re.escape(k) + r"\}\}" for k in tags))
    def _resolve(match):
        k = match.group(0)[2:-2]
        v = tags.get(k)
        return str(v) if v is not None and v != "None" else ""
    return pattern.sub(_resolve, html)

def _current_theme_name():
    """Derives the skeleton theme name from the active stylesheet choice
    (e.g. 'behtml.css' -> 'behtml'), so a per-theme skeleton override
    folder (resources/templates/<theme>/) lines up naturally with
    whichever .css file is selected. No such folder exists for any theme
    yet -- every theme currently falls back to the shared
    resources/templates/default/ set, exactly as designed (Proposal
    §3.1): dropping a file into resources/templates/behtml/ is all a
    future genuine per-theme override needs."""
    stylesheet = _state.get("stylesheet", "default.css")
    return stylesheet[:-4] if stylesheet.endswith(".css") else stylesheet

def _read_skel(name):
    """Routed through SkeletonLoader (lib_bejson_NewAgentCMS_cms_skeletons.py)
    instead of a direct file read. name is passed with its .html suffix
    by every call site (unchanged calling convention); the loader's
    registry keys skeletons without the suffix, so it's stripped here.
    Raises SkeletonContractError -- caught below -- if the resolved file
    is missing a {{tag}} its registry entry requires, so a broken
    skeleton is reported clearly instead of silently shipping a page with
    a literal unreplaced {{tag}} in it.

    FIX (2026-08-31, audit F-45): the pre-publish validation gate in
    _execute() already catches this for every REGISTERED skeleton before
    a build starts -- but a skeleton that was never registered at all
    (a new file dropped in without a matching registry entry) bypasses
    that gate entirely and can only be caught here, mid-render. This
    fallback used to just log a line and return an invisible HTML
    comment -- the build still printed "Build Complete!" as if nothing
    was wrong, and the only trace was buried in the build log. Now also
    increments _state['build_had_skeleton_errors'], which _execute()
    checks at the end to report the build as failed/broken instead of
    silently successful, even for this narrower not-yet-registered case
    the pre-publish gate can't see.
    """
    skeleton_name = name[:-5] if name.endswith(".html") else name
    theme = _current_theme_name()
    try:
        return _skeleton_loader.get(theme, skeleton_name)
    except SkeletonContractError as e:
        _log(f"SKELETON CONTRACT ERROR: {e}")
        _state["build_had_skeleton_errors"] = _state.get("build_had_skeleton_errors", 0) + 1
        return f"<!-- SKELETON CONTRACT ERROR: {e} -->"
    except (OSError, IOError) as e:
        _log(f"SKELETON READ ERROR for {name}: {e}")
        _state["build_had_skeleton_errors"] = _state.get("build_had_skeleton_errors", 0) + 1
        return "<body>Skeleton Missing</body>"

def _get_sidebar_html(categories, rel_prefix):
    html = ""
    for c in categories:
        c_name = c.get('cat_name')
        c_slug = c.get('cat_slug')
        if c_name and c_slug:
            html += f'<li><a href="{rel_prefix}category/{c_slug}/index.html">{c_name}</a></li>'
    return html

def _generate_excerpt(html_content, word_limit=30):
    """Plain-text excerpt from an HTML body: strips tags, collapses
    whitespace, takes the first word_limit words, adds a trailing ellipsis
    if it was actually truncated. Used as the feed-card summary for pages,
    which (unlike apps) have no dedicated description field of their own."""
    if not html_content:
        return ""
    Stripped_Excerpt_Text = re.sub(r'<[^>]+>', ' ', html_content)   # strip tags
    Stripped_Excerpt_Text = re.sub(r'\s+', ' ', Stripped_Excerpt_Text).strip()        # collapse whitespace
    words = Stripped_Excerpt_Text.split(' ')
    if len(words) <= word_limit:
        return Stripped_Excerpt_Text
    return ' '.join(words[:word_limit]) + '...'


def _generate_card_html(item, link, target_attr, label, p_date, p_auth, rel_prefix, desc=""):
    f_img = item.get('page_featured_img')
    fallback_url = f"{rel_prefix}assets/{DEFAULT_FEATURED_IMAGE}"

    # FIX (2026-08-25, audit F-07): page_title and desc are user-controlled
    # (typed into the admin's page-title/description fields) and were being
    # inserted into this published-static-site HTML with zero escaping --
    # a title of e.g. `<img src=x onerror=alert(1)>` executed in every
    # visitor's browser. html.escape() covers both element-text-content and
    # attribute-value contexts (its default quote=True also escapes quote
    # characters). link/f_img/fallback_url/label/p_date are not
    # user-controlled text (UUID-based stored filenames, hardcoded caller
    # labels, formatted dates) and don't need this.
    safe_title = html.escape(item.get("page_title", ""))
    safe_desc = html.escape(desc) if desc else ""

    # App images are typically square-ish icons/logos, not wide banners like
    # page featured images - object-fit:cover on a square source inside this
    # wide, short card container crops/zooms in hard and can lose the subject
    # entirely. Apps get object-fit:contain instead, so the whole icon is
    # visible (letterboxed against the container background) rather than
    # cropped.
    img_fit_style = "object-fit:contain; background:var(--img-placeholder);" if label == "APP" else ""

    if f_img:
        img_path = f"{rel_prefix}assets/{f_img}"
        img_html = f'<div class="card-img-container"><img src="{img_path}" class="card-img" style="{img_fit_style}" alt="{safe_title}" onerror="this.src=\'{fallback_url}\'"></div>'
    else:
        # Automatically generate text canvas image when no image is assigned
        img_html = f'<div class="card-img-container"><img src="{fallback_url}" class="card-img" style="{img_fit_style}" alt="{safe_title}"></div>'

    desc_html = f'<p class="card-desc" style="font-size:0.85rem; color:var(--text-muted); margin-top:10px; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;">{safe_desc}</p>' if safe_desc else ""

    return f"""<a href="{link}" class="card"{target_attr}>{img_html}<div class="card-content"><span class="card-type">{label}</span><h3>{safe_title}</h3>{desc_html}<div class="card-meta">{p_date}</div></div></a>"""
def _generate_ad_block(ad_units, rel_prefix, zone="sidebar"):
    # BUG FIX: this used to pick a random active ad regardless of ad_zone,
    # even though the admin UI (site/ads) lets you assign header/footer/sidebar
    # per ad and shows a per-zone "Ad Zones Summary" -- the zone was collected
    # and displayed but never actually used to filter placement. This is only
    # ever called for the sidebar widget slot (no header/footer slot exists in
    # any skeleton), so it now filters to zone="sidebar" ads specifically,
    # matching where it's actually rendered.
    active = [a for r in ad_units if (a := r).get('ad_active') and a.get('ad_zone', 'sidebar') == zone]
    if not active: return ""
    Selected_Ad_Unit = random.choice(active)
    return f'''
    <div class="sidebar-widget ad-widget">
        <h3 class="widget-title">Sponsored</h3>
        <a href="{Selected_Ad_Unit.get('ad_target_url', '#')}" target="_blank">
            <img src="{rel_prefix}assets/{Selected_Ad_Unit.get('ad_banner_url')}" style="width:100%; height:auto;">
        </a>
    </div>'''

def _write_sitemap_and_robots(output_dir, base_url, feed_items, categories):
    """Writes sitemap.xml + robots.txt to the build output. New in pkg75 --
    previously neither existed anywhere in the build (confirmed absent in
    the pre-pkg75 feature audit). Called once at the end of _execute(), after
    every page/category/app/home file is already on disk, so nothing here
    can point at a URL that doesn't actually resolve on the published site.
    """
    def _esc(s):
        return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    base = base_url.rstrip("/")
    urls = [(base + "/", None)]                              # home
    urls.append((f"{base}/apps/", None))                     # apps feed
    for cat in categories:
        c_slug = cat.get("cat_slug") or "uncategorized"
        urls.append((f"{base}/category/{c_slug}/", None))

    for x in feed_items:
        if x["type"] not in ("page", "app"):
            continue                                          # external_link points off-site, not our URL to index
        link = x["link"]
        if link.endswith("index.html"):
            link = link[: -len("index.html")]                 # directory-style clean URL to match how these
        urls.append((f"{base}/{link}", x.get("date")))        # actually resolve on a static host

    sitemap_entries = []
    for loc, lastmod in urls:
        lastmod_tag = f"<lastmod>{_esc(lastmod)}</lastmod>" if lastmod else ""
        sitemap_entries.append(f"  <url><loc>{_esc(loc)}</loc>{lastmod_tag}</url>")

    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(sitemap_entries) + "\n"
        "</urlset>\n"
    )
    with open(os.path.join(output_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap_xml)

    robots_txt = (
        "User-agent: *\n"
        "Allow: /\n\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    with open(os.path.join(output_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(robots_txt)


def _generate_related_block(items, current_item, default_author, categories):
    rel_cat = current_item.get('page_cat_name')
    related = [i for i in items if i.get('page_cat_name') == rel_cat and i.get('page_uuid') != current_item.get('page_uuid')]
    if not related: return ""
    
    # FIX (2026-08-31, audit F-41): random.shuffle() (the shared, unseeded
    # global RNG) meant the same page's "Related Content" picks came out
    # in a different order -- sometimes a different SET of 3 entirely --
    # on every single rebuild of the identical database. For a static
    # site generator, two builds of the same source data should produce
    # byte-identical output; this broke that for every page with more
    # than 3 related candidates, which in turn breaks diffing a rebuild
    # against the previous deploy to verify nothing else changed.
    # random.choice() at the ad-rotation call site above this function is
    # NOT touched -- that one's non-determinism is the actual intended
    # behavior (rotating which ad shows), so a local, separately-seeded
    # random.Random instance is used here instead of reseeding the
    # shared global `random` module, which would have made THAT call
    # deterministic too as an unwanted side effect.
    # Seeded by the current page's own UUID: stable across rebuilds of
    # the same page, but still varies page-to-page so every page's
    # related section doesn't look identically ordered.
    seed = current_item.get('page_uuid') or rel_cat or ""
    random.Random(seed).shuffle(related)
    selected = related[:3]
    
    grid_html = ""
    for s in selected:
        cat_obj  = next((c for c in categories if c.get('cat_name') == s.get('page_cat_name')), None)
        cat_slug = cat_obj['cat_slug'] if cat_obj and cat_obj.get('cat_slug') else "uncategorized"
        itype = s.get('page_type', 'page')
        # This is used in Article_Skeleton which is at itype/cat/slug/index.html (3 levels deep)
        Generated_Page_Permalink = f"../../../{itype}/{cat_slug}/{s['page_slug']}/index.html"
        p_date = s.get('page_created_at') or ""
        grid_html += _generate_card_html(s, Generated_Page_Permalink, "", itype.upper(), p_date, default_author, "../../../")
        
    return f"""
    <hr style="border:0; border-top:1px solid #eee; margin:40px 0;">
    <h3 style="margin-bottom:20px; font-weight:800; color:#333;">Related Content</h3>
    <div class="grid">{grid_html}</div>
    """

def _execute():
    """
    Robust build execution using unified tag resolution.
    """
    _log("Initializing Build...")
    _state["build_had_skeleton_errors"] = 0

    # Pre-publish validation gate (Proposal §3.4 / Suggestion #6): refuse
    # to publish if any *wired-up* registered skeleton for the active
    # theme is missing a required {{tag}} -- reported per-file instead of
    # silently shipping a page with a literal unreplaced tag in it.
    theme = _current_theme_name()
    failures = {
        (t, n): missing
        for (t, n), missing in _skeleton_loader.validate_all(theme=theme).items()
        if (_skeleton_loader.registry.get(t, n) or {}).get("wired_up", True)
    }
    if failures:
        for (t, n), missing in failures.items():
            _log(f"SKELETON VALIDATION FAILED: {n} ({t}) missing tags: {missing}")
        _log("Build aborted -- fix the skeleton(s) above and try again.")
        return

    output_dir = _state["output_dir"]

    if not os.path.exists(MANIFEST_PATH):
        _log("ERROR: Master DB missing.")
        return

    # FIX (2026-08-27, audit F-14): this used to only ever ADD to
    # output_dir -- nothing removed a page/category/app directory that no
    # longer has a live source record. Delete a page in the CMS, rebuild,
    # and its old HTML survived forever in storage/builds/, indefinitely
    # accumulating "ghost pages" a visitor could still stumble onto by
    # direct URL.
    #
    # A cleanup step naming just "page/category/apps" wouldn't actually
    # be complete: target_dir for an individual page is built from
    # item["page_type"] (`os.path.join(output_dir, itype, cat_slug,
    # slug)`), which can be "page", "video", "document", or any future
    # polymorphic type -- a hardcoded list of "known" top-level folder
    # names would miss a ghost directory from a page type that used to
    # exist but doesn't get generated by this build (e.g. the last
    # "video"-type page was deleted, so nothing regenerates video/, but
    # the old video/ directory and its contents would still be sitting
    # there untouched).
    #
    # Matches how every real static-site generator (Jekyll's _site,
    # Hugo's public/, etc.) handles exactly this: the build output
    # directory is treated as fully ephemeral/regenerable, wiped clean at
    # the start of every build rather than patched incrementally.
    if os.path.exists(output_dir):
        for entry in os.listdir(output_dir):
            entry_path = os.path.join(output_dir, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
    else:
        os.makedirs(output_dir)

    # Copy Assets
    if os.path.exists(ASSETS_SRC):
        dst_assets = os.path.join(output_dir, "assets")
        if os.path.exists(dst_assets):
            shutil.rmtree(dst_assets)
        shutil.copytree(ASSETS_SRC, dst_assets)
        _log("Assets copied.")

    # Copy selected stylesheet
    selected_css = _state.get("stylesheet", "dark.css")
    css_src = os.path.join(STYLESHEETS_DIR, selected_css)
    if not os.path.exists(css_src):
        _write_default_stylesheets()
        css_src = os.path.join(STYLESHEETS_DIR, "dark.css")
    shutil.copy2(css_src, os.path.join(output_dir, "style.css"))
    _log(f"Stylesheet applied: {selected_css}")

    # Load Data
    db.mount()
    site_conf_records = db.get_records("SiteConfig")
    site_conf         = {r["sys_key"]: r["sys_value"] for r in site_conf_records if "sys_key" in r}

    categories      = db.get_records("Category")
    items           = db.get_records("PageRecord")
    nav_records     = db.get_records("NavLink")
    social_records  = db.get_records("SocialLink")
    standalone_apps = db.get_records("StandaloneApp")
    ad_units        = db.get_records("AdUnit")

    # FIX (2026-08-25, audit F-07): site_title/site_desc/default_author are
    # admin-typed SiteConfig values, and nav_display_label/
    # social_platform_name are admin-typed too -- all inserted raw into
    # EVERY published page via the Global_Skeleton header/footer/nav
    # (base_tags applies globally), making this actually more broadly
    # exploitable than the single page_title example the audit gave.
    # nav_target_url/social_target_url are used as href values (not text
    # content) -- html.escape() still correctly neutralizes a
    # quote-breaking payload there without mangling a legitimate URL.
    # site_title/site_desc are NOT escaped here (same reasoning as
    # default_author below): each is used in more than one place
    # downstream, and at least one of those places (safe_desc's
    # `p_desc or site_desc` fallback, further down) already applies
    # html.escape() itself -- pre-escaping here would double-escape that
    # path. Escaped individually at each actual point of use instead.
    site_title     = site_conf.get("title", "boehnenelton2024")
    site_desc      = site_conf.get("description", "Personal project showcase")
    # default_author is NOT escaped here either, for the same reason -- it
    # flows into p_author (line ~1143) which already gets html.escape()'d
    # downstream as safe_author right before use; escaping it here too
    # would double-escape (e.g. "Tom & Jerry" -> "Tom &amp; Jerry" ->
    # "Tom &amp;amp; Jerry") for any page that falls back to it.
    default_author = site_conf.get("creator", "The Architect")
    base_url       = site_conf.get("base_url", "https://boehnenelton2024-blog.pages.dev")

    custom_nav_html = "".join([f"<li><a href='{html.escape(n.get('nav_target_url', '#'))}'>{html.escape(n.get('nav_display_label', 'Link'))}</a></li>" for n in nav_records])
    social_html     = "".join([f"<a href='{html.escape(s.get('social_target_url', '#'))}' target='_blank' class='social-btn'>{html.escape(s.get('social_platform_name', 'Social'))}</a>" for s in social_records])

    wrapper_skel = _read_skel("Global_Skeleton.html")
    feed_items   = []

    # Common tags
    base_tags = {
        "site_title": html.escape(site_title),
        "site_description": html.escape(site_desc),
        "current_year": datetime.now().year,
        "social_media_links": social_html,
        "custom_nav_links": custom_nav_html,
    }

    # --- PROCESS PAGES ---
    for item in items:
        itype = item.get("page_type", "page")
        if itype == "external_link":
            ext_url = item.get("page_external_url", "#")
            p_date  = item.get("page_created_at") or datetime.now().strftime("%Y-%m-%d")
            feed_items.append({
                "date": p_date,
                "item": item,
                "link": ext_url,
                "type": "external_link",
                "target_attr": " target='_blank' rel='noopener noreferrer'",
                "desc": ""
            })
            continue

        _log(f"Building Page: {item['page_title']}")
        cat_obj  = next((c for c in categories if c.get("cat_name") == item.get("page_cat_name")), None)
        cat_slug = cat_obj["cat_slug"] if cat_obj and cat_obj.get("cat_slug") else "uncategorized" 

        target_dir = os.path.join(output_dir, itype, cat_slug, item["page_slug"])
        os.makedirs(target_dir, exist_ok=True)

        src_file = os.path.join(PAGES_DB_DIR, f"{item['page_uuid']}.json")
        if not os.path.exists(src_file): continue

        try:
            import lib_bejson_Core_bejson_core as Core
            with open(src_file, "r", encoding="utf-8") as f: js = json.load(f)
            field_map = Core.bejson_core_get_field_map(js)
            idx_html = field_map.get("html_body", -1)
            idx_parent = field_map.get("Record_Type_Parent", 0)
            idx_desc = field_map.get("meta_description", -1)
            
            content_row = next((r for r in js["Values"] if r[idx_parent] == "Content"), None)
            html_body = content_row[idx_html] if content_row and idx_html != -1 else ""
            
            p_desc = ""
            if idx_desc != -1:
                meta_row = next((r for r in js["Values"] if r[idx_parent] == "PageMeta"), None)
                if meta_row: p_desc = meta_row[idx_desc] or ""
            if not p_desc:
                p_desc = _generate_excerpt(html_body)

            p_author = item.get("page_author_name") or default_author
            p_date   = item.get("page_created_at") or datetime.now().strftime("%Y-%m-%d")
            f_img    = item.get("page_featured_img")
            
            # Handle missing or "None" images with the seeded default image
            if not f_img or str(f_img).lower() == "none":
                feat_img_html = f"<img src='../../../assets/{DEFAULT_FEATURED_IMAGE}' class='article-featured-image'>"
            else:
                feat_img_html = f"<img src='../../../assets/{f_img}' class='article-featured-image'>"
            
            related_html = _generate_related_block(items, item, default_author, categories)
            ad_html      = _generate_ad_block(ad_units, "../../../")

            # Render page content via strategy renderer dispatch
            from NewAgent_CMS_Renderers import render_page
            rendered_article_content = render_page(itype, {"page_title": item.get("page_title", ""), "html_body": html_body, "page_external_url": item.get("page_external_url"), "page_featured_img": f_img})

            # FIX (2026-08-25, audit F-07): page_title, page_cat_name,
            # p_author, and p_desc are all admin-typed free text (page
            # title field, category name field, author display name,
            # meta-description field) and were substituted into this
            # published static HTML raw -- same unescaped-text-content/
            # attribute-value XSS class the audit demonstrated via
            # page_title in _generate_card_html. html_body/
            # rendered_article_content is NOT escaped here -- it's the
            # actual page body content, which is HTML by design for a
            # CMS; escaping that would break every page's rendered
            # content, and it isn't the vulnerability class in question.
            safe_title    = html.escape(item.get("page_title", ""))
            safe_cat_name = html.escape(item.get("page_cat_name", "Uncategorized"))
            safe_author   = html.escape(p_author)
            safe_desc     = html.escape(p_desc or site_desc)

            # Build Page Tags
            page_tags = base_tags.copy()
            page_tags.update({
                "page_title": safe_title,
                "rel_prefix": "../../../",
                "sidebar_categories": _get_sidebar_html(categories, "../../../"),
                "breadcrumb_html": f"<a href='../../../category/{cat_slug}/index.html'>{safe_cat_name}</a> <span>/</span> {safe_title}",
                "seo_description": safe_desc,
                "seo_author": safe_author,
                "seo_image": f"{base_url.rstrip('/')}/assets/{f_img}" if f_img else "",
                "current_url": "",
                # Inner Tags
                "article_title": safe_title,
                "category": safe_cat_name,
                "article_body": rendered_article_content,
                "featured_image_html": feat_img_html,
                "related_content_section": related_html + ad_html,
                "timestamp": f"{p_date} \u2022 {safe_author}"
            })

            # Assemble Page
            article_skel = _read_skel("Article_Skeleton.html")
            main_content = _apply_tags(article_skel, page_tags)
            page_tags["main_content_injection"] = main_content
            
            final = _apply_tags(wrapper_skel, page_tags)
            final = _apply_tags(final, page_tags) 

            with open(os.path.join(target_dir, "index.html"), "w", encoding="utf-8") as f: f.write(final)
            feed_items.append({"date": p_date, "item": item, "link": f"{itype}/{cat_slug}/{item['page_slug']}/index.html", "type": "page", "desc": p_desc})
        except Exception as e:
            _log(f"Error processing {item['page_title']}: {e}")

    # --- PROCESS APPS ---
    for sa in standalone_apps:
        src_dir = os.path.join(APPS_STORAGE, sa["app_uuid"])
        dst_dir = os.path.join(output_dir, "apps", sa["app_slug"])
        if os.path.exists(src_dir):
            if os.path.exists(dst_dir): shutil.rmtree(dst_dir)
            shutil.copytree(src_dir, dst_dir)
            Generated_App_Permalink = f"apps/{sa['app_slug']}/{sa.get('app_entry_file', 'index.html')}"
            feed_items.append({"date": sa.get("app_created_at", datetime.now().strftime("%Y-%m-%d")), "item": {"page_title": sa["app_name"], "page_featured_img": sa.get("app_featured_img"), "page_uuid": sa["app_uuid"]}, "link": Generated_App_Permalink, "type": "app", "desc": sa.get("app_description", "")})

    # --- BUILD HOME ---
    _log("Generating Home Feed...")
    recent = sorted(feed_items, key=lambda k: k["date"] or "", reverse=True)[:15]
    home_grid = "".join([_generate_card_html(x["item"], x["link"], x.get("target_attr", ""), x["type"].upper(), x["date"], default_author, "", x.get("desc", "")) for x in recent])
    
    home_tags = base_tags.copy()
    home_tags.update({
        "page_title": "Home",
        "rel_prefix": "",
        "sidebar_categories": _get_sidebar_html(categories, ""),
        "breadcrumb_html": "Dashboard",
        "seo_description": html.escape(site_desc),
        "seo_author": html.escape(site_title),
        "seo_image": "",
        "current_url": base_url,
        "content_grid": home_grid + _generate_ad_block(ad_units, "")
    })
    
    home_inner = _apply_tags(_read_skel("Home_Skeleton.html"), home_tags)
    home_tags["main_content_injection"] = home_inner
    
    final = _apply_tags(wrapper_skel, home_tags)
    final = _apply_tags(final, home_tags)
    with open(os.path.join(output_dir, "index.html"), "w", encoding="utf-8") as f: f.write(final)

    # --- BUILD APPS FEED ---
    _log("Generating Apps Feed...")
    apps_only = [x for x in feed_items if x["type"] == "app"]
    apps_grid = "".join([_generate_card_html(x["item"], x["link"].replace("apps/", ""), "", "APP", x["date"], default_author, "../", x.get("desc", "")) for x in apps_only])
    
    apps_tags = base_tags.copy()
    apps_tags.update({
        "page_title": "Applications",
        "rel_prefix": "../",
        "sidebar_categories": _get_sidebar_html(categories, "../"),
        "breadcrumb_html": "Applications",
        "seo_description": "Web Tools",
        "seo_author": html.escape(site_title),
        "seo_image": "",
        "current_url": "",
        "content_grid": apps_grid + _generate_ad_block(ad_units, "../")
    })
    
    apps_inner = _apply_tags(_read_skel("Apps_Feed_Skeleton.html"), apps_tags)
    apps_tags["main_content_injection"] = apps_inner
    
    final = _apply_tags(wrapper_skel, apps_tags)
    final = _apply_tags(final, apps_tags)
    os.makedirs(os.path.join(output_dir, "apps"), exist_ok=True)
    with open(os.path.join(output_dir, "apps", "index.html"), "w", encoding="utf-8") as f: f.write(final)

    # --- BUILD CATEGORY FEEDS ---
    for cat in categories:
        c_name = cat.get("cat_name") or cat.get("category_name")
        if not c_name: continue
        c_slug = cat.get("cat_slug") or cat.get("category_slug") or "uncategorized"
        _log(f"Generating Category: {c_name}")
        c_items = [x for x in feed_items if x["type"] in ("page", "external_link") and x["item"].get("page_cat_name") == c_name]
        c_grid = "".join([_generate_card_html(x["item"], x["link"] if x["type"] == "external_link" else f"../../{x['link']}", x.get("target_attr", ""), x["type"].upper(), x["date"], default_author, "../../", x.get("desc", "")) for x in c_items])
        
        # FIX (2026-08-25, audit F-07): c_name is an admin-typed category
        # name, same unescaped-text-content class as page_title.
        safe_c_name = html.escape(c_name)

        cat_tags = base_tags.copy()
        cat_tags.update({
            "page_title": safe_c_name,
            "rel_prefix": "../../",
            "sidebar_categories": _get_sidebar_html(categories, "../../"),
            "breadcrumb_html": f"Category <span>/</span> {safe_c_name}",
            "seo_description": "",
            "seo_author": html.escape(site_title),
            "seo_image": "",
            "current_url": "",
            "category_name": safe_c_name,
            "category_description": f"Browsing all items in {safe_c_name}.",
            "content_grid": c_grid + _generate_ad_block(ad_units, "../../")
        })
        
        cat_inner = _apply_tags(_read_skel("Category_Skeleton.html"), cat_tags)
        cat_tags["main_content_injection"] = cat_inner
        
        final = _apply_tags(wrapper_skel, cat_tags)
        final = _apply_tags(final, cat_tags)
        cat_dir = os.path.join(output_dir, "category", c_slug)
        os.makedirs(cat_dir, exist_ok=True)
        with open(os.path.join(cat_dir, "index.html"), "w", encoding="utf-8") as f: f.write(final)

    # --- SITEMAP.XML + ROBOTS.TXT ---
    _log("Generating sitemap.xml and robots.txt...")
    _write_sitemap_and_robots(output_dir, base_url, feed_items, categories)

    # FIX (2026-08-31, audit F-45): the pre-publish gate can't see a
    # skeleton that was never registered at all -- only _read_skel()'s
    # own SkeletonContractError catch (above) sees that narrower case,
    # mid-render, once it's too late to abort cleanly. Surfacing it here
    # as an unmistakable final line instead of letting "Build Complete!"
    # alone imply everything rendered correctly.
    if _state.get("build_had_skeleton_errors", 0) > 0:
        _log(f"Build FINISHED WITH {_state['build_had_skeleton_errors']} SKELETON ERROR(S) -- "
             f"one or more pages contain a broken/placeholder section. Scroll up for the exact "
             f"file(s) and missing tag(s), then rebuild after fixing.")
    else:
        _log("Build Complete!")


# ==============================================================================
# LOCAL PREVIEW SERVER  (from WebPublisher._start_server / _stop_server)
# ==============================================================================

def _run_preview_server(port):
    output_dir = _state["output_dir"]

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=output_dir, **kwargs)
        def log_message(self, fmt, *args):
            pass  # suppress console noise

    # FIX (2026-08-27, audit F-13): TCPServer.__init__ calls server_bind()
    # internally, which is what actually checks allow_reuse_address (via
    # SO_REUSEADDR) -- it reads the attribute DURING construction, before
    # __init__ returns. Setting httpd.allow_reuse_address = True after
    # construction (the old code, right below where this subclass is now
    # used instead) has no effect at all: the socket is already bound by
    # the time that assignment runs. A subclass with allow_reuse_address
    # as a CLASS attribute is checked before super().__init__()'s
    # server_bind() call, which is the only way this setting actually
    # takes effect. Confirmed via a real bind-close-rebind test on the
    # same port, not just read from the docs.
    class ReusableTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    try:
        httpd = ReusableTCPServer(("", port), Handler)
        _state["httpd"]       = httpd
        _state["srv_running"] = True
        _state["srv_port"]    = port
        _log(f"Preview server running on http://localhost:{port}")
        httpd.serve_forever()
    except Exception as e:
        _state["srv_running"] = False
        _log(f"Server error: {e}")


def _stop_preview_server():
    if _state.get("httpd"):
        _state["httpd"].shutdown()
        _state["httpd"].server_close()
    _state["httpd"]       = None
    _state["srv_running"] = False
    _log("Preview server stopped.")


# ==============================================================================
# ADMIN UI — shared shell (dark theme matching the original app palette)
# ==============================================================================

_SHELL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>{{ page_title }} -- NewAgent Publisher</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=Source+Code+Pro&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0f0f0f;--panel:#161616;--card:#1c1c1c;--acc:#DE2626;
  --border:#2a2a2a;--fg:#f0f0f0;--muted:#888;--green:#16a34a;
  --sb-w:220px;
}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{height:100%;}
body{font-family:'Inter',sans-serif;background:var(--bg);color:var(--fg);font-size:15px;overflow-x:hidden;}
a{color:var(--acc);text-decoration:none;} a:hover{opacity:.8;}

/* ── OVERLAY (mobile) ── */
#sb-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:90;}
#sb-overlay.show{display:block;}

/* ── SIDEBAR ── */
.sb{
  position:fixed;top:0;left:0;height:100%;width:var(--sb-w);
  background:var(--panel);border-right:1px solid var(--border);
  display:flex;flex-direction:column;z-index:100;
  transition:transform .25s ease;
}
.sb-logo{padding:18px 16px;border-bottom:2px solid var(--acc);font-size:1.2rem;font-weight:900;letter-spacing:-1px;color:#fff;flex-shrink:0;}
.sb-logo span{color:var(--acc);}
.sb nav{flex:1;overflow-y:auto;}
.sb nav a{display:flex;align-items:center;gap:10px;padding:14px 16px;color:var(--muted);font-size:.9rem;font-weight:600;transition:.15s;border-left:3px solid transparent;}
.sb nav a:hover{color:#fff;background:rgba(222,38,38,.1);}
.sb nav a.on{color:#fff;background:rgba(222,38,38,.15);border-left-color:var(--acc);}
.sb-foot{padding:12px 16px;font-size:.7rem;color:#444;border-top:1px solid var(--border);flex-shrink:0;}

/* ── TOPBAR ── */
.topbar{
  position:fixed;top:0;left:var(--sb-w);right:0;height:52px;
  background:var(--panel);border-bottom:1px solid var(--border);
  display:flex;align-items:center;padding:0 20px;gap:14px;z-index:80;
}
.topbar h2{font-size:.95rem;font-weight:800;color:var(--acc);flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.hamburger{display:none;background:none;border:none;color:var(--fg);font-size:1.4rem;cursor:pointer;padding:4px 6px;line-height:1;flex-shrink:0;}

/* ── MAIN CONTENT ── */
.main{margin-left:var(--sb-w);margin-top:52px;min-height:calc(100vh - 52px);display:flex;flex-direction:column;}
.content{padding:22px;max-width:1080px;width:100%;}

/* ── CARDS ── */
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px;margin-bottom:16px;}
.card-hd{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--border);gap:10px;flex-wrap:wrap;}
.card-hd h3{font-size:.93rem;font-weight:700;}

/* ── BUTTONS ── */
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 16px;border:none;border-radius:6px;font-family:inherit;font-weight:700;font-size:.84rem;cursor:pointer;text-decoration:none;transition:.15s;white-space:nowrap;touch-action:manipulation;}
.btn-red{background:var(--acc);color:#fff;} .btn-red:hover{background:#b91c1c;}
.btn-grey{background:#2a2a2a;color:#ccc;border:1px solid var(--border);} .btn-grey:hover{background:#333;}
.btn-green{background:var(--green);color:#fff;} .btn-green:hover{background:#15803d;}
.btn-sm{padding:7px 12px;font-size:.78rem;}
.btn:disabled{opacity:.45;cursor:default;}

/* ── FORMS ── */
.fg{margin-bottom:14px;}
label{display:block;margin-bottom:5px;font-size:.82rem;font-weight:600;color:var(--muted);}
input[type=text],input[type=number],select,textarea{
  width:100%;padding:10px 13px;background:#111;border:1px solid var(--border);
  border-radius:6px;color:#fff;font-family:inherit;font-size:1rem;
  -webkit-appearance:none;
}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--acc);}
textarea{min-height:420px;font-family:'Source Code Pro',monospace;font-size:.88rem;line-height:1.6;resize:vertical;}

/* ── MISC ── */
.logbox{background:#000;border:1px solid var(--border);border-radius:6px;padding:14px;height:260px;overflow-y:auto;font-family:'Source Code Pro',monospace;font-size:.78rem;color:#00ff00;white-space:pre-wrap;line-height:1.5;}
table{width:100%;border-collapse:collapse;}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border);font-size:.88rem;}
th{font-size:.7rem;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);}
tr:hover{background:rgba(255,255,255,.02);}
td:last-child{white-space:nowrap;}
.badge{display:inline-block;padding:3px 8px;border-radius:4px;font-size:.68rem;font-weight:700;text-transform:uppercase;}
.b-on{background:#14532d;color:#4ade80;} .b-off{background:#292929;color:#777;}
.alert{padding:12px 16px;border-radius:6px;margin-bottom:16px;font-size:.88rem;line-height:1.5;}
.a-ok{background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.25);color:#4ade80;}
.a-err{background:rgba(220,38,38,.1);border:1px solid rgba(220,38,38,.3);color:#f87171;}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px;}
.btn-row{display:flex;gap:10px;flex-wrap:wrap;}

/* ── MOBILE ── */
@media(max-width:700px){
  :root{--sb-w:220px;}
  .sb{transform:translateX(calc(-1 * var(--sb-w)));}
  .sb.open{transform:translateX(0);}
  .topbar{left:0;}
  .main{margin-left:0;}
  .hamburger{display:block;}
  .grid2{grid-template-columns:1fr;}
  .content{padding:14px;}
  .card{padding:16px;}
  /* stack editor split layout */
  .editor-split{flex-direction:column !important;}
  .editor-split > div:first-child{width:100% !important;max-height:200px;}
  /* make tables scrollable */
  .table-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch;}
  /* bigger tap targets */
  .btn{padding:11px 16px;}
  input[type=text],input[type=number],select{font-size:16px;}
}
</style>
</head>
<body>
<div id="sb-overlay" onclick="closeSb()"></div>
<div class="sb" id="sidebar">
  <div class="sb-logo">NewAgent<span>.</span></div>
  <nav>
    <a href="/"        class="{{ 'on' if active=='dash'    else '' }}">&#9711; Dashboard</a>
    <a href="/publish" class="{{ 'on' if active=='publish' else '' }}">&#9654; Publisher</a>
    <a href="/reset"   class="{{ 'on' if active=='reset'   else '' }}">&#9888; Factory Reset</a>
  </nav>
  <div class="sb-foot">Flask port</div>
</div>
<div class="topbar">
  <button class="hamburger" onclick="toggleSb()" aria-label="Menu">&#9776;</button>
  <h2>{{ page_title }}</h2>
</div>
<div class="main">
  <div class="content">
    {% if flash %}<div class="alert {{ flash_cls }}">{{ flash | safe }}</div>{% endif %}
    {{ body | safe }}
  </div>
</div>
<script>
function toggleSb(){
  var sb=document.getElementById('sidebar');
  var ov=document.getElementById('sb-overlay');
  sb.classList.toggle('open');
  ov.classList.toggle('show');
}
function closeSb(){
  document.getElementById('sidebar').classList.remove('open');
  document.getElementById('sb-overlay').classList.remove('show');
}
// close sidebar on nav link tap (mobile)
document.querySelectorAll('.sb nav a').forEach(function(a){
  a.addEventListener('click',closeSb);
});
</script>
</body>
</html>"""

def _page(title, active, body, flash="", flash_cls="a-ok"):
    return render_template_string(
        _SHELL,
        page_title=title, active=active, body=body,
        flash=flash, flash_cls=flash_cls
    )


# ==============================================================================
# ROUTE: DASHBOARD
# ==============================================================================

@app.route("/")
def r_dashboard():
    db_ok = os.path.exists(MANIFEST_PATH)
    pages = Standalone_App_Count = Category_Count = 0
    if db_ok:
        try:
            db.mount()
            pages = len([r for r in db.get_records("PageRecord") if r.get("page_type") != "external_link"])
            Standalone_App_Count  = len(db.get_records("StandaloneApp"))
            Category_Count  = len(db.get_records("Category"))
        except Exception:
            pass

    assets = 0
    if os.path.exists(ASSETS_SRC):
        assets = len([f for f in os.listdir(ASSETS_SRC) if not f.startswith(".")])

    built = os.path.exists(_state["output_dir"]) and bool(os.listdir(_state["output_dir"]))

    srv_badge = (f"<span class='badge b-on'>:{_state['srv_port']}</span>"
                 if _state["srv_running"] else "<span class='badge b-off'>stopped</span>")

    Dashboard_Page_Html = f"""
    <div class="grid2" style="margin-bottom:18px;">
      <div class="card" style="padding:18px;">
        <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:6px;">Pages</div>
        <div style="font-size:2.4rem;font-weight:900;color:var(--acc);">{pages}</div>
      </div>
      <div class="card" style="padding:18px;">
        <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:6px;">Standalone Apps</div>
        <div style="font-size:2.4rem;font-weight:900;color:var(--acc);">{Standalone_App_Count}</div>
      </div>
      <div class="card" style="padding:18px;">
        <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:6px;">Categories</div>
        <div style="font-size:2.4rem;font-weight:900;color:var(--acc);">{Category_Count}</div>
      </div>
      <div class="card" style="padding:18px;">
        <div style="font-size:.7rem;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:6px;">Assets</div>
        <div style="font-size:2.4rem;font-weight:900;color:var(--acc);">{assets}</div>
      </div>
    </div>
    <div class="card">
      <div class="card-hd"><h3>System Status</h3></div>
      <div class="table-wrap">
      <table>
        <tr><td>Master Database</td>
            <td>{"<span class='badge b-on'>OK</span>" if db_ok else "<span class='badge b-off'>MISSING</span>"}</td></tr>
        <tr><td>Output Directory</td>
            <td><code style="font-size:.8rem;color:#aaa;white-space:normal;word-break:break-all;">{_state["output_dir"]}</code></td></tr>
        <tr><td>Site Built</td>
            <td>{"<span class='badge b-on'>YES</span>" if built else "<span class='badge b-off'>NOT YET</span>"}</td></tr>
        <tr><td>Preview Server</td><td>{srv_badge}</td></tr>
        <tr><td>Skeleton Dir</td>
            <td>{"<span class='badge b-on'>OK</span>" if os.path.exists(SKEL_DIR) else "<span class='badge b-off'>MISSING</span>"}</td></tr>
      </table>
      </div>
    </div>
    <div class="btn-row">
      <a href="/publish" class="btn btn-red">&#9654; Build &amp; Publish</a>
    </div>"""
    return _page("Dashboard", "dash", Dashboard_Page_Html)


# ==============================================================================
# ROUTE: PUBLISHER
# ==============================================================================

@app.route("/publish")
def r_publish():
    built    = os.path.exists(_state["output_dir"]) and bool(os.listdir(_state["output_dir"]))
    building = _state["build_running"]
    srv_on   = _state["srv_running"]
    srv_port = _state["srv_port"]
    out_dir  = _state["output_dir"]

    build_badge = ("<span class='badge b-on'>IDLE</span>" if not building
                   else "<span class='badge' style='background:#7c2d12;color:#fca5a5;'>BUILDING...</span>")
    srv_badge   = (f"<span class='badge b-on'>:{srv_port}</span>" if srv_on
                   else "<span class='badge b-off'>stopped</span>")

    server_controls = f"""
      <form method="POST" action="/publish/server/start" style="display:flex;gap:10px;align-items:flex-end;margin-bottom:10px;">
        <div class="fg" style="margin:0;">
          <label>Port</label>
          <input type="number" name="port" value="{srv_port}" style="width:100px;">
        </div>
        <button class="btn btn-green" {"disabled" if srv_on else ""}>&#9654; Start</button>
      </form>
      {"<form method='POST' action='/publish/server/stop'><button class='btn btn-red'>&#9646;&#9646; Stop Server</button></form>" if srv_on else ""}
      {"<a href='http://localhost:" + str(srv_port) + "' target='_blank' class='btn btn-grey' style='margin-top:8px;display:inline-flex;'>&#127760; Open Browser</a>" if srv_on else ""}
    """

    body = f"""
    <div class="grid2">
      <div>
        <div class="card">
          <div class="card-hd"><h3>Build Site</h3>{build_badge}</div>
          <p style="color:var(--muted);font-size:.88rem;margin-bottom:16px;">
            Reads BEJSON data, assembles HTML using your skeleton files on disk, copies assets.
          </p>
          <form method="POST" action="/publish/build">
            <div class="fg">
              <label>Output Directory</label>
              <input type="text" name="output_dir" value="{out_dir}">
            </div>
            <div class="fg">
              <label>Theme Stylesheet</label>
              <select name="stylesheet">
                {''.join(f'<option value="{f}" {"selected" if f == _state["stylesheet"] else ""}>{f}</option>' for f in _list_stylesheets()) or '<option value="light.css">light.css</option>'}
              </select>
              <p style="font-size:.78rem;color:var(--muted);margin-top:6px;">
                Stylesheets live in <code style="color:#aaa;word-break:break-all;">{STYLESHEETS_DIR}</code>.
                Copy &amp; edit to build custom themes.
              </p>
            </div>
            <button class="btn btn-red" {"disabled" if building else ""}>&#9654; Build Now</button>
          </form>
        </div>
        <div class="card">
          <div class="card-hd">
            <h3>Build Log</h3>
            <button class="btn btn-grey btn-sm" id="btn-poll" onclick="togglePoll()">Auto-refresh</button>
          </div>
          <div class="logbox" id="logbox">{chr(10).join(_state["build_log"][-200:]) or "No build started yet."}</div>
        </div>
      </div>
      <div>
        <div class="card">
          <div class="card-hd"><h3>Preview Server</h3>{srv_badge}</div>
          <p style="color:var(--muted);font-size:.88rem;margin-bottom:16px;">
            Serves the built static site locally for review.
            {"<br><strong style='color:#4ade80;'>Built site detected.</strong>" if built else ""}
          </p>
          {server_controls}
        </div>
        <div class="card">
          <div class="card-hd"><h3>Cloudflare Pages</h3></div>
          <p style="color:var(--muted);font-size:.88rem;margin-bottom:16px;">
            Deploy the built static site directly to Cloudflare Pages.
          </p>
          <form method="POST" action="/publish/cloudflare">
            <div class="fg">
              <label>Project Name</label>
              <input type="text" name="cf_project" placeholder="Enter Cloudflare Project Name" value="boehnenelton2024-blog">
            </div>
            <button class="btn btn-green" {"disabled" if building else ""}>&#9729; Publish to Cloudflare</button>
          </form>
        </div>
        <div class="card">
          <div class="card-hd"><h3>Skeleton Files</h3></div>
          <p style="color:var(--muted);font-size:.85rem;margin-bottom:12px;">
            Live in <code style="font-size:.8rem;color:#aaa;word-break:break-all;">{SKEL_DIR}/default/</code>
            (or <code style="font-size:.8rem;color:#aaa;">{SKEL_DIR}/{_current_theme_name()}/</code> if that theme has its own override files).<br>
            Edit them directly, or use <code style="font-size:.8rem;color:#aaa;">newagent-manage skeleton edit/diff/promote</code> for a draft-and-preview workflow (see docs/SKELETON_LOADER.md).
          </p>
          <form method="POST" action="/publish/reset-theme" onsubmit="return confirm('Reset all skeleton files for the current theme ({_current_theme_name()}) back to the factory default? A timestamped backup of the current files is kept automatically.');">
            <button class="btn btn-grey">&#8635; Reset Theme to Factory Default</button>
          </form>
        </div>
      </div>
    </div>
    <script>
      let _p = false, _t = null;
      function togglePoll() {{
        _p = !_p;
        document.getElementById('btn-poll').textContent = _p ? 'Stop refresh' : 'Auto-refresh';
        if (_p) doPoll(); else clearTimeout(_t);
      }}
      function doPoll() {{
        fetch('/publish/log').then(r=>r.json()).then(d=>{{
          const el = document.getElementById('logbox');
          el.textContent = d.log.join('\\n');
          el.scrollTop = el.scrollHeight;
          if (_p) _t = setTimeout(doPoll, 1500);
        }});
      }}
    </script>"""
    return _page("Publisher", "publish", body)


@app.route("/publish/build", methods=["POST"])
def r_build():
    Submitted_Output_Directory = request.form.get("output_dir", "").strip()
    if Submitted_Output_Directory:
        _state["output_dir"] = Submitted_Output_Directory
    Submitted_Stylesheet_Choice = request.form.get("stylesheet", "").strip()
    if Submitted_Stylesheet_Choice:
        _state["stylesheet"] = Submitted_Stylesheet_Choice
    with _state_lock:
        should_start = not _state["build_running"]
        if should_start:
            _state["build_running"] = True
            _state["build_log"]     = []
    if should_start:
        def _run():
            try:
                _execute()
            finally:
                _state["build_running"] = False
        threading.Thread(target=_run, daemon=True).start()
    return redirect("/publish")


@app.route("/publish/log")
def r_log():
    return jsonify({"log": _state["build_log"][-300:], "running": _state["build_running"]})


@app.route("/publish/server/start", methods=["POST"])
def r_srv_start():
    if not _state["srv_running"]:
        try:
            port = int(request.form.get("port", 8000))
        except ValueError:
            port = 8000
        threading.Thread(target=_run_preview_server, args=(port,), daemon=True).start()
    return redirect("/publish")


@app.route("/publish/server/stop", methods=["POST"])
def r_srv_stop():
    threading.Thread(target=_stop_preview_server, daemon=True).start()
    return redirect("/publish")


@app.route("/publish/reset-theme", methods=["POST"])
def r_reset_theme():
    """Resets the active theme's skeleton set back to the frozen factory
    baseline (resources/templates/_factory/default/) -- a plain file
    copy, never code, and it only ever touches the requested theme's own
    folder (Proposal §Risks). Renamed from the old /publish/regen, which
    used to force-overwrite files from Python string literals."""
    theme = _current_theme_name()
    ok, msg = _skeleton_loader.reset_to_factory(theme, FACTORY_SKEL_DIR)
    return _page("Publisher", "publish",
        '<p style="margin-top:12px;"><a href="/publish" class="btn btn-grey">&#8592; Back</a></p>',
        flash=msg, flash_cls="a-ok" if ok else "a-err")


# ==============================================================================
# ROUTE: FACTORY RESET  (ported from Cleanup_Tool.py)
# Paths and logic identical; tkinter messagebox replaced with HTML confirm.
# ==============================================================================

@app.route("/reset")
def r_reset():
    body = """
    <div class="card" style="max-width:520px;">
      <div class="card-hd"><h3 style="color:var(--acc);">&#9888; Factory Reset</h3></div>
      <p style="line-height:1.8;margin-bottom:18px;">
        This will permanently delete:<br>
        &bull; All pages, articles &amp; categories<br>
        &bull; All images / assets<br>
        &bull; The published static website<br>
        &bull; All ZIP exports<br><br>
        <strong style="color:#f87171;">This cannot be undone.</strong>
      </p>
      <form method="POST" action="/reset/confirm"
            onsubmit="return confirm('Are you absolutely sure? All CMS data will be permanently lost.');">
        <button class="btn btn-red">&#128465; Wipe Everything</button>
        <a href="/" class="btn btn-grey" style="margin-left:10px;">Cancel</a>
      </form>
    </div>"""
    return _page("Factory Reset", "reset", body)


@app.route("/reset/confirm", methods=["POST"])
def r_reset_confirm():
    """Same wipe targets as the Admin factory reset (NewAgent_CMS_System.py
    factory_reset_confirm()), plus the same post-wipe re-bootstrap -- this
    route used to wipe MFDB_DIR/builds/exports and stop, leaving the DB
    unusable until Admin happened to be launched next and rebuilt it by
    accident. It also never cleared storage/tmp/html_imports (the exact
    gap Admin's reset was already fixed for).

    FIX (2026-09-11, audit V106-04): this route rmtree'd MFDB_DIR,
    DEFAULT_OUT_DIR, EXPORTS_DIR, and UPLOAD_TMP with no backup step at
    all -- Admin's equivalent route got a mandatory pre-wipe backup in
    F-15 (same destructive scope, same project); this route never did.
    Worse, it wiped EXPORTS_DIR itself, which is exactly where a rescue
    backup would have to land. Mirrors F-15's fix exactly: zip
    site_master/pages_db/assets/standalone_apps into EXPORTS_DIR *before*
    any rmtree, abort the whole reset if the backup fails, and exclude
    EXPORTS_DIR from the wipe list so the backup just taken survives it."""
    UPLOAD_TMP = os.path.join(STORAGE_ROOT, "tmp", "html_imports")

    try:
        backup_dirs = [
            os.path.join(MFDB_DIR, "site_master"),
            PAGES_DB_DIR,
            ASSETS_SRC,
            APPS_STORAGE,
        ]
        os.makedirs(EXPORTS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(EXPORTS_DIR, f"NewAgent_CMS_publisher_reset_backup_{ts}.zip")
        backup_file_count = 0
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for src_dir in backup_dirs:
                if not os.path.isdir(src_dir):
                    continue
                for root, _, files in os.walk(src_dir):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        arcname = os.path.join("mfdb", os.path.relpath(fpath, MFDB_DIR))
                        zf.write(fpath, arcname)
                        backup_file_count += 1
    except Exception as e:
        return _page("Factory Reset", "reset",
            '<p><a href="/" class="btn btn-grey">Back</a></p>',
            flash=f"Reset aborted -- the mandatory safety backup failed, so nothing was deleted: {e}",
            flash_cls="a-err")

    errors = []

    # NOTE (audit V106-04 fix): EXPORTS_DIR is deliberately excluded from
    # this wipe list -- the safety backup just taken above lives there,
    # and wiping it here would destroy the very backup this reset just
    # made. Mirrors Admin's factory_reset_confirm(), which carries the
    # identical exclusion for the identical reason.
    for path in [MFDB_DIR, DEFAULT_OUT_DIR, UPLOAD_TMP]:
        if os.path.exists(path):
            try:
                shutil.rmtree(path)
            except Exception as e:
                errors.append(str(e))

    # Re-create empty structure (same folders as original)
    for d in [
        os.path.join(MFDB_DIR, "assets"),
                os.path.join(MFDB_DIR, "Context"),
        os.path.join(MFDB_DIR, "standalone_apps"),
        EXPORTS_DIR,
        UPLOAD_TMP,
    ]:
        try:
            os.makedirs(d, exist_ok=True)
            if "STORAGE_ROOT" in globals(): os.makedirs(STORAGE_ROOT, exist_ok=True)
        except Exception:
            pass

    # Re-initialise a fresh master DB -- same lifecycle System.py runs at
    # server startup / Admin's own reset route, so a wipe from this app
    # doesn't leave the CMS broken until some other app happens to launch.
    try:
        import NewAgent_CMS_System as _SystemCube
        _SystemCube.run_startup_bootstrap()
    except Exception as e:
        errors.append(f"Re-bootstrap failed: {e}")

    if errors:
        return _page("Factory Reset", "reset",
            '<p><a href="/" class="btn btn-grey">Back</a></p>',
            flash="Reset completed with errors: " + "; ".join(errors) +
                  f" (Safety backup of pre-reset data: {backup_path}, {backup_file_count} files)",
            flash_cls="a-err")

    return _page("Factory Reset", "reset",
        '<p style="margin-top:12px;color:var(--muted);">Fresh database initialised — the default category and brand author are ready.</p>'
        f'<p style="margin-top:8px;color:var(--muted);">Safety backup of pre-reset data: {backup_path} ({backup_file_count} files).</p>'
        '<p style="margin-top:16px;"><a href="/" class="btn btn-grey">Back to Dashboard</a></p>',
        flash="System reset complete. All data has been wiped.")


# ==============================================================================
# ENTRY POINT
# ==============================================================================


@app.route("/publish/cloudflare", methods=["POST"])
def r_publish_cloudflare():
    project_name = request.form.get("cf_project", "").strip()
    if project_name and not re.match(r'^[a-zA-Z0-9\-]{1,64}$', project_name):
        return jsonify({'error': 'Invalid project name. Use only letters, numbers, and hyphens.'}), 400
    if not project_name:
        # Fallback to site name
        try:
            site_conf = {r["sys_key"]: r["sys_value"] for r in db.get_records("SiteConfig") if "sys_key" in r}
            project_name = site_conf.get("title", "bejson-site")
        except Exception:
            project_name = "bejson-site"

    # FIX (2026-08-27, audit F-12): check-and-set on build_running guarded
    # by _state_lock -- see the lock's own definition comment for why.
    with _state_lock:
        should_deploy = not _state["build_running"]
        if should_deploy:
            _state["build_running"] = True
            _state["build_log"] = []
    if should_deploy:
        _log(f"[Cloudflare] Starting deployment for project: {project_name}")
        
        def _run_deploy():
            try:
                out_dir = _state["output_dir"]
                if not os.path.exists(out_dir) or not os.listdir(out_dir):
                    _log("[Error] Output directory is empty. Run build first.")
                    return

                # Prepare environment
                Cloudflare_Deploy_Subprocess_Env = os.environ.copy()
                Cloudflare_Deploy_Subprocess_Env["CLOUDFLARE_ACCOUNT_ID"] = CF_KEYS.get("ACCOUNT_ID", "")
                Cloudflare_Deploy_Subprocess_Env["CLOUDFLARE_API_TOKEN"] = CF_KEYS.get("API_TOKEN", "")
                
                if not Cloudflare_Deploy_Subprocess_Env["CLOUDFLARE_API_TOKEN"]:
                    _log("[Error] Cloudflare API Token not found in vault.")
                    return

                _log("[Cloudflare] Running wrangler pages publish...")
                Wrangler_Deploy_Command = ["wrangler", "pages", "publish", out_dir, "--project-name", project_name]
                
                process = subprocess.Popen(Wrangler_Deploy_Command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=Cloudflare_Deploy_Subprocess_Env)
                for line in process.stdout:
                    _log(f"[wrangler] {line.strip()}")
                
                process.wait()
                if process.returncode == 0:
                    _log("[Cloudflare] Deployment successful!")
                else:
                    _log(f"[Cloudflare] Deployment failed with code {process.returncode}")
            except Exception as e:
                _log(f"[Cloudflare] Critical Error: {e}")
            finally:
                _state["build_running"] = False

        threading.Thread(target=_run_deploy, daemon=True).start()
    
    return redirect("/publish")

if __name__ == "__main__":
    print(f"""
============================================================
  NewAgent CMS Web Publisher Flask

  Routes:
    /          Dashboard
    /publish   Build + preview server
    /reset     Factory reset

  http://localhost:{PUBLISHER_PORT}
============================================================""")
    # Skeleton files live under resources/templates/default/ (or a
    # per-theme override folder) and are read through _skeleton_loader --
    # nothing to seed here anymore; resources/templates/_factory/default/
    # ships with the app as the frozen reset baseline instead.
    # Write default stylesheets only if they don't already exist
    _write_default_stylesheets()
    _legacy = [f for f in ["Flask_CMS.py", "Flask_CMS_Publisher.py", "Flask_Page_Editor.py",
                            "Flask_Profile_Manager.py", "Page_Editor_v2.py"]
               if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), f))]
    if _legacy:
        print(f"\n    !! WARNING: old pre-rename file(s) still present: {', '.join(_legacy)} -- delete them, they are unmaintained leftovers from before the Blueprint split.\n")
    # Port resolved via config.json (publisher_port) / CMS_PUBLISHER_PORT env
    # override — see lib_bejson_NewAgentCMS_cms_ports.py. Default unchanged at 5001.
    app.run(host="0.0.0.0", port=PUBLISHER_PORT, debug=False)
