#!/usr/bin/env python3
"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Script:      Cli_Web_Toolkit.py
Description: Unified CLI web toolkit combining Web Search, Content Extraction,
             and Mobile Interactive Web Browsing (with link navigation and history).
Version:     1.3.0
Date:        2026-08-13
Author:      Elton Boehnen
Contact:     boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 5d4c3b2a-1e0f-9a8b-7c6d-5e4f3a2b1c0d
"""

import sys
import os
import argparse
import json
import re
from datetime import datetime

from env_loader import load_dotenv
from web_search_core import search_duckduckgo
from web_extractor_core import (
    fetch_html,
    extract_text_standard,
    extract_text_ai,
    render_html,
    cleanup_old_files,
    VERSION as CORE_VERSION
)
from browser_core import MobileBrowserSession

load_dotenv()


def _slugify(text):
    safe = re.sub(r'[^a-zA-Z0-9]+', '_', text).strip('_').lower()
    return safe[:50] or "web_output"


def _resolve_api_key(cli_key):
    if cli_key:
        return cli_key
    for env_name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_KEY_1"):
        val = os.environ.get(env_name)
        if val:
            return val
    return None


def handle_search(args, results_dir, pages_dir):
    query_str = " ".join(args.query)
    print(f"[*] Executing search for: '{query_str}'...")

    try:
        results = search_duckduckgo(query_str, max_results=args.num)
    except Exception as e:
        print(f"[!] Search failed: {e}", file=sys.stderr)
        sys.exit(1)

    if args.fetch > 0 and results:
        num_fetch = min(args.fetch, len(results))
        print(f"[*] Fetching and refining content for top {num_fetch} page(s)...")
        for i in range(num_fetch):
            target_url = results[i]['url']
            print(f"    -> [{i+1}/{num_fetch}] Fetching: {target_url}")
            try:
                raw_html = fetch_html(target_url)
                if args.ai:
                    api_key = _resolve_api_key(args.api_key)
                    if api_key:
                        extracted = extract_text_ai(raw_html, target_url, api_key, args.model)
                    else:
                        print("    [!] No API key found for AI, using standard parser.")
                        extracted = extract_text_standard(raw_html)
                else:
                    extracted = extract_text_standard(raw_html)

                timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                timestamp_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                rendered_page = render_html(extracted, target_url, timestamp_iso, query=query_str)
                
                safe_title = _slugify(extracted.get('title', 'page'))[:30]
                page_filename = f"{timestamp_str}_q{i+1}_{safe_title}.html"
                page_path = os.path.join(pages_dir, page_filename)

                with open(page_path, "w", encoding="utf-8") as f:
                    f.write(rendered_page)

                results[i]['saved_page'] = page_path
                results[i]['extracted_title'] = extracted.get('title')
                print(f"       [+] Page saved: {page_path}")
            except Exception as e:
                results[i]['fetch_error'] = str(e)
                print(f"       [!] Fetch error: {e}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug_q = _slugify(query_str)
    out_filename = args.out if args.out else f"search_{slug_q}_{timestamp}.json"
    out_path = os.path.join(results_dir, out_filename)

    output_data = {
        "query": query_str,
        "timestamp": datetime.now().isoformat(),
        "total_results": len(results),
        "results": results
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\n[+] Search completed.")
    print(f"    Index saved: {out_path}")

    if args.json:
        print(json.dumps(output_data, indent=2, ensure_ascii=False))
    else:
        print(f"\n=== Search Results: '{query_str}' ===\n")
        for idx, r in enumerate(results, 1):
            print(f"{idx}. {r['title']}")
            print(f"   URL: {r['url']}")
            print(f"   Snippet: {r['snippet']}")
            if 'saved_page' in r:
                print(f"   Saved HTML Page: {r['saved_page']}")
            print()


def handle_extract(args, results_dir, pages_dir):
    url = args.url
    print(f"[*] Extracting page: {url}")
    try:
        raw_html = fetch_html(url)
    except Exception as e:
        print(f"[!] Fetch failed: {e}", file=sys.stderr)
        sys.exit(1)

    if args.ai:
        api_key = _resolve_api_key(args.api_key)
        if not api_key:
            print("[!] AI requested but no API key found. Falling back to standard extraction.")
            extracted = extract_text_standard(raw_html)
        else:
            print(f"[*] Extracting using Gemini AI ({args.model})...")
            try:
                extracted = extract_text_ai(raw_html, url, api_key, args.model)
            except Exception as e:
                print(f"[!] AI extraction failed ({e}), falling back to standard extraction.")
                extracted = extract_text_standard(raw_html)
    else:
        extracted = extract_text_standard(raw_html)

    if args.title:
        extracted['title'] = args.title

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    timestamp_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rendered_html = render_html(extracted, url, timestamp_iso)

    out_filename = args.out if args.out else f"{timestamp_str}_{_slugify(extracted.get('title', 'extracted'))}.html"
    if os.path.isabs(out_filename) or "/" in out_filename:
        out_path = out_filename
    else:
        out_path = os.path.join(pages_dir, out_filename)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(rendered_html)

    print(f"\n[+] Extraction Successful!")
    print(f"    Title:     {extracted.get('title')}")
    print(f"    Method:    {extracted.get('method', 'Standard')}")
    print(f"    HTML File: {out_path}")


def handle_browse(args):
    session = MobileBrowserSession()

    if args.url:
        page = session.navigate_to(args.url)
    elif args.link:
        page = session.follow_link(args.link)
    elif args.back:
        page = session.back()
    elif args.forward:
        page = session.forward()
    else:
        page = session.current_page

    if not page:
        print("[!] No page active in browser session. Provide a URL using: toolkit browse <url>")
        return

    print("\n" + "="*60)
    print(f" TITLE: {page.get('title')}")
    print(f" URL:   {page.get('url')}")
    print("="*60 + "\n")

    if args.links_only:
        print("=== Navigable Links on Current Page ===")
        for l in page.get('links', []):
            print(f" [{l['id']}] {l['text']}\n     -> {l['url']}")
    else:
        print(page.get('text', 'No text content available.'))
        print("\n" + "-"*60)
        print(f"Available Links: {len(page.get('links', []))} (Use --links-only to list all links, or --link <N> to follow a link)")
        print("-"*60)


def main():
    parser = argparse.ArgumentParser(
        prog="Cli_Web_Toolkit.py",
        description="Unified NewAgent Web Toolkit for Web Search, Content Extraction, and Mobile Web Browsing."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Subcommand: search
    search_parser = subparsers.add_parser("search", help="Search the web and optionally fetch/refine result pages")
    search_parser.add_argument("query", nargs="+", help="Search query terms")
    search_parser.add_argument("-n", "--num", type=int, default=5, help="Number of search results to return (default: 5)")
    search_parser.add_argument("--fetch", type=int, default=0, help="Fetch, refine, and save top N result pages (default: 0)")
    search_parser.add_argument("--ai", action="store_true", help="Use AI (Gemini) extraction for fetched pages")
    search_parser.add_argument("--model", default="gemini-3-flash-preview", help="Gemini model for AI pass")
    search_parser.add_argument("--api-key", default=None, help="Gemini API Key")
    search_parser.add_argument("--json", action="store_true", help="Print result JSON to stdout")
    search_parser.add_argument("-o", "--out", default=None, help="Output JSON filename in results/")

    # Subcommand: extract
    extract_parser = subparsers.add_parser("extract", help="Extract and refine a single web page URL")
    extract_parser.add_argument("url", help="Target URL to extract content from")
    extract_parser.add_argument("-o", "--out", default=None, help="Output HTML file path (default inside results/pages/)")
    extract_parser.add_argument("-t", "--title", default=None, help="Override extracted page title")
    extract_parser.add_argument("--ai", action="store_true", help="Use AI (Gemini) extraction pass")
    extract_parser.add_argument("--model", default="gemini-3-flash-preview", help="Gemini model for AI pass")
    extract_parser.add_argument("--api-key", default=None, help="Gemini API Key")

    # Subcommand: browse
    browse_parser = subparsers.add_parser("browse", help="Mobile terminal web browser session with link navigation and history")
    browse_parser.add_argument("url", nargs="?", default=None, help="URL to navigate to")
    browse_parser.add_argument("-l", "--link", type=int, default=None, help="Follow link number N on current page")
    browse_parser.add_argument("-b", "--back", action="store_true", help="Go back in session history")
    browse_parser.add_argument("-f", "--forward", action="store_true", help="Go forward in session history")
    browse_parser.add_argument("--links-only", action="store_true", help="List all navigable links on current page")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Base output directories
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    results_dir = os.path.join(tool_dir, "results")
    pages_dir = os.path.join(results_dir, "pages")

    os.makedirs(results_dir, exist_ok=True)
    os.makedirs(pages_dir, exist_ok=True)

    # Auto-cleanup >24 hour files
    cleaned_pages = cleanup_old_files(pages_dir, max_age_seconds=86400)
    cleaned_results = cleanup_old_files(results_dir, max_age_seconds=86400)
    if cleaned_pages or cleaned_results:
        print(f"[*] Cleanup auto-removed {cleaned_results} old result index(es) and {cleaned_pages} old page(s) (>24h old).")

    if args.command == "search":
        handle_search(args, results_dir, pages_dir)
    elif args.command == "extract":
        handle_extract(args, results_dir, pages_dir)
    elif args.command == "browse":
        handle_browse(args)


if __name__ == "__main__":
    main()