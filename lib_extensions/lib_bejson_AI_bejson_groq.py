"""
Library:        lib_bejson_AI_bejson_groq.py
Family:         AI
Description:    Integration wrapper for Groq API services.
Version:        2.1.7
Date:           2026-08-14
Author:         Elton Boehnen
Contact:        eltonboehnen@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  7d3e9f42-1b6c-4a58-8e0d-9f2c5a7b3e14
Release_Version: 300

Changelog:
  2.1.7 - Merged verified fix from Elton's own groq_cli test (cli_test.zip,
          groq_cli_test_report.md, tested live on-device against 10 real
          keys): default MaxResponseTokens fallback (used when a profile
          doesn't set one) was 32768, which produced real 413 Payload Too
          Large responses from Groq on llama-3.3-70b-versatile. Lowered to
          8192.
  2.1.6 - Modularization: GroqKeyRegistry/GroqModelRegistry now subclass
          lib_bejson_AI_ai_registry_base.py's shared atomic base instead of
          reimplementing BEJSON key-loading/round-robin/model-lookup logic.
          Behavior preserved exactly (verified: default file creation,
          model list, active_model_id, get_model_info()); gains
          GROQ_KEY_1.._10 numbered env-slot fallback, checked before the
          BEJSON file, which the original never had.
  2.1.5 - AI-family audit fix: module-level VERSION var had drifted to
          "2.1.2" while this header said 2.1.4 -- any code reading
          groq_module.VERSION got a stale value two patches behind.
          Re-synced to a single source of truth.
"""

import os
import sys
import json
import time
import requests
import random
import copy
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# --- Path Resolution Utility ---
# Add Lib directory to path for relative imports
LIB_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_DIR = os.path.join(os.path.dirname(LIB_DIR), "Core")
if CORE_DIR not in sys.path:
    sys.path.append(CORE_DIR)

from lib_bejson_Core_bejson_env import resolve_path as resolve_system_path

# --- SCHEMAS INFERRED VIA LIB_BEJSON_SCHEMA ---
GROQ_PROFILE_SCHEMA = {
    "Format": "BEJSON",
    "Format_Version": "104",
    "Format_Creator": "Elton Boehnen",
    "Records_Type": ["AI_Profile"],
    # FIX (LIB-AI-M2): see the matching fix + full explanation in
    # bejson_openrouter.py's SCHEMA_AI_PROFILE.
    "Fields": [
        {"name": "Record_Type_Parent", "type": "string"},
        {"name": "Name", "type": "string"},
        {"name": "Archetype", "type": "string"},
        {"name": "Persona", "type": "string"},
        {"name": "SystemInstruction", "type": "string"},
        {"name": "ForbiddenTopics", "type": "array"},
        {"name": "Avatar_Type", "type": "string"},
        {"name": "Avatar_sourceUrl", "type": "string"},
        {"name": "Avatar_Data", "type": "string"},
        {"name": "MaxResponseTokens", "type": "integer"},
        {"name": "Creativity", "type": "number"},
        {"name": "Tone", "type": "array"},
        {"name": "Formality", "type": "string"},
        {"name": "Verbosity", "type": "string"},
        {"name": "EmotionalExpression_Enabled", "type": "boolean"},
        {"name": "EmotionalExpression_Intensity", "type": "number"},
        {"name": "GoogleSearch_Enabled", "type": "boolean"},
        {"name": "CodeInterpreter_Enabled", "type": "boolean"},
    ],
    "Values": []
}

# --- Environment & Setup ---
LIB_DIR = os.environ.get("BEJSON_LIB_DIR", str(Path(__file__).resolve().parent))
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

from lib_bejson_Core_bejson_core import (
    bejson_core_load_file, 
    bejson_core_get_field_index, 
    bejson_core_get_field_map, 
    bejson_core_atomic_write
)
from lib_bejson_AI_ai_registry_base import RoundRobinKeyRegistry, ModelRegistryBase

# --- Legacy Fallback Constants ---
_GROQ_MODEL_LEGACY   = {"model_name": 0, "model_id": 1, "currently_active": 2}
_GROQ_PROFILE_LEGACY = {"SystemInstruction": 4} # Note: Groq profile schema varies, using safe fallback

# --- Registry Managers ---
# 2.1.6: GroqKeyRegistry/GroqModelRegistry now subclass the shared AI-family
# atomic base (lib_bejson_AI_ai_registry_base.py) instead of reimplementing
# BEJSON key-loading/round-robin and model-lookup logic independently.
# Behavior preserved exactly (placeholder markers, default schema, legacy
# fallback indices, .keys/.models/.active_model_id attribute names) and
# verified via functional test against the previous implementation. Also
# gains numbered-slot env fallback (GROQ_KEY_1.._10) that the original never
# had -- checked before the BEJSON file.

