"""
Library:        book_writer.py
Project:        Cli_Bookwriter
Description:    Chapter-by-chapter book writer. For each not-yet-written
                 PlanTask in the active plan, the AI is given: (1) the
                 active context bubble, (2) the full plan scope (so it
                 understands the whole book's structure), and (3) the
                 previous chapter's content (for continuity) — a direct
                 port of BookGenerationTab.tsx's currentContext / lastOutput
                 chaining. Each chapter is written to books/BEJSON/<name>
                 .bejson (the resumable record --resume-plan reads back)
                 and a scratch copy under data/temp/<name>/ (deleted once
                 the whole book compiles cleanly). The finished book is a
                 single books/HTML/<name>.html file — <article> sections
                 inside <body>, no separate "library" step, no image gen.
Version:        1.0.1
Date:           2026-08-11
Author:         Elton Boehnen
Contact:        boehnenelton2024@gmail.com | boehnenelton2024.pages.dev | github.com/boehnenelton
Format_Creator: Elton Boehnen
RELATIONAL_ID:  1e2f3a4b-5c6d-4e7f-8a9b-0c1d2e3f4a55

Changelog:
  1.0.0 - Initial build.
  1.0.1 - Compiled HTML output is now explicitly wrapped in a width-capped
          .book-container (max-width:800px), with overflow-wrap/word-break
          on body, headings, paragraphs, list items, blockquotes, code, and
          pre (pre now wraps via white-space:pre-wrap instead of only
          horizontal-scrolling), plus box-sizing:border-box and a viewport
          meta tag, so nothing (long words, raw URLs, long code lines) can
          spill past the page width regardless of viewport size. No new
          visible formatting/decoration added — purely containment. The
          chapter-generation prompt also now asks the AI to write wrapping
          prose and use Markdown link syntax instead of bare long URLs.
"""

import html
import re
import shutil
import time
from pathlib import Path

import text_correction

BOOK_FIELDS = [
    {"name": "entry_id", "type": "string"},
    {"name": "topic", "type": "string"},
    {"name": "title", "type": "string"},
    {"name": "plan_name", "type": "string"},
    {"name": "generation_date", "type": "string"},
]
CHAPTER_FIELDS = [
    {"name": "chapter_number", "type": "integer"},
    {"name": "chapter_title", "type": "string"},
    {"name": "content", "type": "string"},
]
# Positional indices, named so callers never have to guess a magic number.
BOOK_ROW_TOPIC_INDEX = 1
BOOK_ROW_TITLE_INDEX = 2
CHAPTER_ROW_NUMBER_INDEX = 0
CHAPTER_ROW_TITLE_INDEX = 1
CHAPTER_ROW_CONTENT_INDEX = 2

CHAPTER_PROMPT_TEMPLATE = """You are writing a book titled "{book_title}" on the topic of "{topic}".

*** CRITICAL INSTRUCTION ***
Your CURRENT ASSIGNMENT is to ONLY write the content for the single chapter titled: "{chapter_title}".
Do NOT write the entire book. Do NOT write other chapters. Focus exclusively on delivering a complete,
high-quality draft of this one chapter, in Markdown.

Write in normal wrapping prose paragraphs. Do not dump raw long unbroken lines (long URLs, long
unbroken code lines, ASCII art, etc.) — if you include a link, use Markdown link syntax
[text](url) rather than a bare URL, and keep code lines reasonably short so they read cleanly in a
narrow, fixed-width container.

--- ATTACHED CONTEXT (reference material) ---
{attached_context}

--- DOCUMENT PLAN SCOPE (for reference ONLY, so you understand the whole book's structure) ---
{plan_scope}

--- PREVIOUS CHAPTER (for continuity ONLY — do not rewrite this) ---
{previous_chapter_content}
"""

DEFAULT_SYSTEM_INSTRUCTION = (
    "You are a skilled, structured non-fiction author. Write complete, well-organized "
    "chapters in clean Markdown. Stay strictly within the chapter you were assigned."
)


