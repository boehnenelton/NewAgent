#!/usr/bin/env python3
# =============================================================================
# Script:       MD_To_HTML.py
# Description:  Converts Markdown files to HTML. Default output is unstyled,
#               semantically correct HTML wrapped in <article> tags.
#               Use --style to enable the full built-in styled template.
# Version:      3.1.0
# Date Created: 2026-05-29
# Last Updated: 2026-08-30
# Author:       Elton Boehnen
# Email:        eltonboehnen@gmail.com
# Website:      boehnenelton2024.pages.dev
# GitHub:       github.com/boehnenelton
# RELATIONAL_ID: md-to-html-cli-001
# CHANGE (2026-08-30, audit F-30): convert_markdown()'s list handling was
# anchored to zero indentation (`^[\*\-\+]\s`), so an indented nested
# list item didn't match at all -- it fell through into an accidental
# <p> as raw literal markdown text, and the parent list got split into
# two separate <ul>/<ol> blocks around it. Added _list_item_match() and
# _parse_list_block() -- an indentation-aware, recursive list parser
# supporting nested lists (any depth, unordered/ordered/mixed) -- and
# wired both list dispatch points in convert_markdown() through it.
# Verified against the exact broken case first (a real "- Item one\n  -
# Nested\n- Item two" input, confirmed producing two separate <ul>
# blocks with the nested text as a stray <p>), then confirmed the fix
# correctly nests it as one continuous list; also tested 3-level
# nesting, ordered-inside-unordered mixed nesting, and confirmed flat
# (non-nested) lists produce identical output to before. Blockquotes
# containing code blocks were checked too and already worked correctly
# via convert_markdown()'s existing recursive self-call for blockquote
# content -- no fix needed there. Multi-paragraph list items (a blank
# line starting a second paragraph within the same <li>) remain a known,
# separate gap -- a broader change to the paragraph-buffering model,
# not attempted in this pass.
# =============================================================================

import sys
import os
import re
import json
import shutil
import argparse
import tempfile
from pathlib import Path
from datetime import date

VERSION = "3.1.0"

# -----------------------------------------------------------------------------
# SCRIPT_PATH — Dynamic resolution, never hardcoded
# -----------------------------------------------------------------------------
def get_script_path() -> Path:
    return Path(__file__).resolve().parent

SCRIPT_PATH = get_script_path()

# -----------------------------------------------------------------------------
# LIBRARY BOOTSTRAPPING
# -----------------------------------------------------------------------------
LIB_DIR = SCRIPT_PATH / "lib"
MASTER_LIB_SOURCE = "/storage/emulated/0/Admin/libraries/Lib_PY/Core"

REQUIRED_LIBS = [
    "lib_bejson_core.py",
    "lib_bejson_env.py",
    "lib_bejson_errors.py"
]

def bootstrap():
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    for lib in REQUIRED_LIBS:
        target = LIB_DIR / lib
        if not target.exists():
            source = Path(MASTER_LIB_SOURCE) / lib
            if source.exists():
                shutil.copy(source, target)

bootstrap()
sys.path.insert(0, str(LIB_DIR))

# -----------------------------------------------------------------------------
# CONFIGURATION — BEJSON 104a, auto-created on first run, atomic writes
# -----------------------------------------------------------------------------
CONFIG_FILE = SCRIPT_PATH / "md-to-html.config.json"

DEFAULT_CONFIG = {
    "Format": "BEJSON",
    "Format_Version": "104a",
    "Format_Creator": "Elton Boehnen",
    "Records_Type": ["ScriptConfig"],
    "Fields": [
        {"name": "setting_name",  "type": "string"},
        {"name": "setting_value", "type": "string"},
        {"name": "description",   "type": "string"}
    ],
    "Values": [
        ["output_folder_name", "MD_TO_HTML",
         "Name of the output folder created for converted files."],
        ["default_description", "Document converted from Markdown.",
         "Fallback SEO meta description when none can be extracted."]
    ]
}

def init_config():
    if not CONFIG_FILE.exists():
        _write_config(DEFAULT_CONFIG)

def _write_config(data: dict):
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_FILE)

def load_config() -> dict:
    """Return config as a flat key→value dict."""
    raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {row[0]: row[1] for row in raw.get("Values", [])}

init_config()

