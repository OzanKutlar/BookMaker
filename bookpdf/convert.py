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


def split_title(md_text: str, file_stem: str = "") -> tuple[str, str]:
    """Return (title, body). The first heading is removed from the body."""
    lines = md_text.split("\n")
    for i, line in enumerate(lines[:MAX_TITLE_SCAN_LINES]):
        if not line.strip():
            continue
        match = _HEADING_RE.match(line)
        if match:
            title = _CHAPTER_PREFIX_RE.sub("", match.group(1), count=1).strip()
            return title, "\n".join(lines[:i] + lines[i + 1:])
        break
    match = _FILENAME_TITLE_RE.match(file_stem)
    return (match.group(1).strip() if match else ""), md_text


def _clean(md_text: str) -> str:
    text = _WIKILINK_LINE_RE.sub("", md_text)
    text = _WIKILINK_RE.sub(lambda m: m.group(1), text)
    text = _IMAGE_RE.sub("", text)
    return text.replace("$", _DOLLAR_TOKEN)  # keeps mistletoe from treating $...$ as math


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
    title, body = split_title(text, file_stem)
    body, notes = _extract_tnotes(fix_markdown_line_breaks(_clean(body)))
    latex = _render(body)
    for i, note in enumerate(notes):
        latex = latex.replace(_TNOTE_TOKEN.format(i), r"\tnote{" + _render(note) + "}", 1)
    return ConvertedChapter(title=title, body=latex.replace(_DOLLAR_TOKEN, r"\$"))


def convert_file(path: str) -> ConvertedChapter:
    """Convert one chapter file. Raises OSError / UnicodeDecodeError on unreadable files."""
    with open(path, "r", encoding="utf-8-sig") as f:
        md_text = f.read()
    stem = os.path.splitext(os.path.basename(path))[0]
    return convert_markdown(md_text, stem)


def section_command(title: str, numbered: bool) -> str:
    """Chapter heading. Numbered chapters count from 1 per PDF; afterwords get no number."""
    safe = latex_escape(title)
    if numbered:
        return r"\section{" + safe + "}" + "\n\n"
    return (r"\section*{" + safe + "}" + "\n"
            + r"\phantomsection\addcontentsline{toc}{section}{" + safe + "}" + "\n\n")
