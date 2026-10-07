"""Read-only book discovery and selection (same picker as the translator, but never writes)."""

import os

from rich.markup import escape

from . import ask
from . import console as con


def discover_books(library_dir: str) -> list[str]:
    """Sorted folder names inside the library folder."""
    abs_lib = os.path.abspath(library_dir)
    if not os.path.isdir(abs_lib):
        return []
    try:
        entries = os.listdir(abs_lib)
    except OSError as e:
        con.fail(f"Could not read the library folder: {escape(str(e))}")
        return []
    names = [d for d in entries if not d.startswith(".") and os.path.isdir(os.path.join(abs_lib, d))]
    return sorted(names, key=str.lower)


def select_book(library_dir: str, preselected: str | None = None) -> tuple[str, str] | None:
    """Return (book_dir, folder_name), or None if nothing was chosen."""
    abs_lib = os.path.abspath(library_dir)
    books = discover_books(abs_lib)
    if preselected:
        resolved = _resolve_preselected(abs_lib, books, preselected)
        if resolved:
            return resolved
    if not books:
        con.fail(f"No book folders found in [cyan]{escape(abs_lib)}[/cyan]")
        con.info("Point -l/--library at the translator's library folder.")
        return None
    if len(books) == 1:
        con.info(f"Auto-selected the only book: [bold green]{escape(books[0])}[/bold green]")
        return os.path.join(abs_lib, books[0]), books[0]
    idx = ask.choose(f"Select a book ({abs_lib})", books)
    if idx is None:
        return None
    return os.path.join(abs_lib, books[idx]), books[idx]


def _resolve_preselected(abs_lib: str, books: list[str], preselected: str) -> tuple[str, str] | None:
    if preselected in books:
        return os.path.join(abs_lib, preselected), preselected
    if os.path.isdir(preselected):
        path = os.path.abspath(preselected)
        return path, os.path.basename(path)
    con.warn(f"Book '{escape(preselected)}' not found in {escape(abs_lib)}")
    return None
