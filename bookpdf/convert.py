"""Markdown chapter -> LaTeX conversion, adapted from the original md_to_tex script.

Differences from the clipboard script:
  * returns text instead of copying it, and never exits the program,
  * takes the title from the '# Chapter N: Title' heading (falls back to 'Chapter N - Title' file names),
  * removes [[Chapter N]] wikilinks and images,
  * wraps '(TN: ...)' paragraphs in the tnote macro from the template,
  * escapes every LaTeX special character itself and never turns body headings into chapters.
"""

import os
import re
from dataclasses import dataclass

import mistletoe
from mistletoe.latex_renderer import LaTeXRenderer

MAX_TITLE_SCAN_LINES = 10

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_CHAPTER_PREFIX_RE = re.compile(r"^(?:Chapter|Ch\.?)\s*\d+\s*(?:[:：.\-–—]\s*)?", re.IGNORECASE)
_FILENAME_TITLE_RE = re.compile(r"^Chapter\s+\d+\s*-\s*(.+)$", re.IGNORECASE)
_WIKILINK_LINE_RE = re.compile(r"^[ \t]*\[\[[^\]\n]*\]\][ \t]*$", re.MULTILINE)
_WIKILINK_RE = re.compile(r"\[\[(?:[^\]|\n]*\|)?([^\]\n]*)\]\]")
_IMAGE_RE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")
_TN_START_RE = re.compile(r"^\s*[(（]\s*TN\b", re.IGNORECASE)
_SINGLE_NEWLINE_RE = re.compile(r"(?<!\n)\n(?!\n)")
_PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}")

# Letter-only placeholders survive Markdown parsing and escaping unchanged.
_DOLLAR_TOKEN = "BOOKPDFDOLLARSIGNX"
_TNOTE_TOKEN = "BOOKPDFTNOTE{:05d}X"

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}


@dataclass(frozen=True)
class ConvertedChapter:
    title: str  # plain text, not yet escaped
    body: str   # LaTeX
    warnings: tuple = ()  # automatic source repairs worth telling the user about


def latex_escape(text: str) -> str:
    return "".join(_LATEX_SPECIALS.get(ch, ch) for ch in text)


def _code_text(token) -> str:
    content = getattr(token, "content", None)
    if isinstance(content, str):
        return content
    children = getattr(token, "children", None) or []
    return "".join(getattr(child, "content", "") for child in children)


class _BookRenderer(LaTeXRenderer):
    """LaTeXRenderer with full escaping and no sectioning, verbatim, link or image commands."""

    def render_raw_text(self, token, escape=True):
        return latex_escape(token.content) if escape else token.content

    def render_heading(self, token):
        return "\n" + r"\begin{center}\textbf{" + self.render_inner(token) + r"}\end{center}" + "\n"

    def render_inline_code(self, token):
        return r"\texttt{" + latex_escape(_code_text(token)) + "}"

    def render_block_code(self, token):
        lines = [latex_escape(line) for line in _code_text(token).strip("\n").split("\n")]
        body = (r"\\" + "\n").join(lines)
        return "\n" + r"\begin{flushleft}\ttfamily" + "\n" + body + "\n" + r"\end{flushleft}" + "\n"

    def render_link(self, token):
        return self.render_inner(token)

    def render_auto_link(self, token):
        return self.render_inner(token)

    def render_image(self, token):
        return ""


def fix_markdown_line_breaks(md_text: str) -> str:
    """Turn single Enters into double Enters so every line becomes its own paragraph."""
    text = md_text.replace("\r\n", "\n").replace("\r", "\n")
    return _SINGLE_NEWLINE_RE.sub("\n\n", text)


_PLAIN_TITLE_RE = re.compile(r"^(?:Chapter|Ch\.?)\s*\d+\b\s*[:：.\-–—]?\s*(.*)$", re.IGNORECASE)
_EMPHASIS_WRAP_RE = re.compile(r"^(\*\*|__|\*|_)(.+)\1$")
MAX_PLAIN_TITLE_LENGTH = 200


