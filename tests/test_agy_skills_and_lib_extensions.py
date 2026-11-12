"""
Tests for NewAgent v3.49.0 pkg133 (agents.md Directives 1-4):
1. Tool config library routing (shared_lib_directory & lib_extensions_directory).
2. Release 300 BEJSON 104 library synchronization in lib/ and lib_extensions/.
3. Config-gated Antigravity (agy) skills compatibility layer (agy_skills_enabled true/false).
4. Official Tooling System Report in docs/Tooling_System_Report.md.

Author: Elton Boehnen · boehnenelton2024@gmail.com · boehnenelton2024.pages.dev · github.com/boehnenelton
"""

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

import lib_bejson_Core_bejson_core as bejson_core
import lib_bejson_Core_bejson_validator as bejson_validator
import lib_bejson_newagent_actions as actions
import lib_bejson_newagent_agy_skills as agy_skills
import lib_bejson_newagent_commands as commands
import lib_bejson_newagent_config as config_lib
import lib_bejson_newagent_context_bubble as context_bubble
from lib_bejson_newagent_tui import SessionStats


def _create_sample_skill_tree(base_tmp_path: Path) -> Path:
    skills_root = base_tmp_path / "skills"
    sample_skill_dir = skills_root / "bejson-104-validator"
    scripts_dir = sample_skill_dir / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)

    (sample_skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: bejson-104-validator\n"
        "description: Validate Foundational Era BEJSON 104, 104a, and 104db documents.\n"
        "---\n"
        "# BEJSON 104 Validator\n"
        "Run `scripts/check_104.py` to validate documents.\n",
        encoding="utf-8",
    )
    (scripts_dir / "check_104.py").write_text(
        "import sys\nprint('CHECK_OK:' + ','.join(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return skills_root


def test_tool_configs_route_to_lib_and_lib_extensions():
    tool_config_paths = [
        PROJECT_ROOT / "tools" / "NA-MD2HTML" / "md-to-html.config.json",
        PROJECT_ROOT / "tools" / "NA-Chunker" / "config" / "config.json",
        PROJECT_ROOT / "tools" / "NA-WebToolkit" / "config" / "config.json",
        PROJECT_ROOT / "tools" / "NA-Init" / "config" / "config.json",
    ]
    for config_file in tool_config_paths:
        assert config_file.is_file(), f"Missing tool config: {config_file}"
        doc = bejson_core.bejson_core_load_file(str(config_file))
        validation_res = bejson_validator.validate_bejson(doc, is_file=False)
        assert validation_res.valid, f"{config_file} failed BEJSON validation: {validation_res.errors}"
        field_map = bejson_core.bejson_core_get_field_map(doc)
        name_idx = field_map["setting_name"]
        val_idx = field_map["setting_value"]
        settings_dict = {
            row[name_idx]: row[val_idx]
            for row in doc.get("Values", [])
            if len(row) > max(name_idx, val_idx)
        }
        assert "shared_lib_directory" in settings_dict, f"{config_file} missing shared_lib_directory"
        assert "lib_extensions_directory" in settings_dict, f"{config_file} missing lib_extensions_directory"


def test_lib_extensions_contains_synced_104_libraries():
    core_dir = PROJECT_ROOT / "lib"
    ext_dir = PROJECT_ROOT / "lib_extensions"
    assert core_dir.is_dir()
    assert ext_dir.is_dir()
    expected_core_libs = [
        "lib_bejson_Core_bejson_core.py",
        "lib_bejson_Core_bejson_validator.py",
        "lib_bejson_Core_bejson_env.py",
        "lib_bejson_Core_bejson_errors.py",
        "lib_bejson_Core_bejson_path_guard.py",
        "lib_bejson_Core_mfdb_core.py",
        "lib_bejson_Core_mfdb_validator.py",
    ]
    for core_filename in expected_core_libs:
        assert (core_dir / core_filename).is_file(), f"Missing {core_filename} in lib/"

    expected_ext_libs = [
        "lib_bejson_Utility_bejson_utility.py",
        "lib_bejson_MD_md_ops.py",
        "lib_bejson_Chunker_mfdb_chunker_v6.py",
        "lib_bejson_AI_ai_dispatch.py",
        "lib_bejson_AI_bejson_interactions.py",
    ]
    for lib_filename in expected_ext_libs:
        assert (ext_dir / lib_filename).is_file(), f"Missing {lib_filename} in lib_extensions/"


def test_agy_skills_disabled_by_default_in_config(tmp_path):
    temp_config_path = tmp_path / "config.json"
    loaded_cfg = config_lib.init_config(temp_config_path)
    assert "agy_skills_enabled" in loaded_cfg
    assert loaded_cfg["agy_skills_enabled"] is False
    assert isinstance(loaded_cfg.get("agy_skills_directories"), list)

    skills_root = _create_sample_skill_tree(tmp_path)
    disabled_cfg = {
        "agy_skills_enabled": False,
        "agy_skills_directories": [str(skills_root)],
    }
    assert agy_skills.is_agy_skills_enabled(disabled_cfg) is False
    assert agy_skills.discover_installed_agy_skills(disabled_cfg, force_refresh=True) == {}
    assert agy_skills.match_agy_skills_for_prompt("validate bejson 104", disabled_cfg) == []
    section_text, matched_count = agy_skills.build_agy_skills_context_section(
        "validate bejson 104", disabled_cfg
    )
    assert section_text == ""
    assert matched_count == 0

    exit_code, output_msg = agy_skills.execute_agy_skill_action(
        {"action": "list"}, "", str(tmp_path), disabled_cfg
    )
    assert exit_code == 1
    assert "[DISABLED]" in output_msg


def test_agy_skills_enabled_discovery_matching_read_and_exec(tmp_path):
    skills_root = _create_sample_skill_tree(tmp_path)
    enabled_cfg = {
        "agy_skills_enabled": True,
        "agy_skills_directories": [str(skills_root)],
        "exec_timeout_seconds": 15,
    }
    assert agy_skills.is_agy_skills_enabled(enabled_cfg) is True

    catalog = agy_skills.discover_installed_agy_skills(enabled_cfg, force_refresh=True)
    assert "bejson-104-validator" in catalog
    assert "scripts/check_104.py" in catalog["bejson-104-validator"]["scripts"]

    matched = agy_skills.match_agy_skills_for_prompt(
        "Please validate this BEJSON 104 document", enabled_cfg
    )
    assert len(matched) == 1
    assert matched[0]["skill_name"] == "bejson-104-validator"

    section_text, matched_count = agy_skills.build_agy_skills_context_section(
        "Please validate this BEJSON 104 document", enabled_cfg
    )
    assert "Antigravity (agy) Skills Compatibility Layer (ENABLED)" in section_text
    assert "bejson-104-validator" in section_text
    assert matched_count == 1

    # Read action
    read_code, read_out = agy_skills.execute_agy_skill_action(
        {"action": "read", "name": "bejson-104-validator"}, "", str(tmp_path), enabled_cfg
    )
    assert read_code == 0
    assert "# BEJSON 104 Validator" in read_out
    assert "scripts/check_104.py" in read_out

    # Exec action
    exec_code, exec_out = agy_skills.execute_agy_skill_action(
        {"action": "exec", "name": "bejson-104-validator", "script": "scripts/check_104.py"},
        "--strict sample.bejson",
        str(tmp_path),
        enabled_cfg,
    )
    assert exec_code == 0
    assert "CHECK_OK:--strict,sample.bejson" in exec_out

    # Path traversal protection
    traversal_code, traversal_out = agy_skills.execute_agy_skill_action(
        {"action": "exec", "name": "bejson-104-validator", "script": "../../outside.py"},
        "",
        str(tmp_path),
        enabled_cfg,
    )
    assert traversal_code == 1
    assert "[BLOCKED]" in traversal_out


def test_parse_actions_and_slash_command_skills_toggle(tmp_path):
    parsed = actions.parse_actions(
        '<agy_skill action="list"/>\n'
        '<agy_skill name="bejson-104-validator" action="read"></agy_skill>'
    )
    assert len(parsed) == 2
    assert parsed[0]["tag"] == "agy_skill"
    assert parsed[0]["attrs"]["action"] == "list"
    assert parsed[1]["tag"] == "agy_skill"
    assert parsed[1]["attrs"]["name"] == "bejson-104-validator"

    skills_root = _create_sample_skill_tree(tmp_path)
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    cfg = config_lib.init_config(config_dir / "config.json")
    cfg["agy_skills_directories"] = [str(skills_root)]

    ctx = {
        "config": cfg,
        "_config_dir": config_dir,
        "_cwd": str(tmp_path),
        "stats": SessionStats(),
    }

    # While disabled, run_action_queue rejects <agy_skill>
    results_disabled = asyncio.run(actions.run_action_queue([parsed[0]], ctx))
    assert results_disabled[0].exit_code == 1
    assert "[DISABLED]" in results_disabled[0].output

    # Toggle ON via /skills on
    handled, msg_on = asyncio.run(commands.handle_slash_commands("/skills on", ctx))
    assert handled is True
    assert ctx["config"]["agy_skills_enabled"] is True
    assert "ENABLED" in msg_on

    # Verify persisted to config.json on disk
    reloaded_cfg = config_lib.init_config(config_dir / "config.json")
    assert reloaded_cfg["agy_skills_enabled"] is True

    # Now run_action_queue succeeds
    results_enabled = asyncio.run(actions.run_action_queue([parsed[0]], ctx))
    assert results_enabled[0].exit_code == 0
    assert "bejson-104-validator" in results_enabled[0].output

    # Toggle OFF via /skills off
    handled, msg_off = asyncio.run(commands.handle_slash_commands("/skills off", ctx))
    assert handled is True
    assert ctx["config"]["agy_skills_enabled"] is False
    assert "DISABLED" in msg_off


def test_tooling_system_report_exists():
    report_path = PROJECT_ROOT / "docs" / "Tooling_System_Report.md"
    assert report_path.is_file()
    report_text = report_path.read_text(encoding="utf-8")
    assert "Tier 1" in report_text
    assert "Tier 4" in report_text
    assert "agy_skills_enabled" in report_text


def test_gemini_md_policy_disabled_and_enabled_tree_walking(tmp_path):
    # Create local Context/Persistent_Policy.md
    local_policy_path = tmp_path / "Persistent_Policy.md"
    local_policy_path.write_text("LOCAL_BASE_POLICY_RULE", encoding="utf-8")

    # Create global GEMINI.md (and duplicate mirror to verify hash dedup)
    global_dir_1 = tmp_path / "home_dot_gemini"
    global_dir_2 = tmp_path / "home_gemini"
    global_dir_1.mkdir(parents=True, exist_ok=True)
    global_dir_2.mkdir(parents=True, exist_ok=True)
    global_md_1 = global_dir_1 / "GEMINI.md"
    global_md_2 = global_dir_2 / "GEMINI.md"
    global_md_1.write_text("GLOBAL_GEMINI_POLICY_DIRECTIVE", encoding="utf-8")
    global_md_2.write_text("GLOBAL_GEMINI_POLICY_DIRECTIVE", encoding="utf-8")

    # Create ancestor tree: workspace_root -> sub_area -> project_leaf
    workspace_root = tmp_path / "workspace_root"
    sub_area = workspace_root / "sub_area"
    project_leaf = sub_area / "project_leaf"
    project_leaf.mkdir(parents=True, exist_ok=True)

    (workspace_root / "GEMINI.md").write_text("WORKSPACE_ROOT_GEMINI_RULE", encoding="utf-8")
    (sub_area / "AGENTS.md").write_text("SUB_AREA_AGENTS_RULE", encoding="utf-8")
    (project_leaf / "agents.md").write_text("LEAF_PROJECT_AGENTS_RULE", encoding="utf-8")

    disabled_cfg = {
        "gemini_md_policy_enabled": False,
        "gemini_md_global_paths": [str(global_md_1), str(global_md_2)],
        "gemini_md_tree_filenames": ["GEMINI.md", "AGENTS.md", "agents.md"],
        "gemini_md_max_chars": 36000,
    }
    assert context_bubble.is_gemini_md_policy_enabled(disabled_cfg) is False
    assert context_bubble.discover_gemini_md_policy_files(project_leaf, disabled_cfg) == []
    disabled_policy_text = context_bubble.build_persistent_policy_section(
        local_policy_path, project_leaf, 8000, agent_config_dict=disabled_cfg
    )
    assert disabled_policy_text == "LOCAL_BASE_POLICY_RULE"
    assert "GLOBAL_GEMINI_POLICY_DIRECTIVE" not in disabled_policy_text

    # Enable gemini_md_policy_enabled
    enabled_cfg = dict(disabled_cfg)
    enabled_cfg["gemini_md_policy_enabled"] = True
    assert context_bubble.is_gemini_md_policy_enabled(enabled_cfg) is True

    chain = context_bubble.discover_gemini_md_policy_files(project_leaf, enabled_cfg)
    # 1 global + 3 tree levels (workspace_root, sub_area, project_leaf) = 4 files
    assert len(chain) == 4
    assert chain[0][0] == "global"
    assert chain[0][1] == global_md_1.resolve()
    assert [item[1].name for item in chain[1:]] == ["GEMINI.md", "AGENTS.md", "agents.md"]

    enabled_policy_text = context_bubble.build_persistent_policy_section(
        local_policy_path, project_leaf, 8000, agent_config_dict=enabled_cfg
    )
    assert "LOCAL_BASE_POLICY_RULE" in enabled_policy_text
    assert "GLOBAL_GEMINI_POLICY_DIRECTIVE" in enabled_policy_text
    assert "WORKSPACE_ROOT_GEMINI_RULE" in enabled_policy_text
    assert "SUB_AREA_AGENTS_RULE" in enabled_policy_text
    assert "LEAF_PROJECT_AGENTS_RULE" in enabled_policy_text
    # Broadest-first to nearest-leaf-last ordering
    assert enabled_policy_text.index("GLOBAL_GEMINI_POLICY_DIRECTIVE") < enabled_policy_text.index("WORKSPACE_ROOT_GEMINI_RULE")
    assert enabled_policy_text.index("WORKSPACE_ROOT_GEMINI_RULE") < enabled_policy_text.index("SUB_AREA_AGENTS_RULE")
    assert enabled_policy_text.index("SUB_AREA_AGENTS_RULE") < enabled_policy_text.index("LEAF_PROJECT_AGENTS_RULE")

    # Test /geminimd slash command toggle and persistence
    config_dir = tmp_path / "cfg_store"
    config_dir.mkdir(parents=True, exist_ok=True)
    persisted_cfg = config_lib.init_config(config_dir / "config.json")
    assert persisted_cfg["gemini_md_policy_enabled"] is False
    persisted_cfg["gemini_md_global_paths"] = [str(global_md_1)]

    ctx = {
        "config": persisted_cfg,
        "_config_dir": config_dir,
        "_cwd": str(project_leaf),
        "stats": SessionStats(),
    }
    handled_on, out_on = asyncio.run(commands.handle_slash_commands("/geminimd on", ctx))
    assert handled_on is True
    assert ctx["config"]["gemini_md_policy_enabled"] is True
    assert "ENABLED" in out_on
    assert config_lib.init_config(config_dir / "config.json")["gemini_md_policy_enabled"] is True

    handled_off, out_off = asyncio.run(commands.handle_slash_commands("/geminimd off", ctx))
    assert handled_off is True
    assert ctx["config"]["gemini_md_policy_enabled"] is False
    assert "DISABLED" in out_off
    assert config_lib.init_config(config_dir / "config.json")["gemini_md_policy_enabled"] is False


def test_config_manager_57col_positional_tui(tmp_path):
    import lib_bejson_newagent_config_tui as config_tui

    mgr = config_tui.NewAgentConfigManagerState(tmp_path)

    # 1. Verify 100% coverage of all 67 configuration options across 7 categories
    total_opts, mod_opts = mgr.count_total_options_and_modifications()
    expected_total = (
        len(config_lib.DEFAULT_CONFIG)
        + len(context_bubble._DEFAULT_CONSTANTS)
        + len(config_tui.CLI_AGENT_DEFAULT_SCHEMA)
    )
    assert total_opts == expected_total == 67
    assert mod_opts == 0
    assert len(mgr.categories_list) == 7

    # 2. Verify strict 57-column ceiling across EVERY screen and EVERY option
    def _assert_57_col(lines_list: list[str]) -> None:
        assert len(lines_list) > 0
        for line_str in lines_list:
            visible = config_tui.strip_ansi_sequences(line_str)
            assert len(visible) <= 57, f"Line exceeded 57 cols ({len(visible)}): {visible!r}"

    _assert_57_col(config_tui.render_root_dashboard_lines(mgr))
    _assert_57_col(config_tui.render_validation_and_probe_lines(mgr, mode="validate"))
    _assert_57_col(config_tui.render_validation_and_probe_lines(mgr, mode="probe"))
    _assert_57_col(config_tui.render_about_screen_lines())
    _assert_57_col(config_tui.render_search_results_lines(mgr, "gemini", mgr.search_options("gemini")))

    for cat_desc in mgr.categories_list:
        _assert_57_col(config_tui.render_category_submenu_lines(mgr, cat_desc))
        for row_idx in range(1, len(cat_desc.option_keys_order) + 1):
            _assert_57_col(config_tui.render_option_inspector_lines(mgr, cat_desc, row_idx))

    # 3. Simulate interactive menu navigation, preset selection, backup, and validation
    scripted_inputs = iter([
        "1",       # Open Cat 01 [ENG]
        "T 1",     # Toggle/cycle row 01 (engine_mode: rest -> interactions)
        "B",       # Back to Root
        "3",       # Open Cat 03 [MEM]
        "4",       # Inspect row 04 (gemini_md_policy_enabled)
        "1",       # Pick preset 01 (True)
        "B",       # Back to Cat 03
        "B",       # Back to Root
        "6",       # Open Cat 06 [BUB]
        "T 12",    # Toggle row 12 (observer_enabled: false -> true)
        "B",       # Back to Root
        "V",       # Open Validator screen
        "B",       # Back to Root
        "K",       # Create snapshot backup
        "Q",       # Quit & sync
    ])
    captured_screens: list[str] = []
    controller = config_tui.PositionalConfigTUIController(
        mgr,
        input_provider=lambda _prompt: next(scripted_inputs),
        output_writer=lambda block: captured_screens.append(block),
    )
    rc = controller.run_interactive_loop()
    assert rc == config_tui.EXIT_CODE_SUCCESS
    assert mgr.get_option_value("engine_mode") == "interactions"
    assert mgr.get_option_value("gemini_md_policy_enabled") is True
    assert mgr.get_option_value("observer_enabled") is True
    assert len(list((tmp_path / "backups").glob("*.bak"))) == 3

    # Verify all 3 stores validate cleanly on disk
    for _, _, _, status_tag in mgr.validate_all_bejson_stores():
        assert status_tag == "VALID_104A"

    # 4. Verify Policy §8.5 / §8.7 deterministic exit code 10 on picker failure
    picker_fail_inputs = iter([
        "4",   # Open Cat 04 [EXT]
        "3",   # Open row 03 (lib_extensions_directory)
        "P",   # Invoke Termux picker -> fails with Exit Code 10
    ])
    fail_controller = config_tui.PositionalConfigTUIController(
        mgr,
        input_provider=lambda _prompt: next(picker_fail_inputs),
        output_writer=lambda _block: None,
        picker_callable=lambda _title: (False, "TERMUX_API_MISSING"),
    )
    assert fail_controller.run_interactive_loop() == config_tui.EXIT_CODE_PICKER_FAILURE == 10

    # 5. Verify /cfgmenu slash command integration
    ctx = {
        "config": mgr.store_values_map["main_config"],
        "_config_dir": tmp_path / "config",
        "_cwd": str(tmp_path),
        "stats": SessionStats(),
    }
    handled_root, out_root = asyncio.run(commands.handle_slash_commands("/cfgmenu", ctx))
    assert handled_root is True
    _assert_57_col(out_root.splitlines())

    handled_cat, out_cat = asyncio.run(commands.handle_slash_commands("/cfgmenu MEM", ctx))
    assert handled_cat is True
    _assert_57_col(out_cat.splitlines())

