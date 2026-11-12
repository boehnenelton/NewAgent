"""
Tests for NewAgent Semantic Conditions Trigger Engine
(lib_bejson_newagent_semantic_triggers.py + config/semantic_triggers.bejson)

Covers:
  1. Schema validation of semantic_triggers.bejson
  2. Condition evaluation (positive match, negative blocking, combined)
  3. Pipe-separated condition parsing
  4. Cooldown enforcement
  5. skill:// protocol path resolution
  6. Skill folder chunking (SKILL.md read + metadata footer)
  7. Conditions awareness section (always visible)
  8. Triggered actions section (only when conditions met)
  9. Full pipeline end-to-end (scan → awareness + injection)
  10. Negative conditions correctly block even when positives match
  11. Integration with assemble_bubble() (semantic_triggers path registered)

Author: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
"""

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import lib_bejson_Core_bejson_core as bejson_core
import lib_bejson_Core_bejson_validator as bejson_validator
import lib_bejson_newagent_semantic_triggers as semantic_triggers


# ── Test 1: Schema validation ─────────────────────────────────────────────

def test_semantic_triggers_bejson_schema_is_valid():
    """semantic_triggers.bejson must be a valid BEJSON 104a document."""
    triggers_path = PROJECT_ROOT / "config" / "semantic_triggers.bejson"
    assert triggers_path.is_file(), f"Missing: {triggers_path}"
    doc = bejson_core.bejson_core_load_file(str(triggers_path))
    validation_result = bejson_validator.validate_bejson(doc, is_file=False)
    assert validation_result.valid, f"Validation failed: {validation_result.errors}"
    assert doc["Format_Version"] == "104a"
    assert doc["Records_Type"] == ["SemanticTrigger"]


def test_semantic_triggers_schema_has_required_fields():
    """All 6 required fields must be present in the schema."""
    triggers_path = PROJECT_ROOT / "config" / "semantic_triggers.bejson"
    doc = bejson_core.bejson_core_load_file(str(triggers_path))
    field_map = bejson_core.bejson_core_get_field_map(doc)
    required_field_names = [
        "trigger_name", "semantic_conditions", "negative_conditions",
        "triggered_action", "cooldown_seconds", "priority",
    ]
    for field_name in required_field_names:
        assert field_name in field_map, f"Missing field: {field_name}"


def test_semantic_triggers_has_at_least_five_rows():
    """Must have at least 5 sample trigger rows for testing."""
    triggers_path = PROJECT_ROOT / "config" / "semantic_triggers.bejson"
    doc = bejson_core.bejson_core_load_file(str(triggers_path))
    assert len(doc.get("Values", [])) >= 5, "Need at least 5 trigger rows"


# ── Test 2: Condition evaluation ──────────────────────────────────────────

def test_positive_condition_matches_substring():
    """A positive condition phrase present in the message should match."""
    result = semantic_triggers.evaluate_semantic_conditions(
        "I need to validate my bejson schema",
        "validate|schema check|verify bejson",
        "delete|remove",
    )
    assert result["triggered"] is True
    assert "validate" in result["matched_positive"]
    assert result["matched_negative"] == []


def test_negative_condition_blocks_trigger():
    """A negative condition present in the message should block the trigger."""
    result = semantic_triggers.evaluate_semantic_conditions(
        "delete the bejson validator please",
        "validate|schema check|verify bejson",
        "delete|remove",
    )
    assert result["triggered"] is False
    assert "delete" in result["matched_negative"]


def test_no_positive_match_means_no_trigger():
    """No positive condition match → trigger not fired."""
    result = semantic_triggers.evaluate_semantic_conditions(
        "how is the weather today",
        "validate|schema check|verify bejson",
        "delete|remove",
    )
    assert result["triggered"] is False
    assert result["matched_positive"] == []


def test_multiple_positives_can_match():
    """Multiple positive phrases can match simultaneously."""
    result = semantic_triggers.evaluate_semantic_conditions(
        "please validate and verify bejson 104 schema check",
        "validate|schema check|verify bejson",
        "delete|remove",
    )
    assert result["triggered"] is True
    assert len(result["matched_positive"]) >= 2


def test_negative_blocks_even_with_positive_match():
    """Even with positive matches, a negative match blocks the trigger."""
    result = semantic_triggers.evaluate_semantic_conditions(
        "validate and then remove the old schema",
        "validate|schema check",
        "remove|delete",
    )
    assert result["triggered"] is False
    assert len(result["matched_positive"]) >= 1
    assert "remove" in result["matched_negative"]


