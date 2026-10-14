"""
Name:           test_openrouter_engine_integration.py
Description:    Regression coverage for OpenRouter provider key synchronization,
                model catalog routing, request formation, response parsing, and
                slash command engine protection.
Version:        1.1.0
Date:           2026-10-14
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  69e1e046-ecc5-413c-be10-3c3ef50ed2e5
"""
import _libpath  # noqa: F401
from pathlib import Path
import pytest
import asyncio
from unittest.mock import patch

import lib_bejson_newagent_engine_rest as engine_rest
import lib_bejson_newagent_commands as commands
from lib_bejson_Core_bejson_core import bejson_core_create_104a, bejson_core_atomic_write, bejson_core_load_file, bejson_core_get_field_map


def test_provider_env_key_prefix():
    assert engine_rest.PROVIDER_ENV_KEY_PREFIX.get("openrouter") == "OPENROUTER_KEY_"


def test_openrouter_request_builder():
    key = "sk-or-test-key"
    model = "liquid/lfm-2.5-2.6b:free"
    history = [{"role": "user", "content": "hello"}]
    si = "You are a helpful assistant."
    config = {"gen_temperature": 0.5, "gen_top_p": 0.9}
    catalog_rows = [{"model_string": model, "provider": "openrouter"}]

    url, headers, payload = engine_rest._build_openrouter_request(
        key, model, history, si, config, catalog_rows, "openrouter"
    )

    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert headers["Authorization"] == f"Bearer {key}"
    assert headers["HTTP-Referer"] == "https://github.com/boehnenelton/NewAgent"
    assert headers["X-Title"] == "NewAgent CLI"
    assert payload["model"] == model
    assert len(payload["messages"]) == 2
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"


