"""Book discovery and selection using book_picker."""

import os
import sys

# Ensure root directory is importable when running from subpackages
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import book_picker


def discover_books(library_dir: str) -> list[str]:
    """Folder names of valid books sorted by translation recency."""
    return [b.name for b in book_picker.ordered_books(library_dir)]


def select_book(library_dir: str, preselected: str | None = None) -> tuple[str, str] | None:
    """Return (book_dir, folder_name), or None if cancelled or missing."""
    chosen = book_picker.select_book(library_dir, preselected=preselected)
    if chosen is None:
        return None
    return chosen.path, chosen.name
