#!/usr/bin/env python3
"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Module:      web_search_core.py
Description: Core search functionality querying DuckDuckGo HTML.
Version:     1.0.0
Date:        2026-08-13
Author:      Elton Boehnen
Contact:     boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 7c6d5e4f-3a2b-1c0d-9e8f-7a6b5c4d3e2f
"""

import urllib.request
import urllib.parse
from bs4 import BeautifulSoup


def search_duckduckgo(query, max_results=10):
    """
    Search DuckDuckGo HTML interface and return list of result dicts:
    [{'title': ..., 'url': ..., 'snippet': ...}, ...]
    """
    data = urllib.parse.urlencode({'q': query}).encode('utf-8')
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36'
    }
    req = urllib.request.Request('https://html.duckduckgo.com/html/', data=data, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            html = res.read().decode('utf-8', errors='replace')
    except Exception as e:
        raise RuntimeError(f"HTTP request to DuckDuckGo failed: {e}")

    soup = BeautifulSoup(html, 'html.parser')
    results = []
    
    for div in soup.find_all('div', class_='result'):
        title_a = div.find('a', class_='result__a')
        snippet_el = div.find('a', class_='result__snippet')
        if title_a and title_a.get('href'):
            raw_url = title_a['href']
            if '/l/?uddg=' in raw_url:
                parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_url).query)
                clean_url = parsed.get('uddg', [raw_url])[0]
            else:
                clean_url = raw_url
                
            results.append({
                'title': title_a.get_text(strip=True),
                'url': clean_url,
                'snippet': snippet_el.get_text(strip=True) if snippet_el else ''
            })
            if len(results) >= max_results:
                break
                
    return results