def test_openrouter_response_parser():
    sample_response = {
        "id": "gen-12345",
        "choices": [
            {
                "message": {"role": "assistant", "content": "Hello! How can I help?"},
                "finish_reason": "stop"
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18}
    }
    text, usage = engine_rest._parse_openrouter_response(sample_response)
    assert text == "Hello! How can I help?"
    assert usage.get("total_tokens") == 18


def test_resolve_provider_logic():
    catalog_rows = [
        {"model_string": "gemini-3.5-flash-lite", "provider": "gemini"},
        {"model_string": "liquid/lfm-2.5-2.6b:free", "provider": "openrouter"},
        {"model_string": "anthropic/claude-sonnet-5.5", "provider": "openrouter"},
    ]
    key_reg = engine_rest.KeyRegistry(Path("config/keys.bejson"), Path("config/key_state.bejson"))
    model_reg = engine_rest.ModelRegistry(Path("config/models.bejson"))
    prompter = engine_rest.RestPrompter(key_reg, model_reg, Path("config/gemini_catalog.bejson"), {})

    assert prompter._resolve_provider(catalog_rows, "gemini-3.5-flash-lite") == "gemini"
    assert prompter._resolve_provider(catalog_rows, "liquid/lfm-2.5-2.6b:free") == "openrouter"
    assert prompter._resolve_provider(catalog_rows, "anthropic/claude-sonnet-5.5") == "openrouter"
    assert prompter._resolve_provider(catalog_rows, "unknown-model") == "gemini"


def test_engine_slash_command_blocks_interactions_for_non_gemini():
    class DummyModelReg:
        active = "liquid/lfm-2.5-2.6b:free"
    
    ctx = {
        "config": {"engine_mode": "rest"},
        "_config_dir": Path("config"),
        "model_reg": DummyModelReg(),
        "_save_config": lambda: None,
        "_init_engine": lambda: None,
    }
    processed, msg = asyncio.run(commands.handle_slash_commands("/engine", ctx))
    assert processed is True
    assert "Cannot switch to Interactions engine" in msg
    assert ctx["config"]["engine_mode"] == "rest"


def test_is_openrouter_free_model():
    # 1. Authoritative zero-cost
    assert engine_rest.is_openrouter_free_model({
        "id": "vendor/zero-cost-model",
        "pricing": {"prompt": "0", "completion": "0"},
        "description": "Zero cost general LLM"
    }) is True

    # 2. Suffix :free or -free
    assert engine_rest.is_openrouter_free_model({"id": "vendor/model:free"}) is True
    assert engine_rest.is_openrouter_free_model({"id": "vendor/model-free"}) is True
    assert engine_rest.is_openrouter_free_model({"id": "openrouter/free"}) is True

    # 3. Paid models
    assert engine_rest.is_openrouter_free_model({
        "id": "anthropic/claude-sonnet-5.5",
        "pricing": {"prompt": "0.000003", "completion": "0.000015"}
    }) is False

    # 4. Excludes per-song / per-image models that have prompt 0
    assert engine_rest.is_openrouter_free_model({
        "id": "google/lyria-3-pro-preview",
        "pricing": {"prompt": "0", "completion": "0"},
        "description": "Full-length songs are priced at $0.08 per song."
    }) is False


def test_sync_openrouter_free_models_to_catalog(tmp_path):
    catalog_path = tmp_path / "catalog.bejson"
    fields = [
        {"name": "model_number", "type": "number"},
        {"name": "model_string", "type": "string"},
        {"name": "display_name", "type": "string"},
        {"name": "tier", "type": "string"},
        {"name": "status", "type": "string"},
        {"name": "notes", "type": "string"},
        {"name": "api_profile", "type": "string"},
        {"name": "provider", "type": "string"},
        {"name": "key_valid_through", "type": "string"},
    ]
    initial_values = [
        [1, "gemini-2.5-flash", "Gemini 2.5 Flash", "flash", "GA", "notes", "legacy", "gemini", ""],
        [10, "anthropic/claude-sonnet-5.5", "Claude Sonnet 5.5", "pro", "GA", "notes", "legacy", "openrouter", ""],
    ]
    doc = bejson_core_create_104a("GeminiModelCatalog", fields, initial_values)
    assert bejson_core_atomic_write(str(catalog_path), doc) is True

    mock_free_models = [
        {"id": "liquid/lfm-2.5-2.6b:free", "name": "LiquidAI: LFM2.5-2.6B (free)", "description": "Free model"},
        {"id": "nvidia/nemotron-3.5:free", "name": "NVIDIA Nemotron (free)", "description": "Free NVIDIA"},
    ]

    with patch.object(engine_rest, "fetch_openrouter_free_models", return_value=mock_free_models):
        success, count, msg = engine_rest.sync_openrouter_free_models_to_catalog(catalog_path)
        assert success is True
        assert count == 2

    # Verify updated catalog file
    updated_doc = bejson_core_load_file(str(catalog_path))
    fmap = bejson_core_get_field_map(updated_doc)
    vals = updated_doc["Values"]
    assert len(vals) == 4
    # Preserved rows
    assert vals[0][fmap["model_string"]] == "gemini-2.5-flash"
    assert vals[0][fmap["model_number"]] == 1
    assert vals[1][fmap["model_string"]] == "anthropic/claude-sonnet-5.5"
    assert vals[1][fmap["model_number"]] == 10
    # Synced free rows start at 11
    assert vals[2][fmap["model_string"]] == "liquid/lfm-2.5-2.6b:free"
    assert vals[2][fmap["model_number"]] == 11
    assert vals[2][fmap["provider"]] == "openrouter"
    assert vals[3][fmap["model_string"]] == "nvidia/nemotron-3.5:free"
    assert vals[3][fmap["model_number"]] == 12


def test_model_sync_slash_command(tmp_path):
    catalog_path = tmp_path / "gemini_catalog.bejson"
    fields = [
        {"name": "model_number", "type": "number"},
        {"name": "model_string", "type": "string"},
        {"name": "display_name", "type": "string"},
        {"name": "tier", "type": "string"},
        {"name": "status", "type": "string"},
        {"name": "notes", "type": "string"},
        {"name": "api_profile", "type": "string"},
        {"name": "provider", "type": "string"},
        {"name": "key_valid_through", "type": "string"},
    ]
    initial_values = [
        [1, "gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "flash-lite", "GA", "notes", "v3", "gemini", ""],
    ]
    doc = bejson_core_create_104a("GeminiModelCatalog", fields, initial_values)
    assert bejson_core_atomic_write(str(catalog_path), doc) is True

    class DummyModelReg:
        active = "gemini-3.5-flash-lite"

    ctx = {
        "config": {"engine_mode": "rest"},
        "_config_dir": tmp_path,
        "model_reg": DummyModelReg(),
        "_save_config": lambda: None,
        "_init_engine": lambda: None,
    }

    mock_free_models = [
        {"id": "liquid/lfm-2.5-2.6b:free", "name": "LiquidAI: LFM2.5-2.6B (free)", "description": "Free model"},
    ]

    with patch.object(engine_rest, "fetch_openrouter_free_models", return_value=mock_free_models):
        processed, msg = asyncio.run(commands.handle_slash_commands("/model sync", ctx))
        assert processed is True
        assert "Synced 1 free OpenRouter models into catalog" in msg
        assert "LiquidAI: LFM2.5-2.6B" in msg

