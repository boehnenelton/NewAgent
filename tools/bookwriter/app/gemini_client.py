"""
Library:        gemini_client.py
Project:        Cli_Bookwriter
Description:    Minimal Gemini text-generation caller over the plain REST
                 API (no SDK dependency), with retry/backoff — the same
                 shape as call_gemini_with_retry() in Flask_BookCMS.py, kept
                 consistent across Elton's toolkit.
Version:        1.0.1
Date:           2026-08-12
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  6f7a8b9c-0d1e-4f2a-3b4c-5d6e7f8a9b00
"""

import time

DEFAULT_MODEL = "gemini-3.6-flash"
GEMINI_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiCallError(Exception):
    pass


def generate_text(prompt_text: str, api_key: str, system_instruction: str = None,
                   model: str = DEFAULT_MODEL, temperature: float = 0.7, max_retries: int = 3) -> str:
    """Calls the Gemini REST API with exponential backoff. Raises
    GeminiCallError with a clear, never-silent message on final failure."""
    import requests

    if not api_key:
        raise GeminiCallError("No Gemini API key found. Add one to secure/.env "
                               "(GEMINI_API_KEY=... or GEMINI_KEY_1=...) and try again.")

    request_payload = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {"temperature": temperature},
    }
    if system_instruction:
        request_payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

    request_url = GEMINI_ENDPOINT_TEMPLATE.format(model=model)
    last_call_error = None
    for retry_attempt in range(max_retries):
        try:
            api_response = requests.post(
                request_url, params={"key": api_key}, json=request_payload, timeout=120)
            if api_response.status_code == 200:
                response_json = api_response.json()
                response_candidates = response_json.get("candidates", [])
                if not response_candidates:
                    raise GeminiCallError(f"Gemini returned no candidates: {response_json}")
                response_parts = response_candidates[0].get("content", {}).get("parts", [])
                generated_text = "".join(part.get("text", "") for part in response_parts)
                if not generated_text:
                    raise GeminiCallError(f"Gemini returned an empty response: {response_json}")
                return generated_text
            elif api_response.status_code in (429, 500, 503):
                last_call_error = f"HTTP {api_response.status_code}: {api_response.text[:300]}"
                time.sleep(min(2 ** retry_attempt, 10))
                continue
            else:
                raise GeminiCallError(f"Gemini API error (HTTP {api_response.status_code}): {api_response.text[:500]}")
        except requests.RequestException as request_exception:
            last_call_error = str(request_exception)
            time.sleep(min(2 ** retry_attempt, 10))

    raise GeminiCallError(f"Gemini call failed after {max_retries} attempts: {last_call_error}")
