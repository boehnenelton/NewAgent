"""
Name:         test_log_remediation_20261120.py
Description:  Regression tests for fixes driven by the Nov 18-19 2026 logs. Fixtures are the
              literal model outputs from logs/raw_api_debug_*_00000{3,5,6,7}.json.
Version:      1.0.0
Date:         2026-11-20
Author:       Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
RELATIONAL_ID: 51c21100-7937-4d95-8b44-7a824ead66b2
"""
import asyncio
import json
from pathlib import Path

import _libpath  # noqa: F401
import lib_bejson_newagent_actions as actions

ROOT = Path(__file__).resolve().parent.parent
VERSION = "1.0.0"


def test_unwrap_cmd_assignment_from_flint_log():
    acts = actions.parse_actions('<exec>cmd="mkdir -p ~/test && ls -ld ~/test"</exec>')
    assert acts[0]["content"] == "mkdir -p ~/test && ls -ld ~/test"


def test_unwrap_leaves_real_commands_alone():
    for c in ('echo cmd="x"', 'cmd=1; echo $cmd', "ls -la", 'FOO="a b" env'):
        assert actions._unwrap_exec_assignment(c) == c


def test_unwrap_restores_escaped_inner_quotes():
    assert actions._unwrap_exec_assignment('command="echo \\"hi\\""') == 'echo "hi"'


def test_dots_function_call_is_parsed():
    txt = ('<dots_function_call>\n<exec>\n<parameter name="command">pwd && echo "---" && ls -la ~/\n'
           '</parameter>\n</invoke>\n</dots_function_call>')
    acts = actions.parse_actions(txt)
    assert len(acts) == 1 and acts[0]["tag"] == "exec"
    assert acts[0]["content"] == 'pwd && echo "---" && ls -la ~/'


def test_plain_exec_still_parses():
    acts = actions.parse_actions("<exec>cd ~/test && pwd</exec>")
    assert acts == [{"tag": "exec", "attrs": {}, "content": "cd ~/test && pwd"}]


def test_wrapped_exec_actually_runs(tmp_path):
    acts = actions.parse_actions(f'<exec>cmd="mkdir -p {tmp_path}/t && ls -ld {tmp_path}/t"</exec>')
    code, out, _, _ = asyncio.run(actions.do_exec(acts[0]["content"], str(tmp_path), timeout=20))
    assert code == 0 and (tmp_path / "t").is_dir() and "t" in out


def test_catalog_has_no_dead_model_and_is_contiguous():
    d = json.loads((ROOT / "config" / "gemini_catalog.bejson").read_text())
    names = [f["name"] for f in d["Fields"]]
    rows = [dict(zip(names, r)) for r in d["Values"]]
    assert all(r["model_string"] != "poolside/laguna-xs-2.1:free" for r in rows)
    assert [r["model_number"] for r in rows] == list(range(1, len(rows) + 1))
    assert all(len(r) == len(names) for r in d["Values"])


def test_env_paths_sibling_fallback(tmp_path):
    import lib_bejson_newagent_env as env
    (tmp_path / "definitions.json").write_text("{}")
    (tmp_path / "secure.json").write_text("{}")
    cfg = {"env_secure_file_path": str(tmp_path / "secure.json"),
           "env_paths_file_path": str(tmp_path / "paths.json")}
    assert (tmp_path / "definitions.json") in env.resolve_env_bejson_sources(cfg)


def test_config_default_is_definitions_json():
    import lib_bejson_newagent_config as cfgmod
    d = {k: v for k, v, *_ in cfgmod.DEFAULT_CONFIG} if isinstance(cfgmod.DEFAULT_CONFIG, (list, tuple)) else cfgmod.DEFAULT_CONFIG
    assert d["env_paths_file_path"].endswith("definitions.json")
