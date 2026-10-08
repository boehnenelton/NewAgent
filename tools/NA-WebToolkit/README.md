# NA-WebToolkit Documentation
**Author:** Elton Boehnen ([boehnenelton2024@gmail.com](mailto:boehnenelton2024@gmail.com))  
**Website:** [boehnenelton2024.pages.dev](https://boehnenelton2024.pages.dev)  
**Version:** 1.3.0  

`NA-WebToolkit` is a lightweight, mobile-optimized command-line suite for Android/Termux and desktop Linux environments. It unifies web searching, article extraction & HTML refining, and interactive terminal web browsing with link navigation and session history.

---

## Key Features

1. **Web Search (`search`)**:
   - Queries DuckDuckGo HTML directly (no external API keys required).
   - Returns structured JSON search results and human-readable terminal output.
   - `--fetch N` flag fetches, cleans, and saves full HTML pages of top $N$ search results.

2. **Web Extraction & HTML Refining (`extract`)**:
   - Multi-stage fetch fallback chain: `curl` $\rightarrow$ `cloudscraper` $\rightarrow$ `playwright` $\rightarrow$ `requests`.
   - Cleans clutter using `BeautifulSoup` (strips `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>`, `<aside>`, `<form>`, `<svg>`).
   - Renders clean article text onto a responsive HTML layout template.
   - Optional Gemini AI extraction pass (`--ai`).

3. **Interactive Mobile Browser (`browse`)**:
   - Converts web pages into clean, terminal-formatted readable text blocks.
   - Extracts and numbers all hyperlinks (`[Link Text](N)`).
   - Allows jump navigation between links (`--link N`).
   - Supports browsing stack history (`--back`, `--forward`).

4. **24-Hour File Auto-Cleanup**:
   - Automatically purges cached search index JSON files, extracted HTML pages, and session files older than 24 hours (`86400` seconds) on each run.

---

## File Structure

```text
tools/NA-WebToolkit/
├── Cli_Web_Toolkit.py   # Main CLI entrypoint (search, extract, browse)
├── web_search_core.py   # DuckDuckGo search parser
├── web_extractor_core.py# Fetcher, BeautifulSoup cleanser, template renderer & cleanup
├── browser_core.py      # Terminal mobile browser, link navigator, session history
├── env_loader.py        # .env environment loader
├── test_toolkit.py      # Unit test suite
└── results/             # Auto-cleaned output directory
    ├── pages/           # Refined HTML pages
    └── sessions/        # Interactive browser active session cache
```

---

## Installation & Prerequisites

Ensure Python 3 and required packages are installed in your Termux environment:

```bash
pip install beautifulsoup4 jinja2 requests
```

*(Optional)* For Cloudflare bypass and headless rendering:
```bash
pip install cloudscraper playwright
```

---

## Command Reference

### 1. Web Search (`search`)
Search DuckDuckGo and optionally pull/refine result pages:

```bash
# Basic Search (top 5 results)
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py search "python programming" -n 5

# Search and fetch top 2 result pages into results/pages/
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py search "python news" -n 5 --fetch 2

# Output search result JSON to stdout
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py search "open source AI" --json
```

### 2. Extract & Refine Web Page (`extract`)
Fetch and render a clean HTML copy of any web page:

```bash
# Standard BeautifulSoup extraction
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py extract "https://realpython.com/tutorials/news/"

# AI-powered extraction pass via Gemini API
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py extract "https://example.com/article" --ai --api-key YOUR_GEMINI_KEY
```

### 3. Mobile Web Browsing (`browse`)
Browse the web directly inside your terminal with numbered links:

```bash
# Navigate to a URL
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py browse "https://news.ycombinator.com"

# List all numbered links on the current active page
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py browse --links-only

# Follow link #15 on the current active page
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py browse --link 15

# Go Back in history stack
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py browse --back

# Go Forward in history stack
python3 tools/NA-WebToolkit/Cli_Web_Toolkit.py browse --forward
```

---

## Running Unit Tests

Run the included test suite to verify tool integrity:

```bash
python3 -m unittest discover -s tools/NA-WebToolkit -p "test_*.py"
```

---

## License & Credits

**Author:** Elton Boehnen  
**Contact:** [boehnenelton2024@gmail.com](mailto:boehnenelton2024@gmail.com)  
**Ecosystem:** NewAgent Terminal Suite  
All modifications and original code credit Elton Boehnen.