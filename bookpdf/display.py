"""Rich output for the book overview, arc table and build summary."""

import os

from rich.markup import escape
from rich.table import Table

from . import arcs, chapters
from . import console as con

MAX_DUPLICATES_SHOWN = 5
_ORIGIN = {"user": "you", "model": "translator"}


def _span(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}–{end}"


def _missing_cell(missing: int) -> str:
    return f"[red]{missing:,}[/red]" if missing else "[dim]0[/dim]"


def show_chapter_summary(index) -> None:
    missing = index.missing_in(1, index.highest)
    line = f"[bold]{index.count:,}[/bold] chapter files · Chapters 1–{index.highest}"
    if missing:
        line += f" · [yellow]{len(missing):,} missing[/yellow] ({chapters.format_ranges(missing)})"
    con.info(line)
    for number, path in index.duplicates[:MAX_DUPLICATES_SHOWN]:
        con.warn(f"Duplicate file for Chapter {number} ignored: {escape(os.path.basename(path))}")


def show_overview(title: str, data: dict, index) -> None:
    author = str(data.get("author") or "").strip()
    subtitle = escape(f"by {author}") if author else "author not set (Edit book name / author)"
    con.banner(escape(title), subtitle)
    show_chapter_summary(index)
    ranges = arcs.arc_ranges(data)
    if not ranges:
        con.warn("No arcs/volumes defined yet.")
    con.console.print(_arc_table(ranges, index, arcs.next_start(data)))


def _arc_table(ranges: list, index, next_start: int) -> Table:
    table = Table(header_style="bold cyan")
    columns = (("#", "right"), ("Name", "left"), ("Type", "left"), ("Chapters", "left"),
               ("Count", "right"), ("Missing", "right"), ("From", "left"))
    for column, justify in columns:
        table.add_column(column, justify=justify)
    for arc in ranges:
        table.add_row(*_arc_row(arc, index))
    if next_start <= index.highest:
        table.add_row(*_unassigned_row(next_start, index))
    return table


def _arc_row(arc, index) -> tuple:
    present = len(index.present_in(arc.start, arc.end))
    name = escape(arc.name)
    if arc.story_end < arc.end:
        name += f" [dim](+ afterword {_span(arc.story_end + 1, arc.end)})[/dim]"
    origin = _ORIGIN.get(arc.source, "–")
    return (
        str(arc.index), name, arc.kind, _span(arc.start, arc.end), f"{present:,}",
        _missing_cell(arc.end - arc.start + 1 - present), f"[dim]{origin}[/dim]",
    )


def _unassigned_row(start: int, index) -> tuple:
    present = len(index.present_in(start, index.highest))
    return (
        "[dim]–[/dim]", "[dim]Unassigned[/dim]", "", f"[dim]{_span(start, index.highest)}[/dim]",
        f"[dim]{present:,}[/dim]", _missing_cell(index.highest - start + 1 - present), "",
    )


def show_build_summary(results: list) -> None:
    table = Table(header_style="bold cyan", title="Build summary")
    table.add_column("Arc")
    table.add_column("Result")
    for arc, ok in results:
        table.add_row(escape(arc.name), "[green]✔ built[/green]" if ok else "[red]✘ failed[/red]")
    con.console.print(table)
