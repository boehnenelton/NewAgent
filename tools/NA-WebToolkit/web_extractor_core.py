#!/usr/bin/env python3
"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Module:      web_extractor_core.py
Description: Core fetch, extract, and rendering logic for NA-WebToolkit.
             Supports curl, requests, cloudscraper, and playwright.
Version:     1.1.0
Date:        2026-08-13
Author:      Elton Boehnen
Contact:     boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 6b5a4c3d-2e1f-0a9b-8c7d-6e5f4a3b2c1d
"""

import os
import sys
import time
import re
import json
import subprocess
import requests
from bs4 import BeautifulSoup
from jinja2 import Template

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

VERSION = "1.1.0"

BROWSER_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
    'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection':      'keep-alive',
}

HTML_VIEW_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ title }}</title>
<style>
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; max-width: 800px; margin: 0 auto; padding: 2rem; background: #fafafa; color: #222; }
h1 { border-bottom: 2px solid #DE2626; padding-bottom: 0.5rem; color: #DE2626; font-size: 1.8rem; }
.meta { font-size: 0.85rem; color: #666; background: #eee; padding: 0.75rem 1rem; border-radius: 4px; margin-bottom: 1.5rem; }
.meta a { color: #DE2626; text-decoration: none; word-break: break-all; }
.meta a:hover { text-decoration: underline; }
.content { background: #fff; padding: 1.5rem; border-radius: 6px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
.content p { margin-bottom: 1rem; }
.content h2, .content h3 { color: #333; margin-top: 1.5rem; margin-bottom: 0.5rem; }
.content pre { background: #f4f4f4; padding: 1rem; overflow-x: auto; border-radius: 4px; }
.content blockquote { border-left: 4px solid #DE2626; margin: 0; padding-left: 1rem; color: #555; }
.content img { max-width: 100%; height: auto; border-radius: 4px; }
.content a { color: #DE2626; }
</style>
</head>
<body>
<h1>{{ title }}</h1>
<div class="meta">
    {% if query %}<strong>Query:</strong> {{ query }}<br>{% endif %}
    <strong>Source URL:</strong> <a href="{{ url }}" target="_blank" rel="noopener">{{ url }}</a><br>
    <strong>Fetched At:</strong> {{ timestamp }}
</div>
<div class="content">
    {{ content|safe }}
</div>
</body>
</html>"""


def _is_challenge(text):
    markers = ['enable javascript and cookies', 'cf-browser-verification',
               'checking your browser', 'ddos protection by cloudflare', 'cf_chl_opt', '__cf_chl']
    t = text.lower()
    return any(m in t for m in markers)


def fetch_html(url, timeout=15):
    """Multi-stage fetcher: curl -> cloudscraper -> playwright -> requests.

    FIX (2026-08-31, audit F-36): each stage used to fall through to the
    next immediately on any failure -- no delay at all between attempts
    against the SAME target URL. A site that returns a real response but
    with a challenge page (cloudscraper succeeds at the HTTP level, gets
    a 200, but the body is a Cloudflare check) fell through to Playwright
    immediately, which failed to Playwright immediately, which fell
    through to plain requests immediately -- up to 4 rapid-fire requests
    to the same target within milliseconds of each other. That's exactly
    the burst pattern that gets an IP more aggressively blocked, not
    less. A short, escalating delay before each fallback stage actually
    attempted (not stages skipped outright because their library isn't
    installed) spaces the requests out without adding much total latency
    for the common case where the first stage just works.
    """
    _RETRY_DELAY_SECONDS = 1.5
    # 1. Try curl binary
    try:
        cmd = [
            "curl", "-sL",
            "-A", BROWSER_HEADERS['User-Agent'],
            "--max-time", str(timeout),
            url
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout+5)
        if res.returncode == 0 and res.stdout.strip() and not _is_challenge(res.stdout):
            return res.stdout
    except Exception:
        pass

    # 2. Try cloudscraper if installed
    if CLOUDSCRAPER_AVAILABLE:
        time.sleep(_RETRY_DELAY_SECONDS)
        try:
            s = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'mobile': True})
            r = s.get(url, timeout=timeout)
            if r.status_code == 200 and not _is_challenge(r.text):
                return r.text
        except Exception:
            pass

    # 3. Try Playwright if installed
    if PLAYWRIGHT_AVAILABLE:
        time.sleep(_RETRY_DELAY_SECONDS * 2)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_context(user_agent=BROWSER_HEADERS['User-Agent'], locale='en-US').new_page()
                page.goto(url, wait_until='networkidle', timeout=timeout*1000)
                html_text = page.content()
                browser.close()
            if not _is_challenge(html_text):
                return html_text
        except Exception:
            pass

    # 4. Fallback to requests
    time.sleep(_RETRY_DELAY_SECONDS * 2)
    r = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    if r.status_code == 200 and not _is_challenge(r.text):
        return r.text
    if _is_challenge(r.text):
        raise RuntimeError("Website blocked by JS challenge/Cloudflare.")
    r.raise_for_status()
    return r.text


