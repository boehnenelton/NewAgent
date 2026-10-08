"""
Library:         NewAgent_CMS_Admin
Family:          NewAgent_CMS
Description:     Main admin app entry point. Registers the four NewAgent_CMS
                 blueprints (System, Content, Media, Interface) and starts
                 the Flask dev server. Route logic itself lives in the
                 blueprint files, not here.
                 REBRAND/STRIP NOTE (2026-08-23): forked from BEJSON CMS to
                 NewAgent CMS. Page Editor V1/V2 and Profile Manager
                 (Persona Hub) were removed project-wide -- this Admin app
                 and its 4 blueprints, plus the Publisher, are now the only
                 two surviving Flask apps in this fork.
Version:         19.0
Library_Version: 58
Date:            2026-08-23
RELATIONAL_ID:   4b8f1e6a-2d9c-4a7e-b3f0-6c1a9e5d8b2f
"""

import os
import sys
from flask import Flask, request

from NewAgent_CMS_Shared import (
    R, get_breadcrumbs, MFDB_DIR, ASSETS_DIR, PUBLISH_DIR,
    _USING_DEFAULT_PASSWORD, _check_auth, _unauthorized, warn_about_legacy_files,
    ADMIN_PORT,
)
from NewAgent_CMS_System import system_cube
from NewAgent_CMS_Content import content_cube
from NewAgent_CMS_Media import media_cube
from NewAgent_CMS_Interface import interface_cube

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('CMS_SECRET_KEY') or os.urandom(24).hex()  # Set CMS_SECRET_KEY env var in production
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

app.register_blueprint(system_cube)
app.register_blueprint(content_cube)
app.register_blueprint(media_cube)
app.register_blueprint(interface_cube)


@app.before_request
def _enforce_auth_everywhere():
    # SECURITY FIX: @require_auth was only ever applied to 2 routes total
    # (the dashboard "/" and one API endpoint) out of roughly 50 across the
    # 4 blueprints -- an incomplete carryover from before the Blueprint
    # split, which left page create/edit/delete, media upload/delete/
    # bulk-delete, database export, site config, and factory reset all
    # completely open to unauthenticated requests. This enforces the exact
    # same check on every single request, once, in one place, so no future
    # route can accidentally ship without it. The per-route @require_auth
    # decorators that already existed are now redundant but harmless.
    Request_Basic_Auth_Header = request.authorization
    if not Request_Basic_Auth_Header or not _check_auth(Request_Basic_Auth_Header.username, Request_Basic_Auth_Header.password):
        return _unauthorized()


@app.errorhandler(404)
def not_found(e):
    html = '''<div class="empty-state"><h1 style="font-size:4rem;color:var(--accent);">404</h1><h3>Page not found</h3><p>The page you\'re looking for doesn\'t exist.</p><br><a href="/" class="btn btn-primary">Go Home</a></div>'''
    return R(html, breadcrumbs=[{'label': '404', 'href': None}], active_section=''), 404


if __name__ == '__main__':
    warn_about_legacy_files()

    # FIX (2026-08-29, audit F-22): the DB init/migrate/self-heal/seed
    # sequence used to run as a NewAgent_CMS_System.py import-time side
    # effect. Called explicitly here instead, in the one real place a
    # server actually starts -- see run_startup_bootstrap()'s own
    # docstring for the full reasoning.
    from NewAgent_CMS_System import run_startup_bootstrap
    run_startup_bootstrap()

    # FIX (2026-08-25, audit F-08): debug mode used to be controlled by
    # FLASK_DEBUG alone -- any accidental source (a stray .env file, a
    # leftover shell export from an unrelated tool, another process
    # setting it) silently turned on Werkzeug's interactive debugger.
    # That debugger lets anyone who can reach an error page run arbitrary
    # Python -- real RCE, and "bound to loopback only" does not fully
    # neutralize it: a malicious page open in the same browser can still
    # reach a localhost service (browsers don't block that by default),
    # and any other local user/process on a shared device can too.
    # Now requires BOTH FLASK_DEBUG=1 in the environment AND an explicit
    # --debug flag on the actual command line -- an ambient env var can
    # no longer enable this by itself; someone has to deliberately type
    # the flag, this run, to turn it on.
    _debug_requested = os.getenv('FLASK_DEBUG', '0') == '1' and '--debug' in sys.argv
    if os.getenv('FLASK_DEBUG', '0') == '1' and not _debug_requested:
        print('''
    !! FLASK_DEBUG=1 is set in the environment, but debug mode was NOT
    !! enabled -- it now also requires the --debug flag on the command
    !! line (`python3 NewAgent_CMS_Admin.py --debug`), so an ambient or
    !! leftover env var can't silently turn on Werkzeug's interactive
    !! debugger (that debugger allows arbitrary code execution from the
    !! browser to anyone who can reach an error page).
        ''')
    if _debug_requested:
        print('''
    !! WARNING: Starting with debug=True. Werkzeug's interactive debugger
    !! is active -- anyone who can reach an unhandled error page in this
    !! app can execute arbitrary Python. Never leave this running longer
    !! than the debugging session you're actively doing right now.
        ''')

    print(f'''
    ============================================
    NewAgent CMS Admin
    ============================================
    Data Directory: {MFDB_DIR}
    Assets Directory: {ASSETS_DIR}
    Publish Directory: {PUBLISH_DIR}

    Starting server on http://localhost:{ADMIN_PORT}
    Press CTRL+C to stop
    ============================================
    ''')
    if _USING_DEFAULT_PASSWORD:
        print('''
    !! WARNING: CMS_PASSWORD is not set - running with the default
    !! password ("changeme"). Anyone on your network can log in.
    !! Set the CMS_PASSWORD environment variable before exposing
    !! this beyond localhost.
        ''')
    # Port resolved via NewAgent_CMS_Shared: env var CMS_ADMIN_PORT > config.json
    # (admin_port) > 5001 default. See config.json / lib_bejson_NewAgentCMS_cms_ports.py.
    app.run(host='127.0.0.1', port=ADMIN_PORT, debug=_debug_requested, threaded=True, use_reloader=False)
