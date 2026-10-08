# Multi-Provider REST Engine: Implementation Plan
### Ollama, OpenRouter, Hugging Face alongside Gemini
**Status:** PLAN ONLY — no code written. For review before implementation.
**Author:** Claude, for Elton Boehnen
**Date:** 2026-08-01
**Grounded in:** `lib_bejson_newagent_engine_rest.py` as it currently exists (RestPrompter, KeyRegistry, ModelRegistry, `gemini_catalog.bejson`, `MODEL_API_PROFILES`)

---

## 1. The core idea in one paragraph

`RestPrompter`'s retry loop — key rotation, cooldown, auto-deactivation on repeated failure, transient-vs-key-specific error handling, the circuit-breaker-feeding logic — is already provider-agnostic. None of it cares that it happens to be talking to Gemini. What's Gemini-specific is narrow: the URL template, the request body shape (`contents`/`parts`), where the auth key goes (URL query param), and where the response text lives (`candidates[0].content.parts[0].text`). The plan is to pull exactly that narrow slice out into swappable **provider adapters**, and leave everything else — the part that's already built, tested, and working — untouched.

This is the same pattern already in the codebase at smaller scale: `MODEL_API_PROFILES`/`get_model_api_profile()` already switches *how the generation config is shaped* (legacy vs v3 Gemini models) based on which model is active. This plan is that same idea, one level up: switch *which provider's wire format entirely* based on which model is active.

---

## 2. What's already true, and helps

- Your own env var list (from the System Development Policy) already includes `OPENROUTER_KEY_1`, `OPENROUTER_KEY_2`, and `HUGGINGFACE_MM_KEY_1`, `HUGGINGFACE_MM_KEY_2`. You've already anticipated this — the credentials exist, nothing here needs to invent a new secrets story.
- `KeyRegistry` is already a clean, generic "pool of strings with rotation/cooldown/auto-deactivation" — it has no Gemini-specific logic in it at all. It can be reused per-provider without modification.
- The retry loop's error handling (429/401/403/transient-500s/network errors) is standard HTTP semantics, not Gemini-specific. It transfers to any provider that speaks HTTP.
- Ollama needs **no API key at all** when run locally (`http://localhost:11434`) — it's the simplest case and a good first target.
- OpenRouter and Hugging Face's Inference API both speak an **OpenAI-compatible** `chat/completions` shape — one adapter can likely serve both with a different base URL and auth header, not two separate adapters.

---

## 3. Architecture

### 3.1 The adapter interface

A provider adapter needs to answer exactly three questions the current Gemini-only code has hardcoded:

```
build_request(key, model, history, system_instruction, config)
    -> (url: str, headers: dict, body: bytes)

parse_response(raw_json: dict)
    -> (text: str, usage: dict)

requires_auth: bool   # False for local Ollama
```

Matching the codebase's existing style (dict-based dispatch, like `MODEL_API_PROFILES`, rather than a class hierarchy), this becomes a `PROVIDER_ADAPTERS` dict:

```python
PROVIDER_ADAPTERS = {
    "gemini":      {"build_request": _build_gemini_request,      "parse_response": _parse_gemini_response,      "requires_auth": True},
    "ollama":      {"build_request": _build_ollama_request,      "parse_response": _parse_ollama_response,      "requires_auth": False},
    "openrouter":  {"build_request": _build_openai_compat_request, "parse_response": _parse_openai_compat_response, "requires_auth": True},
    "huggingface": {"build_request": _build_openai_compat_request, "parse_response": _parse_openai_compat_response, "requires_auth": True},
}
```

Note `openrouter` and `huggingface` sharing the same two functions, parameterized only by base URL — this is the "one adapter, two providers" point from Section 2.

### 3.2 What changes in `RestPrompter`

Today, `_build_request()` (the helper factored out this session) hardcodes the Gemini URL template and payload shape. It becomes:

```python
def _build_request(self, history, system_instruction):
    model = self.model_reg.active
    provider = self._resolve_provider(model)   # NEW — see 3.3
    adapter = PROVIDER_ADAPTERS[provider]
    key = self.key_reg.next_key() if adapter["requires_auth"] else None
    return adapter["build_request"](key, model, history, system_instruction, self.config)
```

The retry loop's HTTP call and error branching (400/429/401/403/transient-500s/network) stays exactly as it is today — it operates on status codes and exceptions, which are the same regardless of provider. Only the *parsing* of a successful response changes, via `adapter["parse_response"](data)` instead of the current hardcoded `candidates[0].content.parts[0].text` reach-in.

### 3.3 Model → provider resolution

The catalog (`gemini_catalog.bejson`) needs one new column: `provider`. Renaming the file to something provider-neutral (e.g. `model_catalog.bejson`) is worth doing at the same time, but not required — `bejson_core_get_field_map()` already resolves by field name, so the filename itself carries no meaning to the code.

```
Fields: model_number, model_string, display_name, tier, status, notes, api_profile, provider
Row:    [9, "llama3.1:8b", "Llama 3.1 8B (local)", "local", "GA", "Ollama, no key needed", "n/a", "ollama"]
Row:    [10, "anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet (via OpenRouter)", "flash", "GA", "...", "n/a", "openrouter"]
```

