"""Interactive main loop: pick a book, manage its arcs/volumes and build PDFs."""

import os
from dataclasses import dataclass

from rich.markup import escape

from . import arcs, ask, build, chapters, define, display, engine, template
from . import console as con
from . import library as lib

MAX_MENU_ROUNDS = 1000
TEST_CHAPTERS = 5

_ACTIONS = (
    ("build", "Build PDF for an arc", "pick one arc/volume"),
    ("test", "Test build", f"first {TEST_CHAPTERS} chapters of an arc; quick check"),
    ("all", "Build all arcs", "one PDF per arc/volume"),
    ("more", "Define more arcs", "continue after the last arc"),
    ("redefine", "Redefine all arcs", "start over; Arcs.json.bak keeps the old ones"),
    ("meta", "Edit book name / author", "title page details"),
    ("switch", "Switch book", ""),
    ("quit", "Quit", ""),
)


@dataclass
class Session:
    book_dir: str
    folder: str
    index: chapters.ChapterIndex
    data: dict

    @property
    def title(self) -> str:
        return arcs.book_title(self.data, self.folder)

    @property
    def author(self) -> str:
        return str(self.data.get("author") or "").strip()

    @property
    def ranges(self) -> list:
        return arcs.arc_ranges(self.data)


def run(args, tool_dir: str) -> int:
    con.banner("bookpdf", "Arc / volume → PDF builder")
    try:
        session = _open_book(args.library, args.book)
    except ask.Cancelled:
        con.warn("Cancelled.")
        return 1
    if session is None:
        return 1
    for _ in range(MAX_MENU_ROUNDS):
        display.show_overview(session.title, session.data, session.index)
        try:
            action = _main_menu(session)
        except ask.Cancelled:
            return 0
        if action in (None, "quit"):
            return 0
        session = _run_action(action, session, args, tool_dir)
    return 0


# ----------------------------------------------------------------------
# Loading and saving
# ----------------------------------------------------------------------

def _open_book(library: str, preselected: str | None) -> Session | None:
    picked = lib.select_book(library, preselected)
    if picked is None:
        return None
    book_dir, folder = picked
    return _load_session(book_dir, folder, setup=True)


def _load_session(book_dir: str, folder: str, setup: bool) -> Session | None:
    try:
        index = chapters.scan_chapters(book_dir)
    except OSError as e:
        con.fail(f"Could not read {escape(book_dir)}: {escape(str(e))}")
        return None
    if index.count == 0:
        con.fail(f"No 'Chapter N.md' files found in {escape(book_dir)}")
        return None
    data, err = arcs.load_arcs(book_dir)
    if err:
        con.fail(escape(err))
        con.info("Fix or rename the file, then run bookpdf again. It will not overwrite it.")
        return None
    session = Session(book_dir, folder, index, data)
    return _first_time_setup(session) if setup else session


def _first_time_setup(session: Session) -> Session:
    """Ask for missing book details, and for arcs when the book has none yet."""
    changed = define.ensure_metadata(session.data, session.folder)
    if not session.data["arcs"]:
        if not arcs.arcs_exist(session.book_dir):
            con.info("This book has no Arcs.json yet. Let's define its arcs/volumes.")
        display.show_chapter_summary(session.index)
        changed = define.define_arcs(session.data, session.index) > 0 or changed
    if not changed:
        return session
    return _save(session) or session


def _reload(session: Session) -> Session | None:
    return _load_session(session.book_dir, session.folder, setup=False)


def _save(session: Session) -> Session | None:
    try:
        arcs.save_arcs(session.book_dir, session.data)
    except OSError as e:
        con.fail(f"Could not save Arcs.json: {escape(str(e))}")
        return _reload(session)
    con.ok(f"Saved [cyan]{escape(arcs.arcs_path(session.book_dir))}[/cyan]")
    return session


# ----------------------------------------------------------------------
# Menu
# ----------------------------------------------------------------------

def _available_actions(session: Session) -> list[tuple[str, str, str]]:
    hidden = set()
    if not session.ranges:
        hidden |= {"build", "test", "all", "redefine"}
    if arcs.next_start(session.data) > session.index.highest:
        hidden.add("more")
    return [action for action in _ACTIONS if action[0] not in hidden]


