"""
Name:           test_openrouter_engine_integration.py
Description:    Regression coverage for OpenRouter provider key synchronization,
                model catalog routing, request formation, response parsing, and
                slash command engine protection.
Version:        1.0.0
Date:           2026-10-14
Author:         Elton Boehnen — boehnenelton2024@gmail.com
RELATIONAL_ID:  74bc2901-4d32-4731-9f9b-65e1281db091
"""
import _libpath  # noqa: F401
from pathlib import Path
import pytest

import lib_bejson_newagent_engine_rest as engine_rest
import lib_bejson_newagent_commands as commands
from lib_bejson_Core_bejson_core import bejson_core_create_104a, bejson_core_atomic_write


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


import asyncio


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

