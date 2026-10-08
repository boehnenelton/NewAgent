#!/usr/bin/env python3
"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Module:      browser_core.py
Description: Interactive mobile terminal browser & link navigator for NA-WebToolkit.
             Converts HTML into mobile-optimized formatted text, tracks browsing session
             history, resolves relative URLs, extracts numbered links for easy navigation,
             and supports text searching and auto-cleanup.
Version:     1.0.0
Date:        2026-08-13
Author:      Elton Boehnen
Contact:     boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 9f8e7d6c-5b4a-3f2e-1d0c-9b8a7f6e5d4c
"""

import os
import sys
import json
import urllib.parse
from datetime import datetime
from bs4 import BeautifulSoup

from web_extractor_core import fetch_html, cleanup_old_files


class MobileBrowserSession:
    def __init__(self, session_file=None):
        tool_dir = os.path.dirname(os.path.abspath(__file__))
        self.results_dir = os.path.join(tool_dir, "results")
        self.session_dir = os.path.join(self.results_dir, "sessions")
        os.makedirs(self.session_dir, exist_ok=True)
        
        # Enforce 24h retention on session files
        cleanup_old_files(self.session_dir, max_age_seconds=86400)

        self.session_file = session_file or os.path.join(self.session_dir, "active_session.json")
        self.history = [] # Stack of URLs
        self.current_index = -1
        self.current_page = None
        self.links = [] # List of {'id': 1, 'text': '...', 'url': '...'}
        
        self.load_session()

    def load_session(self):
        if os.path.exists(self.session_file):
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.history = data.get("history", [])
                    self.current_index = data.get("current_index", -1)
                    self.current_page = data.get("current_page", None)
                    self.links = data.get("links", [])
            except Exception as e:
                print(f"[!] Warning: Failed to load session ({e}), starting fresh session.")

    def save_session(self):
        data = {
            "history": self.history,
            "current_index": self.current_index,
            "current_page": self.current_page,
            "links": self.links,
            "last_updated": datetime.now().isoformat()
        }
        with open(self.session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def navigate_to(self, url):
        """Fetches URL, parses formatted readable text and numbered links."""
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url

        print(f"[*] Navigating to: {url} ...")
        raw_html = fetch_html(url)
        parsed_page = self._parse_html(raw_html, url)

        # Update history
        if self.current_index < len(self.history) - 1:
            self.history = self.history[:self.current_index + 1]
        
        self.history.append(url)
        self.current_index = len(self.history) - 1
        self.current_page = parsed_page
        self.links = parsed_page['links']

        self.save_session()
        return parsed_page

    def _fetch_and_load(self, url):
        url = url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url

        print(f"[*] Navigating to: {url} ...")
        raw_html = fetch_html(url)
        parsed_page = self._parse_html(raw_html, url)
        self.current_page = parsed_page
        self.links = parsed_page['links']
        self.save_session()
        return parsed_page

    def back(self):
        if self.current_index > 0:
            self.current_index -= 1
            prev_url = self.history[self.current_index]
            return self._fetch_and_load(prev_url)
        else:
            print("[!] Already at the beginning of browsing history.")
            return self.current_page

    def forward(self):
        if self.current_index < len(self.history) - 1:
            self.current_index += 1
            next_url = self.history[self.current_index]
            return self._fetch_and_load(next_url)
        else:
            print("[!] Already at the end of browsing history.")
            return self.current_page

    def follow_link(self, link_num):
        for l in self.links:
            if l['id'] == link_num:
                return self.navigate_to(l['url'])
        print(f"[!] Link #{link_num} not found on current page.")
        return None

    def _parse_html(self, raw_html, base_url):
        soup = BeautifulSoup(raw_html, 'html.parser')
        
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "svg", "iframe", "noscript"]):
            tag.decompose()

        title = "Untitled Page"
        if soup.title and soup.title.get_text().strip():
            title = soup.title.get_text().strip()
        elif soup.find('h1'):
            title = soup.find('h1').get_text().strip()

        main = (soup.find('main') or soup.find('article') or
                soup.find('div', class_=lambda c: c and any(x in c.lower() for x in ['content', 'post', 'entry', 'main'])) or
                soup.find('body'))

        links = []
        link_counter = 1

        # Extract links within content body
        if main:
            for a in main.find_all('a', href=True):
                link_text = a.get_text(strip=True)
                href = a['href'].strip()
                if not link_text or href.startswith('#') or href.startswith('javascript:'):
                    continue
                
                full_url = urllib.parse.urljoin(base_url, href)
                links.append({
                    'id': link_counter,
                    'text': link_text[:60],
                    'url': full_url
                })
                # Replace link in DOM with numbered marker for easy terminal viewing
                a.replace_with(f" [{link_text}]({link_counter}) ")
                link_counter += 1

        # Extract readable formatted text for mobile display
        if main:
            text_blocks = []
            for elem in main.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'ul', 'ol', 'pre', 'blockquote']):
                block_text = elem.get_text(strip=True)
                if not block_text:
                    continue
                if elem.name.startswith('h'):
                    text_blocks.append(f"\n--- {block_text.upper()} ---")
                elif elem.name == 'pre':
                    text_blocks.append(f"\n[CODE BLOCK]\n{block_text}\n[/CODE BLOCK]")
                elif elem.name in ('ul', 'ol'):
                    items = [f" • {li.get_text(strip=True)}" for li in elem.find_all('li') if li.get_text(strip=True)]
                    if items:
                        text_blocks.append("\n" + "\n".join(items))
                else:
                    text_blocks.append(block_text)
            formatted_text = "\n\n".join(text_blocks)
        else:
            formatted_text = "No readable main content body found."

        return {
            'title': title,
            'url': base_url,
            'text': formatted_text,
            'links': links
        }