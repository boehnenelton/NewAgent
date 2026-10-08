"""
Library:        lib_bejson_AI_bejson_huggingface.py
Family:         AI
Description:    HuggingFace inference wrapper. Uses HF's OpenAI-compatible
                 router endpoint via lib_bejson_AI_ai_openai_compatible_base.py
                 rather than the older per-model
                 api-inference.huggingface.co/models/{id} REST shape --
                 same reasoning as Groq/OpenRouter/Provocative: one
                 request/response contract, thin config on top.

                 UNVERIFIED, flagged not guessed past: the exact base URL
                 (https://router.huggingface.co/v1) and default model id
                 below are HF's documented OpenAI-compatible router as of
                 this file's creation, but neither has been test-called
                 from this environment (no network egress to
                 huggingface.co here). Built to be run and checked by
                 Elton, not assumed correct -- see
                 cli_ai_provider_test.py.
Version:        1.0.0
Date:           2026-08-13
Author:         Elton Boehnen
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  aee9149e-5e05-4d8d-82f2-fb9ddaf0ae72
Release_Version: 300

Changelog:
  1.0.0 (2026-08-13) -- Initial creation.
"""

import os
import sys
from pathlib import Path
from typing import Optional

LIB_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(os.path.dirname(LIB_DIR), "Core")
if CORE_DIR not in sys.path:
    sys.path.append(CORE_DIR)

from lib_bejson_Core_bejson_env import resolve_path as resolve_system_path
from lib_bejson_AI_ai_registry_base import RoundRobinKeyRegistry
from lib_bejson_AI_ai_openai_compatible_base import OpenAICompatibleClient

VERSION = "1.0.0"

BASE_URL = "https://router.huggingface.co/v1"
DEFAULT_MODEL = "meta-llama/Llama-3.1-8B-Instruct:novita"  # UNVERIFIED -- check /verify

STD_KEY_PATH = resolve_system_path("{ADMIN_ROOT}/data/schemas/huggingface_keys.bejson")


class HuggingFaceKeyRegistry(RoundRobinKeyRegistry):
    def __init__(self, file_path: str = STD_KEY_PATH):
        super().__init__(
            file_path,
            placeholder_markers=["YOUR_HUGGINGFACE_KEY", "KEY_HERE"],
            env_var_prefix="HUGGINGFACE_MM_KEY",  # matches the roster naming exactly
            env_var_max_slots=5,
        )


_client = OpenAICompatibleClient("huggingface", BASE_URL, DEFAULT_MODEL)
_std_key_registry: Optional[HuggingFaceKeyRegistry] = None


def get_standard_key_registry() -> HuggingFaceKeyRegistry:
    global _std_key_registry
    if _std_key_registry is None:
        _std_key_registry = HuggingFaceKeyRegistry()
    return _std_key_registry


def prompt(
    user_input: str,
    model_id: Optional[str] = None,
    *,
    system_instruction: Optional[str] = None,
    **config,
) -> str:
    reg = get_standard_key_registry()
    key = reg.get_next_key()
    return _client.chat(user_input, key, model=model_id, system_instruction=system_instruction, **config)