class BookWriter:
    def __init__(self, dir_books_bejson: Path, dir_books_html: Path, dir_temp: Path):
        self.dir_books_bejson = dir_books_bejson
        self.dir_books_html = dir_books_html
        self.dir_temp = dir_temp

    def _load_bejson_core_lib(self):
        import lib_bejson_Core_bejson_core as BEJSONCore
        return BEJSONCore

    def _book_bejson_path(self, plan_name: str) -> Path:
        return self.dir_books_bejson / f"{plan_name}.bejson"

    def _load_or_create_book_doc(self, plan_name: str, topic: str, title: str) -> dict:
        bejson_core_lib = self._load_bejson_core_lib()
        book_bejson_path = self._book_bejson_path(plan_name)
        if book_bejson_path.exists():
            existing_book_doc = bejson_core_lib.bejson_core_load_file(str(book_bejson_path))
            if existing_book_doc:
                return existing_book_doc
        return {
            "Format": "BEJSON", "Format_Version": "104a", "Format_Creator": "Elton Boehnen",
            "Records_Type": ["Book", "Chapter"],
            "Fields": {"Book": BOOK_FIELDS, "Chapter": CHAPTER_FIELDS},
            "Book": [[plan_name, topic, title, plan_name, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())]],
            "Chapters": [],
        }

    def _save_book_doc(self, plan_name: str, book_doc: dict):
        self._load_bejson_core_lib().bejson_core_atomic_write(str(self._book_bejson_path(plan_name)), book_doc)

    @staticmethod
    def _already_written_chapter_numbers(book_doc: dict):
        return {chapter_row[CHAPTER_ROW_NUMBER_INDEX] for chapter_row in book_doc.get("Chapters", [])}

    @staticmethod
    def _chapter_content_by_number(book_doc: dict, chapter_number: int):
        for chapter_row in book_doc.get("Chapters", []):
            if chapter_row[CHAPTER_ROW_NUMBER_INDEX] == chapter_number:
                return chapter_row[CHAPTER_ROW_CONTENT_INDEX]
        return None

    def write_or_resume_book(self, plan_name: str, plan_doc: dict, active_context_text: str,
                              generate_text_fn, status_fn, auto_run: bool = True):
        """generate_text_fn(prompt) -> str : the caller's AI call, already
        bound to a key/model/system-instruction.
        status_fn(message) -> None : never-silent progress reporting.
        auto_run : bool : if True, writes all chapters in sequence. If False, stops after writing 1 chapter.
        Returns (book_doc, html_output_path or None)."""
        plan_field_index_map = {field_def["name"]: field_index
                                 for field_index, field_def in enumerate(plan_doc["Fields"])}
        plan_task_rows = plan_doc.get("Values", [])
        if not plan_task_rows:
            raise ValueError(f"Plan '{plan_name}' has no chapters. Re-run --generate-plan.")

        book_title = plan_doc.get("Writing_Title", plan_name)
        book_topic = plan_doc.get("Book_Goal", book_title)
        book_doc = self._load_or_create_book_doc(plan_name, book_topic, book_title)
        already_written_chapter_numbers = self._already_written_chapter_numbers(book_doc)

        plan_scope_text = "\n".join(
            f"{chapter_number}. {task_row[plan_field_index_map['Task_Name']]}"
            for chapter_number, task_row in enumerate(plan_task_rows, start=1)
        )

        chapter_scratch_dir = self.dir_temp / plan_name
        chapter_scratch_dir.mkdir(parents=True, exist_ok=True)

        previous_chapter_content = ""
        highest_written_chapter_number = max(already_written_chapter_numbers) if already_written_chapter_numbers else 0
        if highest_written_chapter_number:
            previous_chapter_content = self._chapter_content_by_number(book_doc, highest_written_chapter_number) or ""

        total_chapter_count = len(plan_task_rows)
        chapters_written_this_run = 0

        for chapter_number, task_row in enumerate(plan_task_rows, start=1):
            chapter_title = task_row[plan_field_index_map["Task_Name"]]

            if chapter_number in already_written_chapter_numbers:
                status_fn(f"Chapter {chapter_number}/{total_chapter_count} \"{chapter_title}\" "
                           f"already written — skipping (resume).")
                previous_chapter_content = self._chapter_content_by_number(book_doc, chapter_number) or previous_chapter_content
                continue

            status_fn(f"Writing chapter {chapter_number}/{total_chapter_count}: \"{chapter_title}\"...")
            chapter_prompt = CHAPTER_PROMPT_TEMPLATE.format(
                book_title=book_title, topic=book_topic, chapter_title=chapter_title,
                attached_context=(active_context_text or "(no context attached)"),
                plan_scope=plan_scope_text,
                previous_chapter_content=(previous_chapter_content or "(this is the first chapter)"),
            )
            raw_chapter_content = generate_text_fn(chapter_prompt)
            corrected_chapter_content, _ = text_correction.fix_text(raw_chapter_content)

            book_doc.setdefault("Chapters", []).append(
                [chapter_number, chapter_title, corrected_chapter_content])
            self._save_book_doc(plan_name, book_doc)

            chapter_scratch_file_slug = f"{chapter_number:02d}_" + re.sub(
                r"[^A-Za-z0-9_\-]", "_", chapter_title)[:50]
            (chapter_scratch_dir / f"{chapter_scratch_file_slug}.md").write_text(
                corrected_chapter_content, encoding="utf-8")

            previous_chapter_content = corrected_chapter_content
            already_written_chapter_numbers.add(chapter_number)
            chapters_written_this_run += 1
            status_fn(f"Chapter {chapter_number}/{total_chapter_count} done "
                      f"({len(corrected_chapter_content)} chars).")

            if not auto_run:
                status_fn(f"Auto-run is OFF (--auto-run off). Pausing after chapter {chapter_number}/{total_chapter_count}. "
                          f"Re-run --write-book or --resume-plan to write the next chapter.")
                break

        # Check if all chapters in the plan are completed
        all_completed = len(already_written_chapter_numbers) >= total_chapter_count

        if all_completed:
            html_output_path = self._compile_single_html(plan_name, book_doc)
            shutil.rmtree(chapter_scratch_dir, ignore_errors=True)
            status_fn(f"All {total_chapter_count} chapters completed! Book compiled -> {html_output_path}. Scratch files cleared.")
            return book_doc, html_output_path
        else:
            status_fn(f"Book writing paused ({len(already_written_chapter_numbers)}/{total_chapter_count} chapters written so far). "
                      f"Progress saved to BEJSON record.")
            return book_doc, None

    # --- Markdown -> HTML (minimal, dependency-free) ---
    @staticmethod
    def _markdown_to_html_fragment(markdown_text: str) -> str:
        markdown_lines = markdown_text.splitlines()
        html_output_lines = []
        inside_code_block = False
        for markdown_line in markdown_lines:
            if markdown_line.strip().startswith("```"):
                inside_code_block = not inside_code_block
                html_output_lines.append("<pre><code>" if inside_code_block else "</code></pre>")
                continue
            if inside_code_block:
                html_output_lines.append(html.escape(markdown_line))
                continue
            heading_match = re.match(r"^(#{1,6})\s+(.*)", markdown_line)
            if heading_match:
                heading_level = min(len(heading_match.group(1)) + 1, 6)  # nest under the chapter <h2>
                html_output_lines.append(f"<h{heading_level}>{html.escape(heading_match.group(2))}</h{heading_level}>")
                continue
            if not markdown_line.strip():
                html_output_lines.append("")
                continue
            escaped_line = html.escape(markdown_line)
            escaped_line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped_line)
            escaped_line = re.sub(r"\*(.+?)\*", r"<i>\1</i>", escaped_line)
            html_output_lines.append(f"<p>{escaped_line}</p>")
        return "\n".join(html_output_lines)

    def _compile_single_html(self, plan_name: str, book_doc: dict) -> Path:
        book_row = book_doc["Book"][0]
        book_title = book_row[BOOK_ROW_TITLE_INDEX]
        book_topic = book_row[BOOK_ROW_TOPIC_INDEX]
        sorted_chapter_rows = sorted(book_doc.get("Chapters", []), key=lambda row: row[CHAPTER_ROW_NUMBER_INDEX])

        article_sections = []
        for chapter_row in sorted_chapter_rows:
            chapter_title = chapter_row[CHAPTER_ROW_TITLE_INDEX]
            chapter_html_body = self._markdown_to_html_fragment(chapter_row[CHAPTER_ROW_CONTENT_INDEX])
            article_sections.append(
                f'<article id="chapter-{chapter_row[CHAPTER_ROW_NUMBER_INDEX]}">\n'
                f'<h2>{html.escape(chapter_title)}</h2>\n{chapter_html_body}\n</article>'
            )

        compiled_html_document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(book_title)}</title>
