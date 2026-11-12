"""
Name:           ui_routes.py
Path:           web_routes/ui_routes.py
Description:    Serves the terminal UI page, injecting the auth token + fetch() wrapper.
                Split out of webagent.py (audit item 6, 2026-10-17); audited for
                <hierarchy>_<group>_<purpose> taxonomy compliance.
Version:        2.0.0
Date:           2026-11-12
Author:         Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
License:        PolyForm-Noncommercial-1.0.0
RELATIONAL_ID:  d5b8ba6b-3002-4280-8d08-6cfb41bf3267
"""

import json

from flask import Blueprint, render_template


def create_blueprint(terminal_instance) -> Blueprint:
    """Build the `ui` blueprint bound to `terminal_instance`."""
    ui_route_blueprint = Blueprint("ui", __name__)

    @ui_route_blueprint.route("/")
    def index():
        auth_token_fetch_shim = (
            "<script>(function(){var T=" + json.dumps(terminal_instance.web_token) + ";"
            "var f=window.fetch;window.fetch=function(u,o){"
            "o=o||{};var h=new Headers(o.headers||{});"
            "if(!h.has('X-Auth-Token'))h.set('X-Auth-Token',T);"
            "o.headers=h;return f.call(this,u,o);};})();</script>"
        )
        return render_template("webagent_terminal.html").replace(
            "<head>", "<head>" + auth_token_fetch_shim, 1
        )

    return ui_route_blueprint
