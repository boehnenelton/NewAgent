#!/usr/bin/env python3
"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Script:      Cli_Web_Extractor.py
Description: Single-purpose web extraction tool for NewAgent's tools folder.
             Mirrors Flask_Web_Extractor-422.py's fetch/extract methods
             100% (web_extractor_core.py), with no encryption and no
             Library system. Pulls a URL, extracts it with the same
             standard/AI methods, renders it onto the same HTML template,
             and writes exactly one HTML file. That's it.

             Corrects the prior pkg state of this tool, which had drifted
             into a "Unified CLI for Web Extraction and Book CMS
             Generation" -- a book-generation subcommand had been merged
             in (book_generator.py / combine_bejson_context.py), and a
             list of 12 live Gemini API keys was hardcoded directly in
             source as a fallback pool. Both are removed: book generation
             is Cli_Bookwriter's job, not this tool's, and hardcoded
             secrets in source violate the ecosystem's own negative
             constraints (never hardcode credentials). This is back to
             being a single tool that does one thing.
Version:     1.0.0
Date:        2026-08-13
Author:      Elton Boehnen
Contact:     boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 7d2e9f4a-3b6c-4d8e-a1f5-2c9b7e4d6a83

Changelog:
  1.0.0 - Rebuilt as a single-purpose tool. Removed the book-generation
          subcommand, the hardcoded API key pool, and the leftover
          Flask_Web_Extractor-422.py / Persist / output_books / library
          context clutter from the tool folder. fetch_html,
          extract_text_standard, extract_text_ai, and the HTML template
          are unchanged 1:1 mirrors of the Flask original.
"""

import sys
import os
import argparse
from datetime import datetime

from env_loader import load_dotenv
from web_extractor_core import (
    fetch_html,
    extract_text_standard,
    extract_text_ai,
    render_html,
    VERSION as CORE_VERSION,
)

VERSION = "1.0.0"

load_dotenv()


def _resolve_api_key(cli_key):
    """No hardcoded keys. Checks --api-key, then the standard env var
    names, in order. Returns None if nothing is found -- the caller
    decides whether that's fatal."""
    if cli_key:
        return cli_key
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY_1"):
        val = os.environ.get(env_name)
        if val:
            return val
    return None


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="Cli_Web_Extractor.py",
        description="Extract a web page's main content to a single template-rendered HTML file."
    )
    parser.add_argument("url", help="Target URL to extract content from")
    parser.add_argument("-o", "--out", default=None,
                         help="Output HTML file path (default: ./<slugified-title>.html)")
    parser.add_argument("-t", "--title", default=None, help="Override the extracted title")
    parser.add_argument("--ai", action="store_true", help="Use AI extraction (Gemini) instead of the standard parser")
    parser.add_argument("--model", default="gemini-3-flash-preview", help="Gemini model for --ai (default: gemini-3-flash-preview)")
    parser.add_argument("--api-key", default=None, help="Gemini API key (else GEMINI_API_KEY / GOOGLE_API_KEY / GEMINI_KEY_1 from env)")
    return parser


def _slugify(text):
    safe = "".join(c if c.isalnum() else "_" for c in text).strip("_")
    return safe or "extracted_page"


def main():
    args = build_arg_parser().parse_args()
    url = args.url

    print(f"[*] Target URL: {url}")
    print("[*] Fetching web page...")
    try:
        html_content = fetch_html(url)
    except Exception as e:
        print(f"[!] Error fetching URL: {e}")
        sys.exit(1)

    if args.ai:
        api_key = _resolve_api_key(args.api_key)
        if not api_key:
            print("[!] --ai requested but no API key found (checked --api-key, GEMINI_API_KEY, GOOGLE_API_KEY, GEMINI_KEY_1). Falling back to standard extraction.")
            result = extract_text_standard(html_content)
        else:
            print(f"[*] Extracting with AI ({args.model})...")
            try:
                result = extract_text_ai(html_content, url, api_key, args.model)
                result['method'] = f"AI-{args.model}"
                if not result.get('content'):
                    raise Exception("AI returned empty content")
            except Exception as e:
                print(f"[!] AI extraction failed ({e}), falling back to standard extraction...")
                result = extract_text_standard(html_content)
    else:
        print("[*] Extracting with standard parser...")
        result = extract_text_standard(html_content)

    if args.title:
        result['title'] = args.title

    timestamp = datetime.now().isoformat()
    html_view = render_html(result, url, timestamp)

    out_path = args.out or f"{_slugify(result.get('title', 'Untitled'))}.html"
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_view)

    print("\n[+] Extraction Successful!")
    print(f"    Title:     {result.get('title')}")
    print(f"    Method:    {result.get('method')}")
    print(f"    HTML File: {out_path}")


if __name__ == "__main__":
    main()