<style>
*{{box-sizing:border-box;}}
body{{background:#FFFFFF;color:#000000;font-family:Inter,sans-serif;margin:0;padding:0 1rem;overflow-wrap:break-word;word-wrap:break-word;word-break:break-word;}}
.book-container{{max-width:800px;width:100%;margin:0 auto;padding:2rem 0;}}
h1,h2,h3{{font-family:'Source Code Pro',monospace;overflow-wrap:break-word;word-break:break-word;}}
p,li,blockquote{{overflow-wrap:break-word;word-wrap:break-word;word-break:break-word;}}
pre{{background:#000000;color:#FFFFFF;padding:1rem;overflow-x:auto;white-space:pre-wrap;overflow-wrap:break-word;word-break:break-word;max-width:100%;}}
code{{overflow-wrap:break-word;word-break:break-word;}}
img{{max-width:100%;height:auto;}}
article{{margin-bottom:3rem;max-width:100%;}}
footer{{margin-top:3rem;border-top:1px solid #000;padding-top:1rem;font-size:0.85rem;overflow-wrap:break-word;}}
</style>
</head>
<body>
<div class="book-container">
<h1>{html.escape(book_title)}</h1>
<p><em>{html.escape(book_topic)}</em></p>
{''.join(article_sections)}
<footer>
Elton Boehnen | boehnenelton2024@gmail.com | boehnenelton2024.pages.dev |
<a href="https://github.com/boehnenelton">github.com/boehnenelton</a>
</footer>
</div>
</body>
</html>"""
        html_output_path = self.dir_books_html / f"{plan_name}.html"
        html_output_path.write_text(compiled_html_document, encoding="utf-8")
        return html_output_path