# ── Test 3: Pipe-separated parsing ────────────────────────────────────────

def test_parse_pipe_separated_conditions():
    """Pipe-separated strings should split into cleaned phrases."""
    phrases = semantic_triggers._parse_pipe_separated_conditions(
        "  validate | schema check |verify bejson  | "
    )
    assert phrases == ["validate", "schema check", "verify bejson"]


def test_parse_empty_conditions():
    """Empty string returns empty list."""
    assert semantic_triggers._parse_pipe_separated_conditions("") == []
    assert semantic_triggers._parse_pipe_separated_conditions(None) == []


# ── Test 4: Cooldown enforcement ──────────────────────────────────────────

def test_cooldown_prevents_refiring(tmp_path):
    """A trigger that just fired should not fire again within cooldown."""
    triggers_bejson = _create_test_triggers_file(tmp_path)
    cooldown_state = {}
    now_ts = time.time()

    # First scan: should fire
    results_first = semantic_triggers.scan_semantic_triggers(
        "validate my schema",
        triggers_bejson,
        cooldown_state,
        now_ts,
        300,
    )
    fired_first = [trigger_result for trigger_result in results_first if trigger_result["fired"]]
    assert len(fired_first) >= 1

    # Second scan immediately: should NOT fire (cooldown)
    results_second = semantic_triggers.scan_semantic_triggers(
        "validate my schema",
        triggers_bejson,
        cooldown_state,
        now_ts + 1,  # 1 second later
        300,
    )
    fired_second = [trigger_result for trigger_result in results_second if trigger_result["fired"]]
    assert len(fired_second) == 0


def test_cooldown_expires_allows_refiring(tmp_path):
    """After cooldown expires, the trigger should fire again."""
    triggers_bejson = _create_test_triggers_file(tmp_path)
    cooldown_state = {}
    now_ts = time.time()

    # First scan
    semantic_triggers.scan_semantic_triggers(
        "validate my schema",
        triggers_bejson,
        cooldown_state,
        now_ts,
        300,
    )

    # After cooldown (300s + 1)
    results_after = semantic_triggers.scan_semantic_triggers(
        "validate my schema",
        triggers_bejson,
        cooldown_state,
        now_ts + 301,
        300,
    )
    fired_after = [trigger_result for trigger_result in results_after if trigger_result["fired"]]
    assert len(fired_after) >= 1


# ── Test 5: skill:// protocol resolution ──────────────────────────────────

def test_skill_protocol_resolves_path():
    """skill:///path/to/skill should resolve to Path(/path/to/skill)."""
    result_path = semantic_triggers.resolve_triggered_action_path(
        "skill:///data/data/com.termux/files/home/.gemini/config/skills/bejson-104-validator"
    )
    assert result_path == Path("/data/data/com.termux/files/home/.gemini/config/skills/bejson-104-validator")


def test_absolute_path_resolves_directly():
    """/absolute/path should resolve directly."""
    result_path = semantic_triggers.resolve_triggered_action_path("/some/skill/folder")
    assert result_path == Path("/some/skill/folder")


def test_empty_action_returns_none():
    """Empty triggered_action should return None."""
    assert semantic_triggers.resolve_triggered_action_path("") is None
    assert semantic_triggers.resolve_triggered_action_path(None) is None


# ── Test 6: Skill folder chunking ─────────────────────────────────────────

def test_chunk_skill_folder_reads_skill_md(tmp_path):
    """chunk_skill_folder should read SKILL.md and produce chunked output."""
    skill_folder = _create_test_skill_folder(tmp_path)
    chunk_text = semantic_triggers.chunk_skill_folder(skill_folder, budget_chars=5000)
    assert chunk_text is not None
    assert "Test Validator Skill" in chunk_text
    assert "Skill Directory:" in chunk_text


def test_chunk_skill_folder_respects_budget(tmp_path):
    """Output should be truncated at budget_chars."""
    skill_folder = _create_test_skill_folder(tmp_path)
    chunk_text = semantic_triggers.chunk_skill_folder(skill_folder, budget_chars=100)
    assert chunk_text is not None
    assert len(chunk_text) <= 100
    assert "[truncated]" in chunk_text