def extract_text_standard(html_content):
    """Standard BeautifulSoup content extraction & cleaning."""
    soup = BeautifulSoup(html_content, 'html.parser')
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "svg", "iframe", "noscript"]):
        tag.decompose()

    title = "Untitled Page"
    if soup.title and soup.title.get_text().strip():
        title = soup.title.get_text().strip()
    elif soup.find('h1'):
        title = soup.find('h1').get_text().strip()

    main = (soup.find('main') or soup.find('article') or
            soup.find('div', class_=re.compile(r'content|post|entry|article', re.I)) or
            soup.find('body'))

    content_parts = []
    if main:
        for tag in main.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'ul', 'ol', 'blockquote', 'pre']):
            text = tag.get_text(strip=True)
            if len(text) > 5:
                content_parts.append(str(tag))

    if not content_parts and main:
        lines = [l.strip() for l in main.get_text(separator='\n').split('\n') if len(l.strip()) > 30]
        content_parts = [f"<p>{l}</p>" for l in lines]

    clean_content = "\n".join(content_parts) if content_parts else "<p><em>No content body could be extracted.</em></p>"

    return {
        "title": title,
        "content": clean_content,
        "method": "Standard",
        "word_count": len(clean_content.split())
    }


def extract_text_ai(html_content, url, api_key, model="gemini-3-flash-preview"):
    """Gemini AI extraction pass."""
    if not api_key:
        raise ValueError("No Gemini API key provided for AI extraction.")
    prompt = f"""You are a web extractor. Extract the main article content from the HTML.
Return ONLY a JSON object (no markdown, no backticks):
{{
  "title": "Page Title",
  "author": "Author or null",
  "content": "Clean HTML using <p><h2><ul> tags only. No JS or CSS.",
  "tags": ["tag1","tag2"]
}}
URL: {url}
HTML (first 40k chars):
{html_content[:40000]}"""
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"response_mime_type": "application/json"}},
        timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"AI error {resp.status_code}: {resp.text}")
    text = resp.json()['candidates'][0]['content']['parts'][0]['text']
    text = re.sub(r"```(json)?", "", text).strip()
    return json.loads(text)


def render_html(data, url, timestamp, query=None):
    """Render extracted data using template."""
    content_str = data.get('content', '') or "<p><em>No content available.</em></p>"
    tmpl = Template(HTML_VIEW_TEMPLATE)
    return tmpl.render(
        title=data.get('title', 'Untitled'),
        url=url,
        query=query,
        timestamp=timestamp,
        content=content_str,
    )


def cleanup_old_files(target_dir, max_age_seconds=86400):
    """Deletes files in target_dir older than max_age_seconds (24 hours)."""
    if not os.path.exists(target_dir):
        return 0
    now = time.time()
    count = 0
    for filename in os.listdir(target_dir):
        file_path = os.path.join(target_dir, filename)
        if os.path.isfile(file_path):
            file_age = now - os.path.getmtime(file_path)
            if file_age > max_age_seconds:
                try:
                    os.remove(file_path)
                    count += 1
                except Exception as e:
                    print(f"[!] Cleanup error on {filename}: {e}", file=sys.stderr)
    return count