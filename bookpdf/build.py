"""Arc build: workspace, chapter conversion with progress, compilation and output."""

import os
import re
import shutil
import time
from dataclasses import dataclass

from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from . import console as con
from . import convert, template, texrun
from .arcs import ArcRange
from .chapters import ChapterIndex, format_ranges
from .engine import Engine

CHARS_PER_PAGE = 1900        # rough fill of one 14pt A4 page, used only for the pass-1 estimate
TOC_ENTRIES_PER_PAGE = 80
MAX_FAILURES_SHOWN = 10
FONT_EXTENSIONS = (".otf", ".ttf", ".ttc")
_ILLEGAL_FILENAME_CHARS = '\\/:*?"<>|'
_FONT_NAME_RE = re.compile(r"^[\w .\-]+$")


@dataclass(frozen=True)
class BookInfo:
    title: str
    author: str
    index: ChapterIndex


@dataclass(frozen=True)
class BuildOptions:
    engine: Engine
    output_dir: str
    build_dir: str
    cjk_font: str | None
    keep_build: bool
    timeout_s: int
    log_lines: int = 8


@dataclass(frozen=True)
class _Prepared:
    workdir: str
    sources: dict   # "ch-0001" -> (canonical chapter number, label in this PDF)
    chars: int
    failed: list    # (chapter number, reason)
    notices: tuple = ()  # (chapter number, automatic repair worth checking)


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------

def build_arc(book: BookInfo, arc: ArcRange, opts: BuildOptions, limit: int | None = None) -> bool:
    """Build one arc (or its first `limit` chapters). Returns True when a PDF was produced."""
    numbers = book.index.present_in(arc.start, arc.end)
    if limit:
        numbers = numbers[:limit]
    if not numbers:
        con.fail(f"No chapter files found for {escape(arc.name)} (Chapters {arc.start}–{arc.end}).")
        return False
    label = f"{book.title} - {arc.name}" + (" (test)" if limit else "")
    con.rule(escape(label))
    if not limit:
        _warn_missing(book.index, arc)
    started = time.monotonic()
    try:
        prepared = _prepare(book, arc, opts, numbers, limit)
    except OSError as e:
        con.fail(f"Could not prepare the build folder: {escape(str(e))}")
        return False
    if prepared is None:
        return False
    _report_conversion_failures(prepared.failed)
    _report_notices(prepared.notices)
    log_path = os.path.join(prepared.workdir, "build.log")
    con.info(f"Compiling with [bold]{opts.engine.name}[/bold] · log: [cyan]{escape(log_path)}[/cyan]")
    estimate = _estimate_pages(prepared.chars, len(prepared.sources))
    result = texrun.run_compile(opts.engine.command, prepared.workdir, estimate, opts.timeout_s, log_path,
                                opts.log_lines)
    _report_missing_chars(result.missing_chars, prepared.sources)
    if not result.ok:
        _report_failure(result, prepared, book.index)
        return False
    return _finish(opts, prepared, result, label, time.monotonic() - started)


# ----------------------------------------------------------------------
# Preparation
# ----------------------------------------------------------------------

def _warn_missing(index: ChapterIndex, arc: ArcRange) -> None:
    missing = index.missing_in(arc.start, arc.end)
    if missing:
        con.warn(f"{len(missing):,} chapter(s) missing and skipped: {format_ranges(missing)}")


def _prepare(book: BookInfo, arc: ArcRange, opts: BuildOptions, numbers: list[int], limit) -> _Prepared | None:
    """Write main.tex, chapters.tex and one .tex per chapter. Raises OSError on file problems."""
    workdir = _workspace(opts.build_dir, book.title, arc, limit)
    chapter_dir = os.path.join(workdir, "chapters")
    os.makedirs(chapter_dir, exist_ok=True)
    sources, chars, failed, notices = _convert_all(book.index, arc, numbers, chapter_dir)
    if not sources:
        con.fail("Every chapter failed to convert; nothing to compile.")
        _report_conversion_failures(failed)
        return None
    cjk_setup = _cjk_font_setup(opts.cjk_font, workdir)
    if cjk_setup is None:
        return None
    _write_text(os.path.join(workdir, template.MANIFEST_NAME), _manifest(sources))
    title_line = f"{book.title} - {arc.name}"
    _write_text(os.path.join(workdir, "main.tex"), template.render_main(title_line, book.author, cjk_setup))
    return _Prepared(workdir, sources, chars, failed, tuple(notices))


