"""
Name:           test_help_registry_pkg127.py
Description:    Tests for the BEJSON-driven help system: registry schema, the
                help_topic discriminator, drift between the dispatcher and
                help.bejson, every screen (/help, /help <topic>, /help
                <command>, /<command> help), suggestions, live registry edits,
                and graceful fallback when the registry is missing or bad.
Version:        1.0
Date:           2026-10-14
Author:         Elton Boehnen (written by Claude)
RELATIONAL_ID:  2b7f94d1-6a03-4e58-8c2d-d41e90a7b536
"""
import _libpath  # noqa: F401
import asyncio
import json
import os
import re
import time
from pathlib import Path

import pytest

import lib_bejson_newagent_commands as commands
import lib_bejson_newagent_help as help_lib
from lib_bejson_Core_bejson_validator import validate_bejson

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "config" / "help.bejson"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _slash(text, config_dir=None):
    ctx = {"_config_dir": config_dir} if config_dir else {}
    ok, msg = asyncio.run(commands.handle_slash_commands(text, ctx))
    assert ok
    return ANSI.sub("", msg)


def _write_registry(path, rows, fields=None):
    fields = fields or [{"name": n, "type": "integer" if n == "help_order" else "string"} for n in help_lib.REQUIRED_FIELDS]
    doc = {"Format": "BEJSON", "Format_Version": "104", "Format_Creator": "Elton Boehnen",
           "Records_Type": ["HelpEntry"], "Fields": fields, "Values": rows}
    path.write_text(json.dumps(doc))


class TestRegistryFile:
    def test_valid_bejson_104_single_record_type(self):
        assert validate_bejson(str(REGISTRY), is_file=True).is_valid
        doc = json.loads(REGISTRY.read_text())
        assert doc["Format_Version"] == "104" and doc["Records_Type"] == ["HelpEntry"]

    def test_all_required_fields_present(self):
        doc = json.loads(REGISTRY.read_text())
        names = [f["name"] for f in doc["Fields"]]
        assert set(help_lib.REQUIRED_FIELDS) <= set(names)

    def test_every_row_topic_is_declared(self):
        reg = help_lib.load_registry(REGISTRY)
        doc = json.loads(REGISTRY.read_text())
        names = [f["name"] for f in doc["Fields"]]
        t, k = names.index(help_lib.F_TOPIC), names.index(help_lib.F_KIND)
        declared = {r[t] for r in doc["Values"] if r[k] == help_lib.KIND_TOPIC}
        assert {r[t] for r in doc["Values"]} <= declared
        assert set(reg.topics) == declared

    def test_help_ids_unique(self):
        doc = json.loads(REGISTRY.read_text())
        i = [f["name"] for f in doc["Fields"]].index(help_lib.F_ID)
        ids = [r[i] for r in doc["Values"]]
        assert len(ids) == len(set(ids))


class TestDispatcherDrift:
    def _dispatched(self):
        src = (ROOT / "lib" / "lib_bejson_newagent_commands.py").read_text()
        found = set()
        for m in re.finditer(r'(?m)^\s*(?:el)?if cmd (?:==|in) ([^:\n]+):', src):
            found |= set(re.findall(r'"(/[a-z0-9_]+)"', m.group(1)))
        return found

    def test_registry_matches_dispatcher_exactly(self):
        reg = help_lib.load_registry(REGISTRY)
        assert set(reg.commands) == self._dispatched()

    def test_each_command_in_exactly_one_topic(self):
        reg = help_lib.load_registry(REGISTRY)
        seen = [c.command for t in reg.topics.values() for c in t.commands]
        assert len(seen) == len(set(seen)) == len(reg.commands)


class TestScreens:
    def test_index_lists_every_topic_and_command_grouped(self):
        reg = help_lib.load_registry(REGISTRY)
        text = _slash("/help")
        positions = []
        for topic in reg.topics.values():
            assert f"(/help {topic.key})" in text
            positions.append(text.index(topic.title))
            for cmd in topic.commands:
                assert cmd.command in text
        assert positions == sorted(positions)          # topic order preserved

    @pytest.mark.parametrize("topic", ["general", "models", "keys", "files", "session", "context", "input", "safety", "jobs"])
    def test_topic_pages(self, topic):
        reg = help_lib.load_registry(REGISTRY)
        text = _slash(f"/help {topic}")
        assert reg.topics[topic].title in text
        for cmd in reg.topics[topic].commands:
            assert cmd.syntax.splitlines()[0] in text

    def test_models_topic_explains_provider_switching(self):
        text = _slash("/help models")
        assert "OpenRouter" in text and "/model sync" in text and "Interactions" in text

    def test_command_pages_with_and_without_slash(self):
        assert "Usage: /model" in _slash("/help model")
        assert "Usage: /model" in _slash("/help /model")

    def test_every_command_suffix_help(self):
        reg = help_lib.load_registry(REGISTRY)
        for cmd in reg.commands:
            text = _slash(f"{cmd} help")
            assert f"{cmd} Help:" in text and "Usage:" in text

    def test_unknown_suggests_close_matches_without_duplicates(self):
        text = _slash("/help keyz")
        assert "Did you mean" in text and "/help keys" in text
        line = [l for l in text.splitlines() if "Did you mean" in l][0]
        assert line.count("/help keys") == 1

    def test_unknown_with_no_match_lists_topics(self):
        text = _slash("/help zzzzqq")
        assert "No help topic" in text and "models" in text


class TestDataDriven:
    def test_new_topic_appears_without_code_change(self, tmp_path):
        rows = [["x.topic.01", "extras", "topic", "", "Extras", "", "Bonus section.", 10],
                ["x.command.01", "extras", "command", "/zap", "Zap things", "/zap <n>", "Zaps n things.", 10]]
        _write_registry(tmp_path / "help.bejson", rows)
        assert "Extras" in _slash("/help", tmp_path)
        assert "Zaps n things." in _slash("/help extras", tmp_path)
        assert "Usage: /zap <n>" in _slash("/help zap", tmp_path)

    def test_edit_is_picked_up_live(self, tmp_path):
        path = tmp_path / "help.bejson"
        rows = [["a.topic.01", "t", "topic", "", "Topic One", "", "first", 10]]
        _write_registry(path, rows)
        assert "first" in _slash("/help t", tmp_path)
        rows[0][6] = "second"
        _write_registry(path, rows)
        os.utime(path, (time.time() + 5, time.time() + 5))
        assert "second" in _slash("/help t", tmp_path)

    def test_whitespace_in_values_is_sanitized(self, tmp_path):
        rows = [["a.topic.01", "  pad ", "topic", "", "  Padded  ", "", "  body  ", 10]]
        _write_registry(tmp_path / "help.bejson", rows)
        assert "Padded" in _slash("/help pad", tmp_path)


class TestFallback:
    def test_missing_registry(self, tmp_path):
        text = _slash("/help", tmp_path)
        assert "Help registry unavailable" in text

    def test_missing_required_field(self, tmp_path):
        fields = [{"name": "help_topic", "type": "string"}]
        _write_registry(tmp_path / "help.bejson", [["t"]], fields)
        assert "Help registry unavailable" in _slash("/help", tmp_path)

    def test_command_help_without_registry_is_graceful(self, tmp_path):
        assert "no help entry" in _slash("/model help", tmp_path)
