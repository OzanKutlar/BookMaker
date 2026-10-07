"""Interactive arc/volume definition and book metadata prompts."""

from rich.markup import escape

from . import arcs, ask
from . import console as con

MAX_ARCS = 500


def ensure_metadata(data: dict, folder: str) -> bool:
    """Ask for the book name and author once, while bookName is still empty. Returns True if asked."""
    if str(data.get("bookName") or "").strip():
        return False
    con.info(f"Title page details for [bold]{escape(folder)}[/bold] (asked once, saved in Arcs.json).")
    ask_metadata(data, folder)
    return True


def ask_metadata(data: dict, folder: str) -> None:
    name = str(data.get("bookName") or "").strip() or folder
    author = str(data.get("author") or "").strip()
    data["bookName"] = ask.text("Book name", name)
    data["author"] = ask.text("Author" if author else "Author (Enter to leave blank)", author)


def define_arcs(data: dict, index) -> int:
    """Ask for arc end chapters until 'done'. Appends to data['arcs'] and returns how many were added."""
    start, highest = arcs.next_start(data), index.highest
    if start > highest:
        con.info(f"Every translated chapter (1–{highest}) already belongs to an arc.")
        return 0
    kind = _ask_kind(data)
    if kind is None:
        return 0
    _explain(kind)
    added = 0
    for _ in range(MAX_ARCS):
        if start > highest:
            break
        number = len(arcs.arc_ranges(data)) + 1
        end = _ask_end(kind, number, start, highest)
        if end is None:
            break
        default_name = f"{kind.title()} {number}"
        name = ask.text(f"Name for {default_name} (Chapters {start}–{end})", default_name)
        data["arcs"].append({"endChapter": end, "name": name, "type": kind, "source": "user"})
        con.ok(f"{default_name}: Chapters {start}–{end} · “{escape(name)}”")
        added += 1
        start = end + 1
    return added


def _ask_kind(data: dict) -> str | None:
    ranges = arcs.arc_ranges(data)
    if ranges:
        return ranges[-1].kind
    idx = ask.choose("Does this book use volumes or arcs?", ["Volumes", "Arcs"])
    if idx is None:
        return None
    return "volume" if idx == 0 else "arc"


def _explain(kind: str) -> None:
    title = kind.title()
    con.panel(
        f"Enter the [bold]last chapter[/bold] of each {kind}.\n"
        f"Example: 2000 → {title} 1 is Chapters 1–2000, then 3000 → {title} 2 is Chapters 2001–3000.\n"
        f"Type [bold]rest[/bold] to put every remaining chapter in one final {kind}, "
        f"or press Enter / type [bold]done[/bold] to stop.",
        title=f"Define {kind}s",
        style="cyan",
    )


def _ask_end(kind: str, number: int, start: int, highest: int) -> int | None:
    question = f"Last chapter of {kind.title()} {number} ({start}–{highest})"
    for _ in range(ask.MAX_ATTEMPTS):
        answer = ask.text(question).strip().lower()
        if answer in ("", "done", "q"):
            return None
        if answer == "rest":
            return highest
        if answer.isdecimal() and start <= int(answer) <= highest:
            return int(answer)
        con.warn(f"Enter a chapter between {start} and {highest}, 'rest', or 'done'.")
    return None