def _title_from_line(line: str) -> str | None:
    """Title from '# Chapter N: Title', '**Chapter N: Title**' or a plain 'Chapter N: Title' line.

    Returns None when the line is not a title line. Any Markdown heading counts as a title;
    a plain line only counts when it starts with 'Chapter N'.
    """
    text = line.strip()
    heading = _HEADING_RE.match(text)
    if heading:
        text = heading.group(1).strip()
    wrapped = _EMPHASIS_WRAP_RE.match(text)
    if wrapped:
        text = wrapped.group(2).strip()
    if heading:
        return _CHAPTER_PREFIX_RE.sub("", text, count=1).strip()
    plain = _PLAIN_TITLE_RE.match(text)
    if plain and len(text) <= MAX_PLAIN_TITLE_LENGTH:
        return plain.group(1).strip()
    return None


def split_title(md_text: str, file_stem: str = "") -> tuple[str, str]:
    """Return (title, body). The first heading is removed from the body."""
    lines = md_text.split("\n")
    for i, line in enumerate(lines[:MAX_TITLE_SCAN_LINES]):
        if not line.strip():
            continue
        title = _title_from_line(line)
        if title is not None:
            return title, "\n".join(lines[:i] + lines[i + 1:])
        break
    match = _FILENAME_TITLE_RE.match(file_stem)
    return (match.group(1).strip() if match else ""), md_text


_OPEN_DOUBLE_RE = re.compile(r'(^|[\s(\[{—–/‘*_-])"', re.MULTILINE)
_OPEN_SINGLE_RE = re.compile(r"(^|[\s(\[{—–/“*_-])'", re.MULTILINE)


def smart_quotes(text: str) -> str:
    """Straight quotes -> curly quotes. XeLaTeX would otherwise print every straight double quote as a closing quote."""
    text = _OPEN_DOUBLE_RE.sub(r"\1“", text).replace('"', "”")
    return _OPEN_SINGLE_RE.sub(r"\1‘", text).replace("'", "’")


MAX_QUOTE_DEPTH = 3     # LaTeX allows 6 nested lists/quotes; leave room for lists inside quotes
MAX_LINES_LISTED = 5
_CONFLICT_LINE_RE = re.compile(r"^(?:<{7}|>{7})(?:[ \t].*)?$")
_CONFLICT_STRIP_RE = re.compile(r"^(?:<{7}|={7}|>{7})(?:[ \t].*)?$\n?", re.MULTILINE)
_DEEP_QUOTE_RE = re.compile(r"^((?:[ \t]{0,3}>){%d})(?:[ \t]*>)+" % MAX_QUOTE_DEPTH, re.MULTILINE)


def _line_list(numbers: list[int]) -> str:
    shown = ", ".join(str(n) for n in numbers[:MAX_LINES_LISTED])
    return shown + (" …" if len(numbers) > MAX_LINES_LISTED else "")


def _repair_source(text: str) -> tuple[str, list[str]]:
    """Fix input that would break the build: leftover git conflict markers and runaway quote nesting."""
    warnings = []
    markers = [i + 1 for i, line in enumerate(text.split("\n")) if _CONFLICT_LINE_RE.match(line)]
    if markers:
        # '=======' lines are only removed when real conflict markers prove the file was mid-merge.
        text = _CONFLICT_STRIP_RE.sub("", text)
        warnings.append(f"removed git merge-conflict marker(s) on line {_line_list(markers)}; check the text around them")
    text, flattened = _DEEP_QUOTE_RE.subn(r"\1", text)
    if flattened:
        warnings.append(f"flattened {flattened} quote line(s) nested deeper than {MAX_QUOTE_DEPTH} levels")
    return text, warnings