`_resolve_provider(model_string)` looks up the active model's row and returns its `provider` column, defaulting to `"gemini"` for any row that doesn't have one yet (so every existing catalog entry keeps working unmodified — additive, not breaking).

### 3.4 Key management per provider

`KeyRegistry` doesn't change internally. What changes is that `RestPrompter` needs **one `KeyRegistry` instance per provider that needs auth**, not one global instance:

```python
self.key_registries = {
    "gemini":      self.key_reg,                                    # existing, unchanged
    "openrouter":  KeyRegistry(OPENROUTER_KEYS_PATH, OPENROUTER_STATE_PATH),
    "huggingface": KeyRegistry(HF_KEYS_PATH, HF_STATE_PATH),
    # "ollama" intentionally absent -- requires_auth is False
}
```

Each gets its own `keys.bejson`/`key_state.bejson` pair (e.g. `config/keys_openrouter.bejson`), populated the same way the Gemini one already is — via `sync_keys_from_env_file()`, which already exists and already correctly reads arbitrary env var names. It needs zero changes; it just gets called once per provider at bootstrap with a different key-prefix pattern (`OPENROUTER_KEY_*` instead of `GEMINI_KEY_*`).

### 3.5 Generation config differences

`build_generation_config()` currently returns Gemini's `generationConfig` shape. Each adapter's `build_request()` is responsible for translating your universal config values (`gen_temperature`, `gen_top_p`, etc. — already in `config.json`) into whatever shape that provider expects:

| Your config key | Gemini | OpenAI-compatible (OpenRouter/HF) | Ollama |
|---|---|---|---|
| `gen_temperature` | `generationConfig.temperature` | `temperature` | `options.temperature` |
| `gen_top_p` | `generationConfig.topP` | `top_p` | `options.top_p` |
| max tokens | `generationConfig.maxOutputTokens` | `max_tokens` | `options.num_predict` |

This mapping lives inside each adapter's `build_request()`, not in a shared function — the whole point of the adapter boundary is that this kind of provider-specific detail doesn't leak back into `RestPrompter`.

---

## 4. Phased rollout

```
Phase 1 — Ollama (simplest: local, no auth, no key rotation needed at all)
  - _build_ollama_request() / _parse_ollama_response()
  - _resolve_provider() + provider column on the catalog
  - Manually add 1-2 Ollama model rows to prove the switch works end to end
  - No KeyRegistry changes needed (requires_auth=False path)

Phase 2 — OpenRouter (introduces: real auth, OpenAI-compatible shape,
  per-provider KeyRegistry)
  - _build_openai_compat_request() / _parse_openai_compat_response()
  - Per-provider KeyRegistry wiring (Section 3.4)
  - sync_keys_from_env_file() called for OPENROUTER_KEY_* at bootstrap

Phase 3 — Hugging Face (proves the "one adapter, two providers" claim)
  - Reuse Phase 2's adapter functions with a different base URL + auth header
  - If HF's actual response shape turns out to differ enough from OpenRouter's
    to need its own parser, that's a real finding to correct this plan on,
    not a reason to force a shared adapter that doesn't fit

Phase 4 — /model and webagent's model dropdown become provider-aware
  - Display as "model_name [provider]" so cross-provider selection is
    unambiguous, matching Section 3.3's catalog data
  - ModelRegistry.set_active() unchanged (it only ever stored a string);
    provider is *resolved* from the catalog at call time, not stored twice
```

Each phase is independently shippable and testable — Phase 1 alone proves the adapter boundary is real before any auth complexity gets added.

---

## 5. What does NOT change

- `KeyRegistry`'s auto-deactivation, cooldown, transient-cooldown, and `mark_success` logic — provider-agnostic already, reused as-is per provider instance.
- The retry loop's status-code branching (400/429/401/403/500s/network) — standard HTTP, not Gemini-specific.
- `ModelRegistry` — still just tracks one active model string.
- The circuit breaker, `/status`, `/keys`, `/debug` — all operate one level above this and don't need to know a second provider exists.

---

## 6. Open questions for you

1. **Ollama's base URL** — always `localhost:11434`, or does this need to be configurable (e.g. Ollama running on a different device on your network)? If configurable, that's one more `config.json` key (`ollama_base_url`), not a structural change.
2. **Per-provider `max_retries`/timeout** — a local Ollama call and a network call to OpenRouter have very different realistic timeout expectations. Worth a per-provider override, or is the existing global `max_retries`/`timeout` fine to start?
3. **Catalog file split or single file?** — Section 3.3 proposed one `provider` column on the existing catalog. An alternative is one catalog file per provider (`gemini_catalog.bejson`, `ollama_catalog.bejson`, ...). The single-file-with-a-column approach was chosen here because it keeps `/model`'s cross-provider list a single read instead of a merge — flag if you'd rather split them.
4. **Does Hugging Face here mean the hosted Inference API, or a self-hosted Inference Endpoint?** The plan assumes hosted (fixed base URL); a self-hosted endpoint would need a per-model URL, which is a small but real addition to the catalog schema (an `endpoint_url` column, used only when present).
