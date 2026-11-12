# Technical Overview — Sub-Agent Library Family

Format: File_Name / Function_Name (var1, var2, var3)

Scope note: this file currently only covers the sub-agent library family
added 2026-09-12 (pkg112). It does not yet backfill signatures for the
rest of the existing NewAgent codebase (agent.py, cliagent.py, webagent.py,
JobMaker.py, or the pre-existing lib_bejson_newagent_*.py files) -- that's
a separate, much larger documentation pass outside this family's own
scope. Add to this file (don't replace it) as the sub-agent family grows.

## lib_bejson_newagent_subagent_common.py

- profiles_dir(subagents_dir)
- sessions_path(subagents_dir)
- signals_path(subagents_dir)
- ensure_subagent_dirs(subagents_dir)
- row_to_dict(doc, row)
- dict_to_row(doc, record, defaults=None)
- with_file_lock(path, mutate_fn, empty_doc_factory, lock_timeout=10.0, lock_stale_after=30.0)

## lib_bejson_newagent_subagent_profiles.py

- make_profile_doc(profile_name, role_description="", system_prompt="", model_override="", allowed_actions=None, exec_denylist_override=None, max_turns=DEFAULT_MAX_TURNS)
- save_profile(subagents_dir, profile_name, doc)
- load_profile(subagents_dir, profile_name)
- list_profiles(subagents_dir)
- delete_profile(subagents_dir, profile_name)
- action_allowed(profile, action_tag)

## lib_bejson_newagent_subagent_sessions.py

- create_session(subagents_dir, profile_name, task_description, cwd, parent_session_id="", metadata=None)
- load_session(subagents_dir, session_id)
- list_sessions(subagents_dir, status=None, parent_session_id=None)
- update_session(subagents_dir, session_id, status=None, current_step=None, cwd=None, append_history=None, max_history_turns=None, awaiting_signal_types=None, metadata_delta=None, increment_turn_count=False, result=None)
- delete_session(subagents_dir, session_id)

Status constants: STATUS_ACTIVE, STATUS_BUSY, STATUS_WAITING_SIGNAL, STATUS_COMPLETED, STATUS_ERROR

## lib_bejson_newagent_subagent_signals.py

- send_signal(subagents_dir, session_id, signal_type, payload=None)
- poll_signals(subagents_dir, session_id, signal_type=None)
- consume_signal(subagents_dir, signal_id)

## lib_bejson_newagent_subagent_runtime.py

- run_subagent_turn(subagents_dir, session_id, config, key_reg, model_reg, catalog_path, backups_dir=None, config_dir=None, jobs_dir=None, logs_dir=None, timeout=90, max_retries=3) [async]
- dispatch_subagent(subagents_dir, profile_name, task_description, cwd, config, key_reg, model_reg, catalog_path, parent_session_id="", metadata=None, backups_dir=None, config_dir=None, jobs_dir=None, logs_dir=None, timeout=90, max_retries=3) [async]
- resume_subagent(subagents_dir, session_id, config, key_reg, model_reg, catalog_path, backups_dir=None, config_dir=None, jobs_dir=None, logs_dir=None, timeout=90, max_retries=3) [async]
- _extract_await_signal(response_text)
- _strip_await_signal(response_text)

Class: _ScopedModelRegistry(active_model) -- throwaway `.active`-only stand-in for rest.ModelRegistry, used to apply a profile's model_override for one turn without persisting it to the shared models.bejson.

## subagent_admin.py (CLI, not a library -- lib/ convention doesn't apply)

- _bootstrap_engine(config)
- cmd_create_profile / cmd_list_profiles / cmd_show_profile / cmd_delete_profile
- cmd_list_sessions / cmd_show_session / cmd_send_signal
- cmd_dispatch / cmd_resume
- build_parser()

## lib_bejson_newagent_help.py
Data-driven help. Registry: config/help.bejson (BEJSON 104, Records_Type HelpEntry); help_topic is the topic discriminator, help_kind is topic | command | note | example.
- load_registry(path) -> Optional[HelpRegistry]  (mtime-cached; None if missing/malformed)
- resolve(reg, query) -> (kind, obj)  (topic > command > unique prefix > unknown)
- render_index(reg) / render_topic(reg, topic) / render_command(reg, cmd) / render_unknown(reg, query)
- render_help(query="", config_dir=None)  (entry point for /help [query])
- render_command_help(cmd, config_dir=None) -> Optional[str]  (entry point for /<cmd> help)
- registry_path_for(config_dir)

## lib_bejson_newagent_session.py
- lib_bejson_newagent_session.py / _render_transcript_markdown (session_name, rows, fmap=None)
- lib_bejson_newagent_session.py / convert_session_to_markdown (sessions_dir, session_name)

## lib_bejson_newagent_engine_interactions.py
- lib_bejson_newagent_engine_interactions.py / InteractionsPrompter.run_turn (user_input, system_instruction="", denylist=None, dryrun=False)

## lib_bejson_newagent_agy_skills.py
- lib_bejson_newagent_agy_skills.py / is_agy_skills_enabled (agent_config_dict)
- lib_bejson_newagent_agy_skills.py / get_configured_skill_directories (agent_config_dict)
- lib_bejson_newagent_agy_skills.py / discover_installed_agy_skills (agent_config_dict, force_refresh=False)
- lib_bejson_newagent_agy_skills.py / match_agy_skills_for_prompt (user_prompt_text, agent_config_dict, max_matched_skills=5)
- lib_bejson_newagent_agy_skills.py / build_agy_skills_context_section (user_prompt_text, agent_config_dict, budget_chars=1600)
- lib_bejson_newagent_agy_skills.py / execute_agy_skill_action (skill_action_attrs, skill_action_content, current_working_dir, agent_config_dict)
- lib_bejson_newagent_agy_skills.py / format_agy_skills_status_report (agent_config_dict, filter_query="")

## lib_bejson_newagent_context_bubble.py (GEMINI.md Persistent Policy Extensions)
- lib_bejson_newagent_context_bubble.py / is_gemini_md_policy_enabled (agent_config_dict)
- lib_bejson_newagent_context_bubble.py / discover_gemini_md_policy_files (cwd_target_path, agent_config_dict)
- lib_bejson_newagent_context_bubble.py / build_persistent_policy_section (local_policy_path, cwd_target_path, base_policy_budget_chars, agent_config_dict=None)
- lib_bejson_newagent_context_bubble.py / format_gemini_md_policy_status_report (cwd_target_path, agent_config_dict)

## lib_bejson_newagent_config_tui.py & config_manager.py
- lib_bejson_newagent_config_tui.py / NewAgentConfigManagerState.__init__ (project_root_path)
- lib_bejson_newagent_config_tui.py / NewAgentConfigManagerState.reload_all_stores ()
- lib_bejson_newagent_config_tui.py / NewAgentConfigManagerState.save_store (store_identifier)
- lib_bejson_newagent_config_tui.py / NewAgentConfigManagerState.set_option_value (option_key_name, new_raw_value)
- lib_bejson_newagent_config_tui.py / NewAgentConfigManagerState.toggle_or_cycle_option (option_key_name)
- lib_bejson_newagent_config_tui.py / NewAgentConfigManagerState.validate_all_bejson_stores ()
- lib_bejson_newagent_config_tui.py / NewAgentConfigManagerState.probe_configured_paths ()
- lib_bejson_newagent_config_tui.py / render_root_dashboard_lines (state)
- lib_bejson_newagent_config_tui.py / render_category_submenu_lines (state, category_desc)
- lib_bejson_newagent_config_tui.py / render_option_inspector_lines (state, category_desc, row_one_based_index)
- lib_bejson_newagent_config_tui.py / render_validation_and_probe_lines (state, mode="validate")
- lib_bejson_newagent_config_tui.py / PositionalConfigTUIController.run_interactive_loop ()
- config_manager.py / main (argv_list=None)
