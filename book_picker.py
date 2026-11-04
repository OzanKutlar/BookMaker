"""Shared book picker: ranks books by last translation and lets the user pick one."""

import json
import os
import re
import sys
import time
from dataclasses import dataclass

from rich.console import Console
from rich.markup import escape
from rich.rule import Rule

try:
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import HSplit, Layout, Window
    from prompt_toolkit.layout.controls import FormattedTextControl
    from prompt_toolkit.patch_stdout import patch_stdout
    from prompt_toolkit.styles import Style
    HAS_PROMPT_TOOLKIT = True
except ImportError:
    HAS_PROMPT_TOOLKIT = False

ACTIVITY_FILENAME = "_activity.json"
MAX_SCAN_ENTRIES = 20_000
MAX_NUMBERED_ATTEMPTS = 5
SECONDS_PER_DAY = 86_400
VISIBLE_ROWS = 15
PAGE_JUMP = 10
FOOTER = "↑/↓ move · PgUp/PgDn jump · Enter select · Esc cancel"

CHAPTER_FILE_RE = re.compile(r"^Chapter\s+(\d+)\.md$", re.IGNORECASE)

console = Console()


def _warn(message: str) -> None:
    console.print(f"[yellow]⚠[/yellow] {message}")


def _fail(message: str) -> None:
    console.print(f"[bold red]✘[/bold red] {message}")


def _rule(title: str = "") -> None:
    console.print(Rule(f"[bold blue]{title}[/bold blue]" if title else ""))


# ----------------------------------------------------------------------
# Activity & book ranking
# ----------------------------------------------------------------------

@dataclass(frozen=True)
class BookInfo:
    name: str
    path: str
    last_translated: float | None = None
    last_chapter: int | None = None

    @property
    def hint(self) -> str:
        age = format_age(self.last_translated)
        if not age:
            return ""
        text = f"translated {age}"
        return f"{text} · ch {self.last_chapter}" if self.last_chapter else text