def _main_menu(session: Session) -> str | None:
    actions = _available_actions(session)
    idx = ask.choose("What next?", [a[1] for a in actions], [a[2] for a in actions])
    return actions[idx][0] if idx is not None else None


def _run_action(action: str, session: Session, args, tool_dir: str) -> Session:
    try:
        return _dispatch(action, session, args, tool_dir) or session
    except ask.Cancelled:
        con.warn("Cancelled; unsaved changes were discarded.")
        return _reload(session) or session


def _dispatch(action: str, session: Session, args, tool_dir: str) -> Session | None:
    if action == "switch":
        return _open_book(args.library, None)
    if action == "meta":
        define.ask_metadata(session.data, session.folder)
        return _save(session)
    if action == "more":
        return _save(session) if define.define_arcs(session.data, session.index) else None
    if action == "redefine":
        return _redefine(session)
    if action in ("build", "test"):
        _build_one(session, args, tool_dir, TEST_CHAPTERS if action == "test" else None)
    elif action == "all":
        _build_all(session, args, tool_dir)
    return None


def _redefine(session: Session) -> Session | None:
    count = len(session.ranges)
    if not ask.confirm(f"Replace all {count} arcs, including any the translator recorded?"):
        return None
    try:
        backup = arcs.backup_arcs(session.book_dir)
    except OSError as e:
        con.fail(f"Could not back up Arcs.json ({escape(str(e))}); nothing was changed.")
        return None
    if backup:
        con.info(f"Backup saved to [cyan]{escape(backup)}[/cyan]")
    session.data["arcs"] = []
    define.define_arcs(session.data, session.index)
    return _save(session)


# ----------------------------------------------------------------------
# Building
# ----------------------------------------------------------------------

def _pick_arc(session: Session, title: str) -> arcs.ArcRange | None:
    ranges = session.ranges
    labels = [f"{r.index}. {r.name}" for r in ranges]
    hints = [f"Ch {r.start}–{r.end} · {len(session.index.present_in(r.start, r.end)):,} chapters" for r in ranges]
    idx = ask.choose(title, labels, hints)
    return ranges[idx] if idx is not None else None


def _confirm_missing(session: Session, arc: arcs.ArcRange) -> bool:
    missing = session.index.missing_in(arc.start, arc.end)
    if not missing:
        return True
    con.warn(f"{len(missing):,} chapter(s) missing in {escape(arc.name)}: {chapters.format_ranges(missing)}")
    con.dim("Missing chapters are skipped, so the chapter numbers after a gap shift down.")
    return ask.confirm("Build anyway?")


def _build_options(args, tool_dir: str) -> build.BuildOptions | None:
    found, problem = engine.find_engine(args.engine, tool_dir)
    if found is None:
        con.panel(escape(problem), title="No TeX engine found", style="red")
        return None
    return build.BuildOptions(
        engine=found,
        output_dir=os.path.abspath(args.output),
        build_dir=os.path.abspath(args.build_dir),
        cjk_font=args.cjk_font,
        keep_build=args.keep_build,
        timeout_s=args.timeout * 60,
        log_lines=args.log_lines,
        toc_layout=template.TOC_LAYOUTS[args.density],
        toc_title_length=args.toc_title_length,
    )


def _book_info(session: Session) -> build.BookInfo:
    return build.BookInfo(title=session.title, author=session.author, index=session.index)


def _build_one(session: Session, args, tool_dir: str, limit: int | None) -> None:
    arc = _pick_arc(session, "Select an arc to test" if limit else "Select an arc to build")
    if arc is None:
        return
    if not limit and not _confirm_missing(session, arc):
        return
    opts = _build_options(args, tool_dir)
    if opts is not None:
        build.build_arc(_book_info(session), arc, opts, limit)


def _build_all(session: Session, args, tool_dir: str) -> None:
    ranges = session.ranges
    if not ask.confirm(f"Build all {len(ranges)} arcs? Large books can take a long time."):
        return
    opts = _build_options(args, tool_dir)
    if opts is None:
        return
    info = _book_info(session)
    results = [(arc, build.build_arc(info, arc, opts)) for arc in ranges]
    display.show_build_summary(results)
