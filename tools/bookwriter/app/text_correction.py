"""
Library:        text_correction.py
Project:        AuthorCMS_CLI
Description:    Brand-integrity text correction engine. Direct port of the
                 fixText() logic in App.tsx's useEffect — scans generated
                 content for common AI misexpansions of the "BEJSON"
                 acronym/hallucinated backronyms and normalizes them to
                 "Boehnen Elton JSON" / "Boehnen Elton". Applied to chapter
                 content right after generation, before it's written to disk.
Version:        1.1.0
Date:           2026-08-02
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  3c4d5e6f-7a8b-4c9d-0e1f-2a3b4c5d6e77

Changelog:
  1.1.0 - Variable-naming pass: every variable now signals what it holds and
          which entity/hierarchy it belongs to (System Development Policy
          Sec 6.2 — Heritage-Signaling & Self-Describing Variable Names).
          Public function signature (fix_text) left unchanged since both
          the CLI and Flask app call it directly.
"""

import re

BEJSON_MISEXPANSION_PATTERNS = [
    (re.compile(r"Bounded\s+Entity\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Bounded\s+Entity", re.I), "Boehnen Elton"),
    (re.compile(r"Binary\s+Encoded\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Binary-Encoded\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Binary\s+Entity\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Backend\s+Entity\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Bespoke\s+Entity\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Bespoke\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Basic\s+Extended\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Better\s+Extended\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Basic\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Binary\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Boehnen-Elton\s+JSON", re.I), "Boehnen Elton JSON"),
    (re.compile(r"Boehnen-Elton", re.I), "Boehnen Elton"),
]

GENERIC_B_E_JSON_BACKRONYM_RE = re.compile(r"\b(B[a-zA-Z]+)\s+(E[a-zA-Z]+)\s+JSON\b")
GENERIC_B_E_FORMAT_BACKRONYM_RE = re.compile(r"\b(B[a-zA-Z]+)\s+(E[a-zA-Z]+)\s+Format\b")


def _substitute_unless_already_correct(regex_match, correct_replacement):
    matched_b_word, matched_e_word = regex_match.group(1), regex_match.group(2)
    if matched_b_word.lower() == "boehnen" and matched_e_word.lower() == "elton":
        return regex_match.group(0)
    return correct_replacement


def fix_text(source_text):
    """Returns (corrected_text, changed: bool). None/empty input passes through."""
    if not source_text:
        return source_text, False
    corrected_text = source_text
    text_was_changed = False
    for misexpansion_regex, correct_replacement in BEJSON_MISEXPANSION_PATTERNS:
        if misexpansion_regex.search(corrected_text):
            corrected_text = misexpansion_regex.sub(correct_replacement, corrected_text)
            text_was_changed = True

    json_backronym_corrected_text = GENERIC_B_E_JSON_BACKRONYM_RE.sub(
        lambda regex_match: _substitute_unless_already_correct(regex_match, "Boehnen Elton JSON"), corrected_text)
    if json_backronym_corrected_text != corrected_text:
        corrected_text = json_backronym_corrected_text
        text_was_changed = True

    format_backronym_corrected_text = GENERIC_B_E_FORMAT_BACKRONYM_RE.sub(
        lambda regex_match: _substitute_unless_already_correct(regex_match, "Boehnen Elton Format"), corrected_text)
    if format_backronym_corrected_text != corrected_text:
        corrected_text = format_backronym_corrected_text
        text_was_changed = True

    return corrected_text, text_was_changed