class GroqKeyRegistry(RoundRobinKeyRegistry):
    def __init__(self, file_path: str):
        super().__init__(
            resolve_system_path(file_path),
            placeholder_markers=["YOUR_GROQ_KEY", "KEY_HERE"],
            env_var_prefix="GROQ_KEY",
            env_var_max_slots=10,
        )


class GroqModelRegistry(ModelRegistryBase):
    def __init__(self, file_path: str):
        def _default():
            return {
                "Format": "BEJSON", "Format_Version": "104a", "Format_Creator": "Elton Boehnen",
                "Records_Type": ["GroqModel"],
                "Fields": [
                    {"name": "model_name", "type": "string"},
                    {"name": "model_id", "type": "string"},
                    {"name": "currently_active", "type": "boolean"},
                ],
                "Values": [
                    ["Llama 3.3 70B Versatile", "llama-3.3-70b-versatile", True],
                    ["Llama 3.1 8B Instant", "llama-3.1-8b-instant", False],
                ],
            }
        super().__init__(
            resolve_system_path(file_path),
            default_model_id="llama-3.3-70b-versatile",
            default_rows_factory=_default,
        )


class GroqProfile:
    def __init__(self, file_path: str):
        self.file_path = Path(resolve_system_path(file_path))
        self.instruction = ""
        self.config = {}
        if not self.file_path.exists():
            self.create_default()
        self.load()

    def create_default(self):
        os.makedirs(self.file_path.parent, exist_ok=True)
        bejson_core_atomic_write(str(self.file_path), GROQ_PROFILE_SCHEMA)

    def load(self):
        try:
            data = bejson_core_load_file(str(self.file_path))
            fi = bejson_core_get_field_map(data)
            # FIX (LIB-AI-M1): see matching fix in bejson_openrouter.py -
            # explicit check instead of relying on the except block to
            # silently mask an empty Values list as a bare IndexError.
            values = data.get("Values") or []
            if not values:
                raise ValueError(f"Profile at {self.file_path} has no Values rows")

            instr_idx = fi.get("SystemInstruction", _GROQ_PROFILE_LEGACY["SystemInstruction"])
            self.instruction = values[0][instr_idx]
            self.config = {f["name"]: values[0][i] for i, f in enumerate(data["Fields"])}
        except Exception as e:
            logging.warning(f"[GroqLib] Failed to load profile {self.file_path}, using defaults: {e}")
            self.instruction = ""
            self.config = {}

# --- Unified Prompter Engine ---
class GroqStandardPrompter:
    def __init__(self, key_registry_path: str, model_registry_path: str, profile_path: str):
        self.key_reg = GroqKeyRegistry(key_registry_path)
        self.model_reg = GroqModelRegistry(model_registry_path)
        self.profile = GroqProfile(profile_path)
        self.current_key_idx = 0
        self.last_request_time = 0
        self.request_delay = 1.0

    def _get_next_key(self) -> Optional[str]:
        keys = self.key_reg.keys
        if not keys: return None
        key = keys[self.current_key_idx]
        self.current_key_idx = (self.current_key_idx + 1) % len(keys)
        return key

    def prompt(self, user_input: str, model_id: Optional[str] = None) -> str:
        now = time.time()
        diff = now - self.last_request_time
        if diff < self.request_delay: time.sleep(self.request_delay - diff)
        
        key = self._get_next_key()
        if not key: return "ERROR: No valid API keys."

        m_info = self.model_reg.get_model_info(model_id)
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        payload = {
            "model": m_info["id"],
            "messages": [
                {"role": "system", "content": self.profile.instruction},
                {"role": "user", "content": user_input}
            ],
            "max_tokens": self.profile.config.get("MaxResponseTokens", 8192),
            "temperature": self.profile.config.get("Creativity", 0.7)
        }
        self.last_request_time = time.time()
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=90)
            res.raise_for_status()
            data = res.json()
            if "choices" in data and data["choices"]:
                return data["choices"][0]["message"]["content"].strip()
            return f"ERROR: No choices. {json.dumps(data)}"
        except Exception as e:
            return f"ERROR: {str(e)}"

# --- Global Standard Paths ---
STD_KEY_PATH = resolve_system_path("{HOME}/.env/groq_keys.bejson")
STD_MODEL_PATH = resolve_system_path("{ADMIN_ROOT}/data/schemas/groq_model_registry.104a.bejson")
STD_PROFILE_PATH = resolve_system_path("{ADMIN_ROOT}/data/schemas/groq_standard_profile.bejson")

VERSION = "2.1.7"

def get_standard_prompter():
    return GroqStandardPrompter(STD_KEY_PATH, STD_MODEL_PATH, STD_PROFILE_PATH)