def test_chunk_skill_folder_returns_none_for_missing():
    """Missing skill folder should return None."""
    result = semantic_triggers.chunk_skill_folder(Path("/nonexistent/skill"))
    assert result is None


def test_chunk_skill_folder_lists_scripts(tmp_path):
    """Script subdirectory contents should be listed in metadata."""
    skill_folder = _create_test_skill_folder(tmp_path)
    chunk_text = semantic_triggers.chunk_skill_folder(skill_folder, budget_chars=5000)
    assert "scripts/check_format.py" in chunk_text


# ── Test 7: Conditions awareness section ──────────────────────────────────

def test_awareness_section_shows_all_triggers(tmp_path):
    """Awareness section should list ALL triggers regardless of fired state."""
    triggers_bejson = _create_test_triggers_file(tmp_path)
    cooldown_state = {}

    # Message that matches only one trigger
    all_results = semantic_triggers.scan_semantic_triggers(
        "validate schema",
        triggers_bejson,
        cooldown_state,
        time.time(),
        300,
    )

    awareness_text, awareness_chars = semantic_triggers.build_conditions_awareness_section(
        all_results, budget_chars=5000
    )

    # Should show both the matched and unmatched triggers
    assert "Test Schema Validator" in awareness_text
    assert "Test Fluff Auditor" in awareness_text
    assert awareness_chars > 0


def test_awareness_section_shows_status_indicators(tmp_path):
    """Fired triggers get ✓ ACTIVE, idle ones get ○ IDLE."""
    triggers_bejson = _create_test_triggers_file(tmp_path)
    cooldown_state = {}

    all_results = semantic_triggers.scan_semantic_triggers(
        "validate schema",
        triggers_bejson,
        cooldown_state,
        time.time(),
        300,
    )

    awareness_text, _ = semantic_triggers.build_conditions_awareness_section(
        all_results, budget_chars=5000
    )

    assert "✓ ACTIVE" in awareness_text
    assert "○ IDLE" in awareness_text


# ── Test 8: Triggered actions section ─────────────────────────────────────

def test_triggered_actions_only_includes_fired(tmp_path):
    """Triggered actions section should only include fired triggers."""
    skill_folder = _create_test_skill_folder(tmp_path)
    triggers_bejson = _create_test_triggers_file(tmp_path, skill_path=str(skill_folder))
    cooldown_state = {}

    all_results = semantic_triggers.scan_semantic_triggers(
        "validate schema",
        triggers_bejson,
        cooldown_state,
        time.time(),
        300,
    )

    actions_text, actions_chars = semantic_triggers.build_triggered_actions_section(
        all_results, budget_chars=5000
    )

    assert actions_chars > 0
    assert "Triggered: Test Schema Validator" in actions_text
    assert "Test Validator Skill" in actions_text  # SKILL.md content
    # Should NOT include the fluff auditor skill content
    assert "Fluff detection" not in actions_text


def test_no_fired_triggers_produces_empty_actions(tmp_path):
    """When no triggers fire, actions section should be empty."""
    triggers_bejson = _create_test_triggers_file(tmp_path)
    cooldown_state = {}

    # Message that matches nothing
    all_results = semantic_triggers.scan_semantic_triggers(
        "hello how are you",
        triggers_bejson,
        cooldown_state,
        time.time(),
        300,
    )

    actions_text, actions_chars = semantic_triggers.build_triggered_actions_section(
        all_results, budget_chars=5000
    )

    assert actions_text == ""
    assert actions_chars == 0


# ── Test 9: Full pipeline end-to-end ──────────────────────────────────────

def test_full_pipeline_with_positive_match(tmp_path):
    """Full pipeline: positive match → awareness + skill injection."""
    skill_folder = _create_test_skill_folder(tmp_path)
    triggers_bejson = _create_test_triggers_file(tmp_path, skill_path=str(skill_folder))
    cooldown_state = {}

    full_text, awareness_chars, actions_chars = semantic_triggers.build_semantic_triggers_context(
        "validate my bejson schema please",
        triggers_bejson,
        cooldown_state,
        awareness_budget_chars=3000,
        action_budget_chars=5000,
        global_default_cooldown_seconds=300,
    )

    assert awareness_chars > 0
    assert actions_chars > 0
    assert "✓ ACTIVE" in full_text
    assert "Test Validator Skill" in full_text