# =============================================================================
# MARKDOWN → HTML CONVERSION ENGINE
# A self-contained, dependency-free converter that handles:
#   headings, bold, italic, bold+italic, inline code, code blocks (fenced),
#   blockquotes, ordered lists, unordered lists, tables, horizontal rules,
#   images, links, strikethrough, and bare paragraphs.
# =============================================================================

def _escape_html(text: str) -> str:
    """Escape characters that are special in HTML content."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))

def _inline(text: str) -> str:
    """Convert inline Markdown elements within a line of text."""
    # Preserve raw HTML tags that may already be in the text
    # Process inline code first (highest precedence — content inside is literal)
    parts = []
    last = 0
    for m in re.finditer(r'`([^`]+)`', text):
        parts.append(_inline_spans(text[last:m.start()]))
        parts.append(f"<code>{_escape_html(m.group(1))}</code>")
        last = m.end()
    parts.append(_inline_spans(text[last:]))
    return "".join(parts)

def _safe_url(url: str) -> str:
    """FIX (2026-08-31, audit F-43): _inline_spans() built href/src
    attributes directly from whatever was inside a markdown link/image's
    parentheses with zero scheme validation -- a markdown link literally
    written as `[click](javascript:alert(1))` produced a real
    `<a href="javascript:alert(1)">` in the rendered, styled HTML this
    tool serves to actual readers. Allows the schemes a legitimate
    markdown link/image realistically needs (http/https, mailto, a bare
    relative path or #anchor with no scheme at all) and rejects anything
    else -- javascript:, data:, vbscript:, file:, and any other scheme --
    by replacing the URL with a harmless "#" rather than trying to
    enumerate every dangerous scheme individually (an allowlist is safer
    here than a denylist, which is only ever as complete as the list of
    schemes someone thought to block).
    """
    url = (url or "").strip()
    m = re.match(r'^([a-zA-Z][a-zA-Z0-9+.\-]*):', url)
    if not m:
        return url  # no scheme at all -- a relative path or #anchor, safe
    scheme = m.group(1).lower()
    if scheme in ("http", "https", "mailto"):
        return url
    return "#"


def _inline_spans(text: str) -> str:
    """Handle bold, italic, strikethrough, links, and images (no inline code)."""
    # Images before links — same syntax but starts with !
    text = re.sub(
        r'!\[([^\]]*)\]\(([^)]+)\)',
        lambda m: f'<img src="{_safe_url(m.group(2))}" alt="{_escape_html(m.group(1))}" loading="lazy">',
        text
    )
    # Links
    text = re.sub(
        r'\[([^\]]+)\]\(([^)]+)\)',
        lambda m: f'<a href="{_safe_url(m.group(2))}">{_escape_html(m.group(1))}</a>',
        text
    )
    # Bold + italic (***text*** or ___text___)
    text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
    text = re.sub(r'___(.+?)___',       r'<strong><em>\1</em></strong>', text)
    # Bold (**text** or __text__)
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(.+?)__',     r'<strong>\1</strong>', text)
    # Italic (*text* or _text_)
    # Underscore italic: require non-word char on both sides to avoid MD_TO_HTML → MD<em>TO</em>HTML
    text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
    text = re.sub(r'(?<!\w)_([^_\s][^_]*)_(?!\w)', r'<em>\1</em>', text)
    # Strikethrough (~~text~~)
    text = re.sub(r'~~(.+?)~~', r'<del>\1</del>', text)
    return text

def _parse_table(lines: list) -> str:
    """Convert a Markdown table block to an HTML table.

    FIX (2026-08-31, audit F-52): line.split('|') split on every literal
    pipe character with zero escape awareness -- a cell written as
    "A \\| B" (markdown's own convention for a literal pipe inside a
    table cell) got split into two cells ("A \\" and " B") instead of
    staying one cell containing "A | B". Splits on a pipe only when it's
    NOT immediately preceded by a backslash (a negative lookbehind), then
    un-escapes any remaining "\\|" back into a literal "|" in each
    resulting cell -- the escape backslash itself shouldn't survive into
    the rendered output.
    """
    rows = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|'):
            stripped = stripped[1:]
        cells = [c.strip().replace('\\|', '|') for c in re.split(r'(?<!\\)\|', stripped)]
        # A genuine closing delimiter pipe (not an escaped one, which
        # re.split above already left as real content) produces exactly
        # one trailing empty-string cell after stripping -- drop it.
        # Escaped content can't produce this, since re.split never
        # splits on an escaped pipe in the first place.
        if cells and cells[-1] == '':
            cells.pop()
        rows.append(cells)

    if len(rows) < 2:
        return "<p>" + _inline(" ".join(lines)) + "</p>"

    html = ["<table>", "<thead>", "<tr>"]
    for cell in rows[0]:
        html.append(f"  <th>{_inline(cell)}</th>")
    html += ["</tr>", "</thead>", "<tbody>"]

    for row in rows[2:]:  # row[1] is the separator line
        html.append("<tr>")
        for cell in row:
            html.append(f"  <td>{_inline(cell)}</td>")
        html.append("</tr>")
    html += ["</tbody>", "</table>"]
    return "\n".join(html)

def _is_table_separator(line: str) -> bool:
    return bool(re.match(r'^\|?[\s\-:|]+[\|\-:]+[\s\-:|]*\|?$', line.strip()))

def _is_table_row(line: str) -> bool:
    return '|' in line

def _list_item_match(line):
    """Returns (indent, marker_type, item_text) if line is a list item at
    any indentation, else None. marker_type is 'ul' or 'ol'."""
    m = re.match(r'^(\s*)([\*\-\+])\s+(.*)$', line)
    if m:
        return len(m.group(1)), 'ul', m.group(3)
    m = re.match(r'^(\s*)(\d+)\.\s+(.*)$', line)
    if m:
        return len(m.group(1)), 'ol', m.group(3)
    return None


def _parse_list_block(lines, i, base_indent):
    """FIX (2026-08-30, audit F-30): the previous list handling matched
    only `^[\\*\\-\\+]\\s` / `^\\d+\\.\\s` -- anchored to the start of the
    line with zero indentation tolerance. An indented sub-item ("  -
    subitem") simply didn't match at all, so the parent <ul> closed
    early, the indented line fell through into an accidental <p> as raw
    literal markdown text, and the list resumed as a SECOND, separate
    <ul> afterward -- confirmed with a real "- Item one\\n  - Nested\\n-
    Item two" input before writing this fix.

    This is a bounded, tested fix for nested lists specifically (the
    audit's own concrete example) -- indentation-aware, recursive:
    collects every item at exactly `base_indent`, and for each one,
    checks whether the following line is MORE indented and still a list
    item; if so, recursively parses that as a nested list and embeds it
    inside the current <li> before closing it. Multi-paragraph list
    items (a blank line inside one <li> starting a second paragraph of
    the SAME item) are a separate, broader markdown-parsing-model change
    not attempted here -- flagged as a further known gap, not silently
    assumed fixed.

    Returns (html_string, new_i)."""
    marker_type = None
    output = []
    while i < len(lines):
        m = _list_item_match(lines[i])
        if not m or m[0] != base_indent:
            break
        indent, this_type, item_text = m
        if marker_type is None:
            marker_type = this_type
        elif this_type != marker_type:
            break  # a bullet list directly followed by a numbered list at the same indent ends this block
        i += 1
        item_html = _inline(item_text.strip())
        # Check for a nested (more-indented) list block immediately
        # following this item, before moving to the next sibling.
        nested_html = ""
        if i < len(lines):
            nm = _list_item_match(lines[i])
            if nm and nm[0] > base_indent:
                nested_html, i = _parse_list_block(lines, i, nm[0])
        output.append(f"<li>{item_html}{nested_html}</li>")
    tag = "ul" if marker_type == "ul" else "ol"
    return f"<{tag}>{''.join(output)}</{tag}>", i


def convert_markdown(md_text: str) -> str:
    """
    Convert a full Markdown document to an HTML fragment (no <html>/<body> wrapper).
    Returns the HTML string ready to be placed inside <article>.
    """
    lines = md_text.splitlines()
    output = []
    i = 0

    def flush_paragraph(buf):
        if buf:
            content = _inline(" ".join(buf))
            output.append(f"<p>{content}</p>")
            buf.clear()

    para_buf = []

    while i < len(lines):
        line = lines[i]
        raw = line  # original, unsrtipped

        # --- Fenced code block (``` or ~~~) ---
        fence_match = re.match(r'^(`{3,}|~{3,})(.*)', line)
        if fence_match:
            flush_paragraph(para_buf)
            fence_char = fence_match.group(1)
            lang = fence_match.group(2).strip()
            lang_attr = f' class="language-{_escape_html(lang)}"' if lang else ""
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith(fence_char):
                code_lines.append(_escape_html(lines[i]))
                i += 1
            output.append(f"<pre><code{lang_attr}>{chr(10).join(code_lines)}</code></pre>")
            i += 1
            continue

        # --- Horizontal rule ---
        if re.match(r'^(\*{3,}|-{3,}|_{3,})\s*$', line.strip()):
            flush_paragraph(para_buf)
            output.append("<hr>")
            i += 1
            continue

        # --- ATX Headings (# through ######) ---
        heading_match = re.match(r'^(#{1,6})\s+(.*)', line)
        if heading_match:
            flush_paragraph(para_buf)
            level = len(heading_match.group(1))
            text  = _inline(heading_match.group(2).strip())
            output.append(f"<h{level}>{text}</h{level}>")
            i += 1
            continue

        # --- Blockquote ---
        if line.startswith('>'):
            flush_paragraph(para_buf)
            bq_lines = []
            while i < len(lines) and lines[i].startswith('>'):
                bq_lines.append(lines[i].lstrip('> ').rstrip())
                i += 1
            inner = convert_markdown("\n".join(bq_lines))
            output.append(f"<blockquote>{inner}</blockquote>")
            continue

        # --- Unordered list ---
        if re.match(r'^[\*\-\+]\s', line):
            flush_paragraph(para_buf)
            list_html, i = _parse_list_block(lines, i, 0)
            output.append(list_html)
            continue

        # --- Ordered list ---
        if re.match(r'^\d+\.\s', line):
            flush_paragraph(para_buf)
            list_html, i = _parse_list_block(lines, i, 0)
            output.append(list_html)
            continue

        # --- Table (detect header row + separator row) ---
        if (_is_table_row(line)
                and i + 1 < len(lines)
                and _is_table_separator(lines[i + 1])):
            flush_paragraph(para_buf)
            table_lines = []
            while i < len(lines) and _is_table_row(lines[i]):
                table_lines.append(lines[i])
                i += 1
            output.append(_parse_table(table_lines))
            continue

        # --- Blank line — flush paragraph buffer ---
        if line.strip() == "":
            flush_paragraph(para_buf)
            i += 1
            continue

        # --- Everything else: accumulate into paragraph ---
        para_buf.append(line.strip())
        i += 1

    flush_paragraph(para_buf)
    return "\n".join(output)

# =============================================================================
# OUTPUT MODES
# =============================================================================

# --- MODE 1: RAW (default) ---
# Produces a minimal, valid HTML5 document. No style, no fonts, no fluff.
# Content is wrapped in <article> inside <body>. Semantically correct tags only.

RAW_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
</head>
<body>
<article>
{content}
</article>
</body>
</html>
"""

# --- MODE 2: STYLED (--style flag) ---
# Full ARIA-compliant page with embedded CSS, SEO/OG meta, Inter + Roboto Mono,
# #DE2626 accent, footer with author credit. Content lives inside <article>.

STYLED_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{description}">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{description}">
  <meta property="og:type" content="article">
  <title>{title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=Roboto+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    :root {{
      --white:  #FFFFFF;
      --black:  #000000;
      --red:    #DE2626;
      --muted:  #555555;
      --border: #E0E0E0;
      --code-bg:#F4F4F4;
    }}

    html {{ font-size: 16px; }}

    body {{
      font-family: 'Inter', system-ui, sans-serif;
      background: var(--white);
      color: var(--black);
      line-height: 1.7;
      display: flex;
      flex-direction: column;
      min-height: 100vh;
    }}

    /* ── Page shell ── */
    .page-header {{
      padding: 2.5rem 1.5rem 1.5rem;
      border-bottom: 2px solid var(--red);
      max-width: 860px;
      margin: 0 auto;
      width: 100%;
    }}

    .page-header h1 {{
      font-size: 2rem;
      font-weight: 700;
      color: var(--black);
      line-height: 1.2;
    }}

    main {{
      flex: 1;
      padding: 2rem 1.5rem;
      max-width: 860px;
      margin: 0 auto;
      width: 100%;
    }}

    footer {{
      padding: 2rem 1.5rem;
      border-top: 1px solid var(--border);
      max-width: 860px;
      margin: 0 auto;
      width: 100%;
      font-size: 0.875rem;
      color: var(--muted);
      line-height: 1.6;
    }}

    footer a {{ color: var(--black); font-weight: 600; text-decoration: none; }}
    footer a:hover {{ color: var(--red); }}

    /* ── Article / content ── */
    article h1,
    article h2,
    article h3,
    article h4,
    article h5,
    article h6 {{
      color: var(--red);
      font-weight: 700;
      line-height: 1.25;
      margin: 2rem 0 0.75rem;
    }}

    article h1 {{ font-size: 1.875rem; }}
    article h2 {{ font-size: 1.5rem;   border-bottom: 1px solid var(--border); padding-bottom: 0.35rem; }}
    article h3 {{ font-size: 1.25rem;  }}
    article h4 {{ font-size: 1.1rem;   }}
    article h5, article h6 {{ font-size: 1rem; }}

    article p  {{ margin: 0.85rem 0; }}

    article a  {{ color: var(--red); text-decoration: none; font-weight: 600; }}
    article a:hover {{ text-decoration: underline; }}

    article strong, article b {{ color: var(--red); font-weight: 700; }}
    article em, article i     {{ font-style: italic; }}

    article code {{
      font-family: 'Roboto Mono', monospace;
      background: var(--code-bg);
      padding: 0.15em 0.4em;
      border-radius: 3px;
      font-size: 0.88em;
    }}

    article pre {{
      background: var(--code-bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 1.25rem;
      overflow-x: auto;
      margin: 1.25rem 0;
    }}

    article pre code {{
      background: none;
      padding: 0;
      font-size: 0.85em;
    }}

    article blockquote {{
      border-left: 4px solid var(--red);
      padding: 0.5rem 1rem;
      margin: 1.25rem 0;
      color: var(--muted);
      background: #FFF5F5;
    }}

    article ul, article ol {{
      padding-left: 1.75rem;
      margin: 0.75rem 0;
    }}

    article li {{ margin: 0.3rem 0; }}

    article table {{
      width: 100%;
      border-collapse: collapse;
      margin: 1.5rem 0;
      font-size: 0.92rem;
    }}

    article th, article td {{
      text-align: left;
      padding: 0.65rem 0.85rem;
      border: 1px solid var(--border);
    }}

    article th {{
      background: var(--code-bg);
      font-weight: 700;
      color: var(--black);
    }}

    article hr {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 2rem 0;
    }}

    article img {{
      max-width: 100%;
      height: auto;
      border-radius: 4px;
    }}

    article del {{ color: var(--muted); text-decoration: line-through; }}

    /* ── Responsive ── */
    @media (max-width: 600px) {{
      .page-header h1  {{ font-size: 1.5rem; }}
      .page-header, main, footer {{ padding: 1.25rem 1rem; }}
      article h1 {{ font-size: 1.5rem; }}
      article h2 {{ font-size: 1.25rem; }}
    }}
  </style>
</head>
<body>

  <header class="page-header" role="banner">
    <h1>{title}</h1>
  </header>

  <main role="main">
    <article>
{content}
    </article>
  </main>

  <footer role="contentinfo">
    <p>Generated {date} &mdash; MD_To_HTML v{version}</p>
    <p>
      <strong>Elton Boehnen</strong> &mdash;
      <a href="mailto:eltonboehnen@gmail.com">eltonboehnen@gmail.com</a><br>
      <a href="https://boehnenelton2024.pages.dev">boehnenelton2024.pages.dev</a> &mdash;
      <a href="https://github.com/boehnenelton">github.com/boehnenelton</a>
    </p>
  </footer>

</body>
</html>
"""

# =============================================================================
# CORE CONVERSION LOGIC
# =============================================================================

def _extract_title(md_text: str, fallback: str) -> str:
    """Pull the first H1 from the doc, else derive from filename."""
    for line in md_text.splitlines():
        m = re.match(r'^#\s+(.*)', line.strip())
        if m:
            return m.group(1).strip()
    return fallback

def _extract_description(md_text: str, default: str) -> str:
    """First non-heading, non-blank line, stripped of markdown syntax, capped at 155 chars."""
    for line in md_text.splitlines():
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('|') and not line.startswith('>'):
            # Strip common inline markdown so the meta description is plain text
            plain = re.sub(r'\*{1,3}|_{1,3}|~~|`', '', line)
            plain = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', plain)  # links → text
            plain = plain.strip()
            if plain:
                return (plain[:152] + "...") if len(plain) > 155 else plain
    return default

def convert_file(md_path: Path, output_dir: Path, use_style: bool, cfg: dict):
    md_text = md_path.read_text(encoding="utf-8")
    content_html = convert_markdown(md_text)

    # Title: first H1 in the doc, else prettified filename
    fallback_title = md_path.stem.replace('_', ' ').replace('-', ' ').title()
    title = _extract_title(md_text, fallback_title)

    output_path = output_dir / f"{md_path.stem}.html"

    if use_style:
        desc = _extract_description(md_text, cfg.get("default_description", ""))
        html = STYLED_TEMPLATE.format(
            title=_escape_html(title),
            description=_escape_html(desc),
            content=content_html,
            date=date.today().isoformat(),
            version=VERSION
        )
    else:
        html = RAW_TEMPLATE.format(
            title=_escape_html(title),
            content=content_html
        )

    # Atomic write
    tmp = output_path.with_suffix(".tmp")
    tmp.write_text(html, encoding="utf-8")
    os.replace(tmp, output_path)

    mode_label = "[styled]" if use_style else "[raw]"
    print(f"  {mode_label} {md_path.name} → {output_path.name}")

def process_target(target_str: str, use_style: bool):
    target = Path(target_str).resolve()
    cfg    = load_config()
    folder = cfg.get("output_folder_name", "MD_TO_HTML")

    if target.is_file():
        if target.suffix.lower() != ".md":
            print(f"Error: '{target.name}' is not a Markdown file.")
            sys.exit(1)
        output_dir = target.parent / folder
        output_dir.mkdir(exist_ok=True)
        print(f"Target: {target}")
        print(f"Output: {output_dir}")
        convert_file(target, output_dir, use_style, cfg)

    elif target.is_dir():
        output_dir = target / folder
        output_dir.mkdir(exist_ok=True)
        md_files = sorted(target.glob("*.md"))
        if not md_files:
            print(f"No .md files found in: {target}")
            sys.exit(0)
        print(f"Target: {target}")
        print(f"Output: {output_dir}")
        print(f"Files:  {len(md_files)} Markdown file(s) found\n")
        for f in md_files:
            convert_file(f, output_dir, use_style, cfg)

    else:
        print(f"Error: '{target_str}' is not a valid file or directory.")
        sys.exit(1)

    print(f"\nDone. Output in: {output_dir}")

# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def cmd_about():
    print(f"""
╔══════════════════════════════════════════════╗
║  MD_To_HTML — Markdown to HTML Converter     ║
╠══════════════════════════════════════════════╣
║  Version:  {VERSION:<34}║
║  Created:  2026-05-29                        ║
╠══════════════════════════════════════════════╣
║  Author:   Elton Boehnen                     ║
║  Email:    eltonboehnen@gmail.com            ║
║  Site:     boehnenelton2024.pages.dev        ║
║  GitHub:   github.com/boehnenelton          ║
╚══════════════════════════════════════════════╝

Converts Markdown files to valid HTML5.

Default mode: raw, unstyled HTML wrapped in <article> tags.
--style:      full styled page with embedded CSS, SEO meta,
              Inter + Roboto Mono fonts, and author footer.
""")

def main():
    parser = argparse.ArgumentParser(
        prog="MD_To_HTML",
        description=(
            "Convert Markdown files to HTML. "
            "Default: raw, unstyled HTML in <article> tags. "
            "Add --style for the full built-in styled template."
        )
    )
    parser.add_argument(
        "target",
        nargs="?",
        help="Path to a .md file, or a directory containing .md files."
    )
    parser.add_argument(
        "--style",
        action="store_true",
        help="Enable the built-in styled template with embedded CSS, SEO meta, and author footer."
    )
    parser.add_argument(
        "--about",
        action="store_true",
        help="Display tool info and credits."
    )

    args = parser.parse_args()

    if args.about:
        cmd_about()
        return

    if not args.target:
        parser.print_help()
        sys.exit(1)

    process_target(args.target, use_style=args.style)

if __name__ == "__main__":
    main()