def _valid_chapter(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _valid_stamp(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return None
    return float(value)

def format_age(stamp: float | None, now: float | None = None) -> str:
    valid = _valid_stamp(stamp)
    if valid is None:
        return ""
    current = time.time() if now is None else now
    seconds = max(0.0, current - valid)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < SECONDS_PER_DAY:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 30 * SECONDS_PER_DAY:
        return f"{int(seconds // SECONDS_PER_DAY)}d ago"
    return time.strftime("%Y-%m-%d", time.localtime(valid))


def _read_activity_file(book_dir: str) -> dict | None:
    path = os.path.join(book_dir, ACTIVITY_FILENAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _newest_chapter_file(book_dir: str) -> tuple[float | None, int | None]:
    best: tuple[float, int] | None = None
    try:
        with os.scandir(book_dir) as entries:
            for count, entry in enumerate(entries):
                if count >= MAX_SCAN_ENTRIES:
                    break
                match = CHAPTER_FILE_RE.match(entry.name)
                if not match:
                    continue
                try:
                    if not entry.is_file():
                        continue
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                chapter = int(match.group(1))
                if best is None or mtime > best[0]:
                    best = (mtime, chapter)
    except OSError:
        return None, None
    return best if best is not None else (None, None)


def last_translated(book_dir: str) -> tuple[float | None, int | None]:
    data = _read_activity_file(book_dir)
    stamp = _valid_stamp(data.get("lastTranslated")) if data else None
    if stamp is not None:
        return stamp, _valid_chapter(data.get("lastChapter"))
    return _newest_chapter_file(book_dir)


def _is_book_dir(book_dir: str) -> bool:
    if not os.path.isdir(book_dir):
        return False
    if os.path.isfile(os.path.join(book_dir, ACTIVITY_FILENAME)):
        return True
    try:
        with os.scandir(book_dir) as entries:
            for count, entry in enumerate(entries):
                if count >= MAX_SCAN_ENTRIES:
                    break
                if CHAPTER_FILE_RE.match(entry.name) and entry.is_file():
                    return True
    except OSError:
        return False
    return False


def _book_sort_key(item: BookInfo) -> tuple:
    if item.last_translated is not None:
        return (0, -item.last_translated, item.name.lower())
    return (1, 0.0, item.name.lower())


def ordered_books(library_dir: str) -> list[BookInfo]:
    abs_lib = os.path.abspath(library_dir)
    if not os.path.isdir(abs_lib):
        return []
    books: list[BookInfo] = []
    try:
        names = os.listdir(abs_lib)
    except OSError:
        return []
    for name in names:
        if name.startswith((".", "__")):
            continue
        full_path = os.path.join(abs_lib, name)
        if not _is_book_dir(full_path):
            continue
        stamp, chapter = last_translated(full_path)
        books.append(BookInfo(name=name, path=full_path, last_translated=stamp, last_chapter=chapter))
    books.sort(key=_book_sort_key)
    return books


# ----------------------------------------------------------------------
# Interactive book picker
# ----------------------------------------------------------------------

class MenuUnavailable(RuntimeError):
    pass


class _MenuState:
    def __init__(self, count: int, default_index: int = 0):
        self.count = count
        self.index = default_index if 0 <= default_index < count else 0
        self.top = 0
        self._scroll()

    def move(self, delta: int, wrap: bool = True) -> None:
        if wrap:
            self.index = (self.index + delta) % self.count
        else:
            self.index = max(0, min(self.count - 1, self.index + delta))
        self._scroll()

    def jump(self, index: int) -> None:
        self.index = max(0, min(self.count - 1, index))
        self._scroll()

    def _scroll(self) -> None:
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + VISIBLE_ROWS:
            self.top = self.index - VISIBLE_ROWS + 1


def _render_menu(title: str, books: list[BookInfo], state: _MenuState) -> list:
    fragments = [("class:title", f" {title}\n")]
    scrolling = state.count > VISIBLE_ROWS
    end = min(state.count, state.top + VISIBLE_ROWS)
    if scrolling:
        fragments.append(("class:dim", "   ↑ more\n" if state.top > 0 else "\n"))
    for idx in range(state.top, end):
        book = books[idx]
        if idx == state.index:
            fragments.extend([("class:pointer", " ❯ "), ("class:selected", book.name)])
        else:
            fragments.extend([("", "   "), ("class:item", book.name)])
        if book.hint:
            fragments.append(("class:hint", f"  {book.hint}"))
        fragments.append(("", "\n"))
    if scrolling:
        fragments.append(("class:dim", "   ↓ more\n" if end < state.count else "\n"))
    fragments.append(("class:dim", f" {state.index + 1}/{state.count} · {FOOTER}"))
    return fragments


def _select_with_prompt_toolkit(title: str, books: list[BookInfo]) -> BookInfo | None:
    if not HAS_PROMPT_TOOLKIT or not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise MenuUnavailable("interactive terminal unavailable")
    state = _MenuState(len(books))
    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(_event):
        state.move(-1)

    @kb.add("down")
    @kb.add("j")
    def _down(_event):
        state.move(1)

    @kb.add("pageup")
    def _page_up(_event):
        state.move(-PAGE_JUMP, wrap=False)

    @kb.add("pagedown")
    def _page_down(_event):
        state.move(PAGE_JUMP, wrap=False)

    @kb.add("home")
    def _home(_event):
        state.jump(0)

    @kb.add("end")
    def _end(_event):
        state.jump(state.count - 1)

    @kb.add("enter")
    def _select(event):
        event.app.exit(result=state.index)

    @kb.add("escape", eager=True)
    @kb.add("q")
    @kb.add("c-c")
    def _cancel(event):
        event.app.exit(result=None)

    style = Style.from_dict({
        "title": "bold ansicyan",
        "pointer": "bold ansicyan",
        "selected": "reverse bold",
        "item": "",
        "hint": "ansibrightblack",
        "dim": "ansibrightblack",
    })
    control = FormattedTextControl(
        lambda: _render_menu(title, books, state), focusable=True, show_cursor=False
    )
    app = Application(
        layout=Layout(HSplit([Window(content=control, dont_extend_height=True, always_hide_cursor=True)])),
        key_bindings=kb,
        style=style,
        full_screen=False,
        mouse_support=False,
        erase_when_done=True,
    )
    try:
        with patch_stdout(raw=True):
            result = app.run()
    except Exception as e:
        raise MenuUnavailable(str(e)) from e
    return books[result] if isinstance(result, int) else None


def _select_numbered(title: str, books: list[BookInfo]) -> BookInfo | None:
    _rule(title)
    for idx, book in enumerate(books, start=1):
        hint = f"  [dim]{escape(book.hint)}[/dim]" if book.hint else ""
        console.print(f"  [cyan]{idx:2d}.[/cyan] {escape(book.name)}{hint}")
    by_name = {b.name.lower(): b for b in books}
    for _ in range(MAX_NUMBERED_ATTEMPTS):
        try:
            ans = console.input("\n[bold]Select book # ('q' to quit): [/bold]").strip()
        except (KeyboardInterrupt, EOFError):
            return None
        if ans.lower() in ("q", "quit", ""):
            return None
        if ans.isdigit():
            pos = int(ans) - 1
            if 0 <= pos < len(books):
                return books[pos]
        if ans.lower() in by_name:
            return by_name[ans.lower()]
        _warn(f"Enter a number between 1 and {len(books)}, or 'q' to quit.")
    return None


def select_book(library_dir: str, preselected: str | None = None,
                title: str = "Select book") -> BookInfo | None:
    """Returns the chosen book, or None if the user cancels or nothing matches."""
    books = ordered_books(library_dir)
    if not books:
        _fail(f"No book folders found in {escape(os.path.abspath(library_dir))}.")
        return None
    if preselected:
        clean = preselected.strip().strip('"').strip("'").rstrip("/\\")
        base = os.path.basename(clean)
        for book in books:
            if book.name.lower() == base.lower():
                return book
        _fail(f"Book '{escape(preselected)}' not found.")
        return None
    full_title = f"{title} ({os.path.abspath(library_dir)})"
    try:
        return _select_with_prompt_toolkit(full_title, books)
    except MenuUnavailable:
        return _select_numbered(title, books)