def _conversion_columns() -> tuple:
    return (
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("chapters"),
        TimeElapsedColumn(),
    )


def _convert_all(index: ChapterIndex, arc: ArcRange, numbers: list[int], chapter_dir: str) -> tuple[dict, int, list, list]:
    sources, failed, notices, chars, printed = {}, [], [], 0, 0
    with Progress(*_conversion_columns(), console=con.console) as progress:
        task = progress.add_task("Converting", total=len(numbers))
        for number in numbers:
            progress.update(task, description=f"Converting Chapter {number}")
            afterword = arc.is_afterword(number)
            file_id = f"ch-{len(sources) + 1:04d}"
            tex_path = os.path.join(chapter_dir, file_id + ".tex")
            written, reason, warnings = _convert_one(index.path(number), afterword, tex_path)
            notices.extend((number, warning) for warning in warnings)
            if written is None:
                failed.append((number, reason))
            else:
                sources[file_id] = (number, "afterword" if afterword else f"Chapter {printed + 1}")
                printed += 0 if afterword else 1
                chars += written
            progress.advance(task)
        progress.update(task, description="Converted")
    return sources, chars, failed, notices


def _convert_one(md_path: str, afterword: bool, tex_path: str) -> tuple[int | None, str, tuple]:
    """Convert and write one chapter. Returns (body length, "", warnings) or (None, reason, ())."""
    try:
        chapter = convert.convert_file(md_path)
    except Exception as e:  # mistletoe can raise anything on odd input; skip just this chapter
        return None, f"{type(e).__name__}: {e}", ()
    text = convert.section_command(chapter.title, numbered=not afterword) + chapter.body + "\n"
    try:
        _write_text(tex_path, text)
    except OSError as e:
        return None, f"could not write {os.path.basename(tex_path)}: {e}", ()
    return len(chapter.body), "", chapter.warnings


def _manifest(sources: dict) -> str:
    return "".join(r"\input{chapters/" + file_id + ".tex}" + "\n" for file_id in sources)


def _cjk_font_setup(font: str | None, workdir: str) -> str | None:
    """LaTeX line selecting the Chinese font, or None (after reporting) when unusable."""
    if not font:
        return template.DEFAULT_CJK_FONT
    if os.path.isfile(font):
        return _copy_font(font, workdir)
    if os.path.splitext(font)[1].lower() in FONT_EXTENSIONS:
        con.fail(f"Font file not found: {escape(font)}")
        return None
    if not _FONT_NAME_RE.match(font):
        con.fail(f"Unsupported characters in font name: {escape(font)}")
        return None
    return template.cjk_font_by_name(font)


