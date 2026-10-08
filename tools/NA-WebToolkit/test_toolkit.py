#!/usr/bin/env python3
"""
------------------------------------
Name: Elton Boehnen
Email: boehnenelton2024@gmail.com
Github: github.com/boehnenelton
Website: https://boehnenelton2024.pages.dev
------------------------------------
Module:      test_toolkit.py
Description: Comprehensive unit test suite for NA-WebToolkit.
             Tests web searching, page extraction, HTML rendering, cleanup logic,
             and terminal browsing with link navigation/history.
Version:     1.0.0
Date:        2026-08-13
Author:      Elton Boehnen
Contact:     boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
RELATIONAL_ID: 1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d
"""

import os
import sys
import unittest
import tempfile
import time

from web_search_core import search_duckduckgo
from web_extractor_core import (
    extract_text_standard,
    render_html,
    cleanup_old_files
)
from browser_core import MobileBrowserSession


class TestNAWebToolkit(unittest.TestCase):

    def test_search_duckduckgo(self):
        results = search_duckduckgo("python programming", max_results=3)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        first = results[0]
        self.assertIn("title", first)
        self.assertIn("url", first)
        self.assertIn("snippet", first)
        self.assertTrue(first["url"].startswith("http"))

    def test_extract_text_standard(self):
        sample_html = """
        <html>
        <head><title>Test Page Title</title></head>
        <body>
            <nav><a href="#">Menu</a></nav>
            <main>
                <h1>Main Heading</h1>
                <p>This is a test paragraph for NA-WebToolkit extraction testing.</p>
                <a href="https://example.com/link1">Test Link 1</a>
            </main>
            <footer>Footer Info</footer>
        </body>
        </html>
        """
        extracted = extract_text_standard(sample_html)
        self.assertEqual(extracted["title"], "Test Page Title")
        self.assertIn("Main Heading", extracted["content"])
        self.assertIn("This is a test paragraph", extracted["content"])
        self.assertNotIn("Footer Info", extracted["content"])

    def test_render_html(self):
        data = {
            "title": "Render Test Title",
            "content": "<p>Render content test</p>"
        }
        rendered = render_html(data, url="https://example.com", timestamp="2026-08-13 12:00:00")
        self.assertIn("<title>Render Test Title</title>", rendered)
        self.assertIn("https://example.com", rendered)
        self.assertIn("Render content test", rendered)

    def test_cleanup_old_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            old_file = os.path.join(tmpdir, "old_test.txt")
            new_file = os.path.join(tmpdir, "new_test.txt")
            
            with open(old_file, "w") as f:
                f.write("old data")
            with open(new_file, "w") as f:
                f.write("new data")

            # Set mtime of old_file to 48 hours ago
            past_time = time.time() - (48 * 3600)
            os.utime(old_file, (past_time, past_time))

            cleaned_count = cleanup_old_files(tmpdir, max_age_seconds=86400) # 24h
            self.assertEqual(cleaned_count, 1)
            self.assertFalse(os.path.exists(old_file))
            self.assertTrue(os.path.exists(new_file))

    def test_browser_session_navigation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session_file = os.path.join(tmpdir, "session_test.json")
            session = MobileBrowserSession(session_file=session_file)
            
            # Test navigation to a live URL
            page1 = session.navigate_to("https://news.ycombinator.com")
            self.assertIn("url", page1)
            self.assertEqual(session.current_index, 0)
            self.assertGreater(len(page1["links"]), 0)

            # Test following a link
            first_link_id = page1["links"][0]["id"]
            page2 = session.follow_link(first_link_id)
            self.assertIsNotNone(page2)
            self.assertEqual(session.current_index, 1)

            # Test back navigation
            page_back = session.back()
            self.assertEqual(session.current_index, 0)
            self.assertEqual(page_back["url"], "https://news.ycombinator.com")

            # Test forward navigation
            page_fwd = session.forward()
            self.assertEqual(session.current_index, 1)


if __name__ == "__main__":
    unittest.main()