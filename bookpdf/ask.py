"""Validated console prompts with a bounded number of attempts."""

from rich.markup import escape

from . import console as con
from . import menu

MAX_ATTEMPTS = 5


class Cancelled(Exception):
    """The user pressed Ctrl+C / Ctrl+D at a prompt."""


def _read(prompt: str) -> str:
    try:
        return con.console.input(prompt)
    except (KeyboardInterrupt, EOFError) as e:
        raise Cancelled() from e


def text(question: str, default: str = "") -> str:
    """Free text; Enter keeps the default. `question` may contain Rich markup."""
    hint = f" [dim]({escape(default)})[/dim]" if default else ""
    answer = _read(f"[bold]{question}[/bold]{hint}: ").strip()
    return answer or default


def confirm(question: str, default: bool = False) -> bool:
    """Yes/no question. `question` may contain Rich markup."""
    suffix = escape("[Y/n]" if default else "[y/N]")
    for _ in range(MAX_ATTEMPTS):
        answer = _read(f"[bold]{question}[/bold] {suffix} ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        con.warn("Please answer y or n.")
    return default


def choose(title: str, options: list[str], hints: list[str] | None = None) -> int | None:
    """Arrow-key menu with a numbered fallback. Returns the chosen index, or None if cancelled."""
    try:
        return menu.select_option(title, options, hints)
    except menu.MenuUnavailable:
        return _choose_numbered(title, options, hints)


def _choose_numbered(title: str, options: list[str], hints: list[str] | None) -> int | None:
    con.rule(escape(title))
    for i, label in enumerate(options, start=1):
        hint = hints[i - 1] if hints else ""
        suffix = f"  [dim]{escape(hint)}[/dim]" if hint else ""
        con.console.print(f"  [cyan]{i:2d}.[/cyan] {escape(label)}{suffix}")
    for _ in range(MAX_ATTEMPTS):
        answer = _read("[bold]Number (q to cancel): [/bold]").strip().lower()
        if answer in ("q", "quit"):
            return None
        if answer.isdecimal() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        con.warn(f"Enter a number between 1 and {len(options)}.")
    return None