def _copy_font(font: str, workdir: str) -> str | None:
    name = os.path.basename(font)
    if os.path.splitext(name)[1].lower() not in FONT_EXTENSIONS or not _FONT_NAME_RE.match(name):
        con.fail(f"Use an .otf, .ttf or .ttc file with a plain file name: {escape(name)}")
        return None
    fonts_dir = os.path.join(workdir, "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    shutil.copyfile(font, os.path.join(fonts_dir, name))
    return template.cjk_font_from_file(name)


def _slug(text: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-").lower()[:50].strip("-")
    return slug or fallback


def _workspace(build_dir: str, title: str, arc: ArcRange, limit) -> str:
    suffix = "-test" if limit else ""
    return os.path.join(build_dir, _slug(title, "book"), f"{arc.index:02d}-{_slug(arc.name, arc.kind)}{suffix}")


def _write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _estimate_pages(chars: int, chapter_count: int) -> int:
    # Each chapter starts on a new page, so about half a page per chapter is left empty.
    return int(chars / CHARS_PER_PAGE + chapter_count * 0.5 + chapter_count / TOC_ENTRIES_PER_PAGE + 2)


# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------

def _safe_filename(name: str) -> str:
    for ch in _ILLEGAL_FILENAME_CHARS:
        name = name.replace(ch, "_")
    return name.strip().rstrip(".")[:150] or "book"


def _duration(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def _finish(opts: BuildOptions, prepared: _Prepared, result, label: str, seconds: float) -> bool:
    source_pdf = os.path.join(prepared.workdir, "main.pdf")
    target = os.path.join(opts.output_dir, _safe_filename(label) + ".pdf")
    try:
        os.makedirs(opts.output_dir, exist_ok=True)
        shutil.copyfile(source_pdf, target)
        size_mb = os.path.getsize(target) / (1024 * 1024)
    except OSError as e:
        con.fail(f"Compiled, but could not copy the PDF to the output folder: {escape(str(e))}")
        con.info(f"The PDF is still at [cyan]{escape(source_pdf)}[/cyan]")
        return False
    con.panel(
        f"[bold]{escape(label)}[/bold]\n"
        f"{len(prepared.sources):,} chapters · {result.pages:,} pages · {size_mb:.1f} MB · {_duration(seconds)}\n"
        f"[cyan]{escape(target)}[/cyan]",
        title="✨ PDF ready",
        style="green",
    )
    if not opts.keep_build:
        _remove_workspace(prepared.workdir)
    return True


def _remove_workspace(workdir: str) -> None:
    try:
        shutil.rmtree(workdir)
    except OSError as e:
        con.warn(f"Could not remove the build folder {escape(workdir)}: {escape(str(e))}")


MAX_MISSING_SHOWN = 15
MAX_CHAPTERS_PER_CHAR = 5


def _report_notices(notices) -> None:
    """Problems in the chapter files that were repaired automatically but deserve a look."""
    if not notices:
        return
    lines = [f"Chapter {number}: {escape(note)}" for number, note in notices[:MAX_FAILURES_SHOWN]]
    if len(notices) > MAX_FAILURES_SHOWN:
        lines.append(f"… and {len(notices) - MAX_FAILURES_SHOWN} more")
    con.panel("\n".join(lines), title="Fixed automatically, worth checking", style="yellow")


def _char_label(code: str) -> str:
    try:
        return f"{chr(int(code[2:], 16))} ({code})"
    except ValueError:
        return code


def _report_missing_chars(missing: dict, sources: dict) -> None:
    """Characters no font could print come out blank on paper, so list them with their chapters."""
    if not missing:
        return
    lines = []
    for code in sorted(missing)[:MAX_MISSING_SHOWN]:
        numbers = sorted(sources[cid][0] for cid in missing[code] if cid in sources)
        where = ", ".join(f"Chapter {n}" for n in numbers[:MAX_CHAPTERS_PER_CHAR]) or "front matter"
        lines.append(f"{_char_label(code)} · {where}")
    if len(missing) > MAX_MISSING_SHOWN:
        lines.append(f"… and {len(missing) - MAX_MISSING_SHOWN} more")
    lines.append("[dim]These print as blanks. A font that also covers traditional Chinese fixes them, "
                 "e.g. --cjk-font C:\\Windows\\Fonts\\simsun.ttc[/dim]")
    con.panel("\n".join(lines), title=f"{len(missing)} character(s) missing from the Chinese font", style="yellow")


def _report_conversion_failures(failed: list) -> None:
    if not failed:
        return
    lines = [f"Chapter {number}: {escape(reason)}" for number, reason in failed[:MAX_FAILURES_SHOWN]]
    if len(failed) > MAX_FAILURES_SHOWN:
        lines.append(f"… and {len(failed) - MAX_FAILURES_SHOWN} more")
    con.panel("\n".join(lines), title=f"{len(failed)} chapter(s) skipped", style="yellow")


def _describe_error(error, sources: dict, index: ChapterIndex) -> str:
    message = escape(error.message)
    source = sources.get(error.chapter_id)
    if source is None:
        place = f" ({escape(error.file)}, line {error.line})" if error.file and error.line else ""
        return f"• {message}{place}"
    where = f", line {error.line} of its .tex" if error.line else ""
    number, label = source
    md_name = escape(os.path.basename(index.path(number)))
    return f"• [bold]Chapter {number}[/bold] ({label} in this PDF{where}) → {md_name}\n  {message}"


def _report_failure(result, prepared: _Prepared, index: ChapterIndex) -> None:
    lines = [f"[bold]{escape(result.message)}[/bold]"]
    lines.extend(_describe_error(error, prepared.sources, index) for error in result.errors)
    if not result.errors and result.tail:
        lines.append("[dim]Last output:[/dim]")
        lines.extend(f"[dim]{escape(line)}[/dim]" for line in result.tail[-15:])
    lines.append(f"\nFull log: [cyan]{escape(os.path.join(prepared.workdir, 'build.log'))}[/cyan]")
    con.panel("\n".join(lines), title="❌ Build failed", style="red")
