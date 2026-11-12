"""
Tests for NewAgent Context Keyword Optimization:
Skills Integration, Remote URL Fetching, and Repo URL Resolution in Context Bubble.

Covers:
  1. resolve_context_target() with skill:// and agy:// protocol paths
  2. resolve_context_target() with repo:// translation to raw GitHub URLs
  3. resolve_context_target() with https:// and http:// remote URLs
  4. TTL caching and deduplication for remote URL content
  5. Graceful fallback on network errors or unreachable URLs
  6. resolve_context_target() backward-compatibility with kb:// knowledge entries
  7. resolve_context_target() backward-compatibility with local situational files
  8. build_keyword_section() injecting skill definitions when triggered
  9. build_keyword_section() injecting repo context when triggered
  10. triggers.bejson BEJSON 104a conformance with optimized skill/repo rows

Author: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
"""

import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import lib_bejson_Core_bejson_core as bejson_core
import lib_bejson_Core_bejson_validator as bejson_validator
import lib_bejson_newagent_context_bubble as context_bubble


def test_triggers_bejson_schema_valid_with_skill_and_repo_rows():
    """config/triggers.bejson must remain valid BEJSON 104a."""
    triggers_path = PROJECT_ROOT / "config" / "triggers.bejson"
    assert triggers_path.is_file()
    doc = bejson_core.bejson_core_load_file(str(triggers_path))
    val_res = bejson_validator.validate_bejson(doc, is_file=False)
    assert val_res.valid, f"triggers.bejson invalid: {val_res.errors}"
    assert len(doc.get("Values", [])) >= 80


def test_resolve_repo_url_translation():
    """repo:// URLs must correctly resolve to raw.githubusercontent.com URLs."""
    url1 = context_bubble._resolve_repo_url("repo://boehnenelton/NewAgent/master/README.md")
    assert url1 == "https://raw.githubusercontent.com/boehnenelton/NewAgent/master/README.md"

    # Default to master branch when only 3 segments given
    url2 = context_bubble._resolve_repo_url("repo://boehnenelton/NewAgent/README.md")
    assert url2 == "https://raw.githubusercontent.com/boehnenelton/NewAgent/master/README.md"


def test_resolve_context_target_skill_protocol(tmp_path):
    """skill:// protocol should load and chunk the referenced SKILL.md."""
    # Test using the repository-local skill
    result = context_bubble.resolve_context_target(
        "skill://bejson-104-validator",
        situational_dir=tmp_path,
        budget_chars=4000,
    )
    assert result is not None
    assert "BEJSON 104 Validator" in result or "bejson-104-validator" in result
    assert "Skill Directory:" in result


def test_resolve_context_target_kb_protocol(tmp_path):
    """kb:// protocol must continue resolving knowledge_pool entries."""
    kp_path = PROJECT_ROOT / "config" / "knowledge_pool.bejson"
    result = context_bubble.resolve_context_target(
        "kb://behtml_1",
        situational_dir=tmp_path,
        knowledge_path=kp_path,
        budget_chars=2000,
    )
    assert result is not None
    assert "BEHTML" in result


def test_resolve_context_target_local_file(tmp_path):
    """Local files in situational_dir must continue resolving correctly."""
    test_file = tmp_path / "custom_tool.md"
    test_file.write_text("# Custom Tool Instructions\nRun custom_tool --help\n", encoding="utf-8")

    result = context_bubble.resolve_context_target(
        "custom_tool.md",
        situational_dir=tmp_path,
        budget_chars=2000,
    )
    assert result is not None
    assert "Custom Tool Instructions" in result


def test_resolve_context_target_remote_url_with_mock():
    """Remote URLs should fetch content and cache via TTL cache."""
    test_url = "https://example.com/mock-context.md"
    mock_payload = b"# Mock Context Content\nImportant guidelines from remote repo.\n"

    mock_resp = MagicMock()
    mock_resp.read.return_value = mock_payload
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        content = context_bubble.resolve_context_target(
            test_url,
            situational_dir=PROJECT_ROOT / "Context" / "Situational_Awareness",
            budget_chars=2000,
        )
        assert content is not None
        assert "Mock Context Content" in content

        # Second call should serve from in-memory cache without hitting urlopen again
        with patch("urllib.request.urlopen", side_effect=AssertionError("Should not be called")):
            cached_content = context_bubble.resolve_context_target(
                test_url,
                situational_dir=PROJECT_ROOT / "Context" / "Situational_Awareness",
                budget_chars=2000,
            )
            assert cached_content == content


def test_resolve_context_target_url_network_error_fails_open(tmp_path):
    """Network failure or unreachable URL fails open gracefully without raising."""
    with patch("urllib.request.urlopen", side_effect=OSError("Network unreachable")):
        content = context_bubble.resolve_context_target(
            "https://unreachable-host.example.com/docs.md",
            situational_dir=tmp_path,
            budget_chars=2000,
        )
        assert content is None


def test_build_keyword_section_with_skills_and_urls(tmp_path):
    """build_keyword_section should inject skill content and dedup properly."""
    matches = [
        {"keyword": "bejson validator", "context_path": "skill://bejson-104-validator"},
        {"keyword": "kb behtml", "context_path": "kb://behtml_1"},
    ]
    kp_path = PROJECT_ROOT / "config" / "knowledge_pool.bejson"

    section_text, used_chars = context_bubble.build_keyword_section(
        matches,
        situational_dir=tmp_path,
        budget_chars=10000,
        knowledge_path=kp_path,
    )

    assert used_chars > 0
    assert "[bejson validator]" in section_text
    assert "[kb behtml]" in section_text
    assert "BEHTML" in section_text
