"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Module:      web_extractor_core.py
Description: Core fetch/extract/render logic for Cli_Web_Extractor. This is a
             100% mirror of the fetch chain, extraction methods, and HTML
             template from Flask_Web_Extractor-422.py (fetch_html,
             _is_challenge, extract_text_standard, extract_text_ai,
             HTML_VIEW_TEMPLATE) -- byte-identical logic, ported out of the
             Flask app. Everything about encryption (Fernet/PBKDF2) and the
             Library system (Persist/config.json, storage-path switching,
             import/export, path browser, library markers) has been removed
             on purpose: this tool does one thing -- pull a page, run it
             through the same extraction methods, render it onto the same
             template, and produce a single HTML file. That's it.
Version:     1.0.0
Date:        2026-08-13
Credit:      Elton Boehnen (boehnenelton2024@gmail.com)
RELATIONAL_ID: 4c1a7e2b-9f3d-4a6e-8b21-0d5f6c8a9e10
"""

import re
import json
import requests
from jinja2 import Template

# --- BOT-BYPASS (optional, same 3-stage chain as the Flask original) ---
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

from bs4 import BeautifulSoup

VERSION = "1.0.0"

BROWSER_HEADERS = {
    'User-Agent':      'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36',
    'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Connection':      'keep-alive',
}

# Mirrored verbatim from Flask_Web_Extractor-422.py's HTML_VIEW_TEMPLATE.
HTML_VIEW_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }}</title>
<style>
body{font-family:'Roboto',sans-serif;line-height:1.6;padding:2rem;max-width:800px;margin:0 auto;background:#fff;color:#000}
h1{border-bottom:3px solid #DE2626;padding-bottom:.5rem;color:#DE2626}
.meta{color:#666;font-size:.9rem;margin-bottom:2rem;border-bottom:1px solid #eee;padding-bottom:10px}
img{max-width:100%;height:auto}pre{background:#f4f4f4;padding:1rem;overflow-x:auto}
blockquote{border-left:4px solid #DE2626;padding-left:1rem;color:#555}a{color:#DE2626}p{margin-bottom:15px}
</style></head><body>
<h1>{{ title }}</h1>
<div class="meta"><strong>Source:</strong> <a href="{{ url }}">{{ url }}</a><br><strong>Date:</strong> {{ timestamp }}</div>
<div class="content">{{ content|safe }}</div>
</body></html>"""


# =============================================================================
# FETCH (100% mirror of Flask_Web_Extractor-422.py: cloudscraper -> playwright
# -> requests, same JS-challenge detection, same order, same timeouts)
# =============================================================================

def _is_challenge(text):
    markers = ['enable javascript and cookies', 'cf-browser-verification',
               'checking your browser', 'ddos protection by cloudflare', 'cf_chl_opt', '__cf_chl']
    t = text.lower()
    return any(m in t for m in markers)


def fetch_html(url):
    if CLOUDSCRAPER_AVAILABLE:
        try:
            print("FETCH [1/3] cloudscraper")
            s = cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'android', 'mobile': True})
            r = s.get(url, timeout=20)
            if r.status_code == 200 and not _is_challenge(r.text):
                print("FETCH [1/3] SUCCESS")
                return r.text
        except Exception as e:
            print(f"FETCH [1/3] ERROR: {e}")

    if PLAYWRIGHT_AVAILABLE:
        try:
            print("FETCH [2/3] playwright")
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_context(user_agent=BROWSER_HEADERS['User-Agent'], locale='en-US').new_page()
                page.goto(url, wait_until='networkidle', timeout=30000)
                html_text = page.content()
                browser.close()
            if not _is_challenge(html_text):
                print("FETCH [2/3] SUCCESS")
                return html_text
        except Exception as e:
            print(f"FETCH [2/3] ERROR: {e}")

    print("FETCH [3/3] requests")
    r = requests.get(url, headers=BROWSER_HEADERS, timeout=15)
    if r.status_code == 200 and not _is_challenge(r.text):
        print("FETCH [3/3] SUCCESS")
        return r.text
    if _is_challenge(r.text):
        raise Exception("All fetch methods blocked by JS challenge. Install cloudscraper or playwright.")
    r.raise_for_status()
    return r.text


# =============================================================================
# EXTRACTION (100% mirror of Flask_Web_Extractor-422.py's two extraction
# methods -- standard BeautifulSoup heuristic, and optional Gemini AI pass)
# =============================================================================

def extract_text_standard(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "svg"]):
        tag.decompose()
    main = (soup.find('main') or soup.find('article') or
            soup.find('div', class_=re.compile(r'content|post|entry|article')) or
            soup.find('body'))
    title = soup.title.get_text().strip() if soup.title else "Untitled"
    h1 = soup.find('h1')
    if h1:
        title = h1.get_text().strip()
    content_html = ""
    if main:
        for tag in main.find_all(['p', 'h2', 'h3', 'ul', 'ol', 'blockquote', 'pre', 'div']):
            text = tag.get_text().strip()
            if tag.name == 'div':
                if len(text) < 50 or tag.find(['p', 'h2']):
                    continue
            if len(text) > 10:
                content_html += f"<p>{text}</p>" if tag.name == 'div' else str(tag)
    if len(content_html) < 50 and main:
        lines = [l.strip() for l in main.get_text(separator='\n\n').split('\n') if len(l.strip()) > 30]
        content_html = "".join(f"<p>{l}</p>" for l in lines)
    return {"title": title, "content": content_html, "method": "Standard",
            "word_count": len(content_html.split())}


def extract_text_ai(html_content, url, api_key, model):
    if not api_key:
        raise Exception("No API Key provided")
    print(f"AI extract: {model}")
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
        raise Exception(f"AI error {resp.status_code}: {resp.text}")
    text = resp.json()['candidates'][0]['content']['parts'][0]['text']
    text = re.sub(r"```(json)?", "", text).strip()
    return json.loads(text)


# =============================================================================
# RENDER (mirrors the Flask original's render_template_string call onto
# HTML_VIEW_TEMPLATE -- same template, just rendered via jinja2.Template
# directly instead of inside a Flask request context)
# =============================================================================

def render_html(data, url, timestamp):
    content_str = data.get('content', '') or "<p><em>No content could be extracted.</em></p>"
    template = Template(HTML_VIEW_TEMPLATE)
    return template.render(
        title=data.get('title', 'Untitled'),
        url=url,
        timestamp=timestamp,
        content=content_str,
    )