def _clean(md_text: str) -> str:
    text = _WIKILINK_LINE_RE.sub("", md_text)
    text = _WIKILINK_RE.sub(lambda m: m.group(1), text)
    text = _IMAGE_RE.sub("", text)
    return smart_quotes(text).replace("$", _DOLLAR_TOKEN)  # the $ swap keeps mistletoe from treating $...$ as math


def _extract_tnotes(md_text: str) -> tuple[str, list[str]]:
    kept, notes = [], []
    for paragraph in _PARAGRAPH_SPLIT_RE.split(md_text):
        if _TN_START_RE.match(paragraph):
            kept.append(_TNOTE_TOKEN.format(len(notes)))
            notes.append(paragraph.strip())
        else:
            kept.append(paragraph)
    return "\n\n".join(kept), notes


def _render(md_text: str) -> str:
    with _BookRenderer() as renderer:
        return renderer.render_inner(mistletoe.Document(md_text)).strip()


def convert_markdown(md_text: str, file_stem: str = "") -> ConvertedChapter:
    text = md_text.replace("\r\n", "\n").replace("\r", "\n")
    text, warnings = _repair_source(text)
    title, body = split_title(text, file_stem)
    body, notes = _extract_tnotes(fix_markdown_line_breaks(_clean(body)))
    latex = _render(body)
    for i, note in enumerate(notes):
        latex = latex.replace(_TNOTE_TOKEN.format(i), r"\tnote{" + _render(note) + "}", 1)
    return ConvertedChapter(
        title=smart_quotes(title),
        body=latex.replace(_DOLLAR_TOKEN, r"\$"),
        warnings=tuple(warnings),
    )


def convert_file(path: str) -> ConvertedChapter:
    """Convert one chapter file. Raises OSError / UnicodeDecodeError on unreadable files."""
    with open(path, "r", encoding="utf-8-sig") as f:
        md_text = f.read()
    stem = os.path.splitext(os.path.basename(path))[0]
    return convert_markdown(md_text, stem)


TOC_ELLIPSIS = "…"
_TOC_TRIM_CHARS = " ,;:.-–—"
MIN_WORD_CUT_RATIO = 0.5  # back up to a word boundary only if at least half the room stays used


def toc_title(title: str, max_len: int) -> str:
    """Shorten a title for the table of contents: cut at a word boundary and end with '…'.

    max_len <= 0 keeps the whole title. The result never exceeds max_len characters.
    """
    text = " ".join(str(title or "").split())
    limit = int(max_len)
    if limit <= 0 or len(text) <= limit:
        return text
    cut = text[:limit - 1]  # leave room for the ellipsis
    if text[len(cut)] != " ":  # the cut lands inside a word
        space = cut.rfind(" ")
        if space >= limit * MIN_WORD_CUT_RATIO:
            cut = cut[:space]
    return cut.rstrip(_TOC_TRIM_CHARS) + TOC_ELLIPSIS


def _toc_entry(title: str, safe: str, toc_max: int) -> str:
    """TOC text: the short title in the contents, the full one in the PDF bookmark."""
    short = latex_escape(toc_title(title, toc_max))
    if short == safe:
        return safe
    return r"\texorpdfstring{" + short + "}{" + safe + "}"


def section_command(title: str, numbered: bool, toc_max: int = 0) -> str:
    """Chapter heading. Numbered chapters count from 1 per PDF; afterwords get no number.

    The table of contents shows the title cut to toc_max characters (0 = whole); the heading
    on the page and the PDF bookmark keep the full title.
    """
    safe = latex_escape(title)
    entry = _toc_entry(title, safe, toc_max)
    if numbered:
        if entry == safe:
            return r"\section{" + safe + "}" + "\n\n"
        # Braces keep a ']' inside the title from ending the optional argument early.
        return r"\section[{" + entry + "}]{" + safe + "}" + "\n\n"
    return (r"\section*{" + safe + "}" + "\n"
            + r"\phantomsection\addcontentsline{toc}{section}{" + entry + "}" + "\n\n")