def test_full_pipeline_with_no_match(tmp_path):
    """Full pipeline: no match → awareness only (conditions visible, no injection)."""
    triggers_bejson = _create_test_triggers_file(tmp_path)
    cooldown_state = {}

    full_text, awareness_chars, actions_chars = semantic_triggers.build_semantic_triggers_context(
        "completely unrelated message about weather",
        triggers_bejson,
        cooldown_state,
    )

    assert awareness_chars > 0  # Conditions always visible
    assert actions_chars == 0   # No skill injection


def test_full_pipeline_with_negative_block(tmp_path):
    """Full pipeline: positive + negative match → awareness only, no injection."""
    triggers_bejson = _create_test_triggers_file(tmp_path)
    cooldown_state = {}

    full_text, awareness_chars, actions_chars = semantic_triggers.build_semantic_triggers_context(
        "delete the validator schema",
        triggers_bejson,
        cooldown_state,
    )

    assert awareness_chars > 0
    assert actions_chars == 0  # Blocked by negative condition
    assert "✗ BLOCKED" in full_text


# ── Test 10: Priority ordering ────────────────────────────────────────────

def test_triggers_sorted_by_priority(tmp_path):
    """Results should be sorted by priority (1=highest first)."""
    triggers_bejson = _create_test_triggers_file(tmp_path)
    cooldown_state = {}

    all_results = semantic_triggers.scan_semantic_triggers(
        "validate schema fluff audit",
        triggers_bejson,
        cooldown_state,
        time.time(),
        300,
    )

    priorities = [trigger_result["priority"] for trigger_result in all_results]
    assert priorities == sorted(priorities), f"Not sorted by priority: {priorities}"


# ── Test 11: Integration — _paths() registers semantic_triggers ───────────

def test_context_bubble_paths_includes_semantic_triggers():
    """The _paths() helper must register semantic_triggers.bejson."""
    import lib_bejson_newagent_context_bubble as context_bubble_module
    test_paths = context_bubble_module._paths(
        Path("/tmp/context"), Path("/tmp/config"), Path("/tmp/logs")
    )
    assert "semantic_triggers" in test_paths
    assert str(test_paths["semantic_triggers"]).endswith("semantic_triggers.bejson")


# ── Test helpers ──────────────────────────────────────────────────────────

def _create_test_skill_folder(base_tmp_path: Path) -> Path:
    """Create a minimal test skill folder with SKILL.md and scripts/."""
    skill_folder = base_tmp_path / "test-validator-skill"
    scripts_dir = skill_folder / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    (skill_folder / "SKILL.md").write_text(
        "---\n"
        "name: test-validator-skill\n"
        "description: Test Validator Skill for schema checking.\n"
        "---\n"
        "# Test Validator Skill\n"
        "Run `scripts/check_format.py` to validate documents.\n"
        "Use when validating BEJSON schemas.\n"
        "Do NOT use for HTML formatting.\n",
        encoding="utf-8",
    )
    (scripts_dir / "check_format.py").write_text(
        "import sys\nprint('CHECK_OK:' + ','.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return skill_folder


def _create_test_triggers_file(
    base_tmp_path: Path,
    skill_path: str = "/nonexistent/test-skill",
) -> Path:
    """Create a minimal semantic_triggers.bejson for testing."""
    triggers_doc = {
        "Format": "BEJSON",
        "Format_Version": "104a",
        "Format_Creator": "Elton Boehnen",
        "Records_Type": ["SemanticTrigger"],
        "Fields": [
            {"name": "trigger_name", "type": "string"},
            {"name": "semantic_conditions", "type": "string"},
            {"name": "negative_conditions", "type": "string"},
            {"name": "triggered_action", "type": "string"},
            {"name": "cooldown_seconds", "type": "integer"},
            {"name": "priority", "type": "integer"},
        ],
        "Values": [
            [
                "Test Schema Validator",
                "validate|schema|verify bejson|104 schema",
                "delete|remove|uninstall",
                f"skill://{skill_path}",
                300,
                1,
            ],
            [
                "Test Fluff Auditor",
                "fluff|marketing|buzzword|audit label",
                "create fluff|write marketing",
                "skill:///nonexistent/fluff-auditor",
                900,
                2,
            ],
        ],
    }
    triggers_file_path = base_tmp_path / "semantic_triggers.bejson"
    triggers_file_path.write_text(
        json.dumps(triggers_doc, indent=2), encoding="utf-8"
    )
    return triggers_file_path
