"""Run the TeX engine with a live page progress bar.

XeTeX prints "[N" whenever it finishes page N and starts again at 1 on every pass, so those
markers drive the bar. Pass 1 uses an estimated total; later passes use the exact page count
of the previous pass. The "last output" timer shows whether the engine is still working.
"""

import collections
import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field

from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from . import console as con

POLL_SECONDS = 0.25
MAX_LINES_PER_TICK = 5000
STALL_WARN_SECONDS = 60
MAX_ERRORS = 15
TAIL_LINES = 40
EXIT_WAIT_SECONDS = 60
NEW_PASS_MIN_PAGES = 3  # "[1" only starts a new pass if the previous pass got further than this
PHASE_TYPESETTING = "Typesetting"
PHASE_WRITING = "Writing PDF"
PHASE_DOWNLOADING = "Downloading TeX support files (first run only)"

_PAGE_RE = re.compile(r"(?:^|(?<=[\s\])]))\[(\d+)(?=[\]\s{<(]|$)")
_PASS_RE = re.compile(r"This is XeTeX|Rerunning|Run number \d+ of rule", re.IGNORECASE)
_PDF_RE = re.compile(r"xdvipdfmx", re.IGNORECASE)
_DOWNLOAD_RE = re.compile(r"download", re.IGNORECASE)
_CHAPTER_OPEN_RE = re.compile(r"chapters[/\\](ch-\d+)\.tex")
_FILE_LINE_RE = re.compile(r"^(?:error:\s*)?(\S*?\.tex):(\d+):\s*(.+)$")
_BANG_RE = re.compile(r"^!\s*(.+)$")
_TOOL_ERROR_RE = re.compile(r"^error:\s*(.+)$")


@dataclass
class CompileError:
    chapter_id: str  # e.g. "ch-0012", or "" when unknown
    line: str        # TeX line number, or ""
    message: str


@dataclass
class CompileResult:
    ok: bool
    pages: int
    seconds: float
    message: str
    errors: list
    tail: list


@dataclass
class _State:
    estimated: int
    started: float
    last_output: float
    pass_no: int = 0
    page: int = 0
    exact_total: int = 0
    phase: str = "Starting"
    chapter_id: str = ""
    errors: list = field(default_factory=list)
    tail: collections.deque = field(default_factory=lambda: collections.deque(maxlen=TAIL_LINES))


# ----------------------------------------------------------------------
# Output interpretation
# ----------------------------------------------------------------------

def _start_pass(state: _State) -> None:
    if state.page > 0:
        state.exact_total = state.page
    state.pass_no += 1
    state.page = 0
    if state.phase != PHASE_WRITING:
        state.phase = PHASE_TYPESETTING


def _track_pages(state: _State, line: str) -> None:
    for match in _PAGE_RE.finditer(line):
        number = int(match.group(1))
        line_continues = match.end() < len(line)  # "[1" at a line end may be a wrapped "[123"
        if number == 1 and line_continues and state.page >= NEW_PASS_MIN_PAGES:
            _start_pass(state)
        if number > state.page:
            state.pass_no = max(state.pass_no, 1)
            state.page = number
            if state.phase != PHASE_WRITING:
                state.phase = PHASE_TYPESETTING


def _add_error(state: _State, error: CompileError) -> None:
    if len(state.errors) >= MAX_ERRORS:
        return
    if any(e.message == error.message and e.chapter_id == error.chapter_id for e in state.errors):
        return
    state.errors.append(error)


def _track_errors(state: _State, line: str) -> None:
    match = _FILE_LINE_RE.match(line)
    if match:
        opened = _CHAPTER_OPEN_RE.findall(match.group(1))
        chapter = opened[-1] if opened else state.chapter_id
        _add_error(state, CompileError(chapter, match.group(2), match.group(3).strip()))
        return
    match = _BANG_RE.match(line) or _TOOL_ERROR_RE.match(line)
    if match:
        _add_error(state, CompileError(state.chapter_id, "", match.group(1).strip()))


def _handle_line(state: _State, line: str, log) -> None:
    state.last_output = time.monotonic()
    state.tail.append(line)
    log.write(line + "\n")
    if _PASS_RE.search(line) and (state.page > 0 or state.pass_no == 0):
        _start_pass(state)
    opened = _CHAPTER_OPEN_RE.findall(line)
    if opened:
        state.chapter_id = opened[-1]
    if _DOWNLOAD_RE.search(line) and state.page == 0 and state.phase != PHASE_WRITING:
        state.phase = PHASE_DOWNLOADING
    if _PDF_RE.search(line):
        state.phase = PHASE_WRITING
    _track_pages(state, line)
    _track_errors(state, line)


# ----------------------------------------------------------------------
# Progress display
# ----------------------------------------------------------------------

def _columns() -> tuple:
    return (
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TextColumn("{task.completed:>5.0f}/{task.total:.0f} pages"),
        TimeElapsedColumn(),
    )


def _refresh(progress: Progress, task, state: _State) -> None:
    total = max(state.exact_total or state.estimated, state.page, 1)
    silent = time.monotonic() - state.last_output
    style = "yellow" if silent >= STALL_WARN_SECONDS else "dim"
    if state.phase == PHASE_WRITING or state.pass_no == 0:
        label = state.phase
    else:
        approx = "" if state.exact_total else " · total estimated"
        label = f"{state.phase} · pass {state.pass_no}{approx}"
    description = f"[bold blue]{escape(label)}[/bold blue] [{style}]· last output {silent:.0f}s ago[/{style}]"
    progress.update(task, completed=min(state.page, total), total=total, description=description)


# ----------------------------------------------------------------------
# Process handling
# ----------------------------------------------------------------------

def _reader(stream, lines: queue.Queue) -> None:
    """Background thread: forward engine output line by line; None marks the end."""
    try:
        for line in stream:
            lines.put(line.rstrip("\r\n"))
    except (OSError, ValueError) as e:
        lines.put(f"[bookpdf] lost engine output: {e}")
    finally:
        lines.put(None)


def _spawn(command: tuple, workdir: str) -> tuple[subprocess.Popen | None, str]:
    # Long log lines stop TeX from wrapping page markers and error messages mid-way.
    env = dict(os.environ, max_print_line="10000", error_line="254", half_error_line="238")
    try:
        proc = subprocess.Popen(
            list(command), cwd=workdir, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except OSError as e:
        return None, f"Could not start {os.path.basename(command[0])}: {e}"
    return proc, ""


def _stop(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
        proc.wait(timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        con.warn(f"Could not stop the TeX engine cleanly: {escape(str(e))}")


def _wait(proc: subprocess.Popen) -> int:
    try:
        return proc.wait(timeout=EXIT_WAIT_SECONDS)
    except subprocess.TimeoutExpired:
        _stop(proc)
        return -1


def _drain(lines: queue.Queue, state: _State, log) -> bool:
    """Handle output for one tick (about POLL_SECONDS). Returns True once the output has ended."""
    tick_end = time.monotonic() + POLL_SECONDS
    for _ in range(MAX_LINES_PER_TICK):
        remaining = tick_end - time.monotonic()
        if remaining <= 0:
            return False
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            return False
        if line is None:
            return True
        _handle_line(state, line, log)
    return False


def _stream(lines: queue.Queue, state: _State, timeout_s: int, log_path: str) -> bool:
    """Show progress until the output ends (True) or the timeout passes (False)."""
    deadline = time.monotonic() + timeout_s
    max_ticks = int(timeout_s / POLL_SECONDS) * 4 + 1  # hard bound; the deadline normally ends it
    with open(log_path, "w", encoding="utf-8") as log, Progress(*_columns(), console=con.console) as progress:
        task = progress.add_task("Starting", total=state.estimated)
        for _ in range(max_ticks):
            finished = _drain(lines, state, log)
            _refresh(progress, task, state)
            if finished:
                return True
            if time.monotonic() > deadline:
                return False
    return False


def _result(state: _State, ok: bool, message: str) -> CompileResult:
    return CompileResult(
        ok=ok,
        pages=max(state.exact_total, state.page),
        seconds=time.monotonic() - state.started,
        message=message,
        errors=list(state.errors),
        tail=list(state.tail),
    )


def run_compile(command: tuple, workdir: str, estimated_pages: int, timeout_s: int, log_path: str) -> CompileResult:
    """Run the engine in workdir, streaming its output to log_path behind a progress bar."""
    started = time.monotonic()
    state = _State(estimated=max(int(estimated_pages), 1), started=started, last_output=started)
    proc, problem = _spawn(command, workdir)
    if proc is None:
        return _result(state, False, problem)
    lines = queue.Queue()
    threading.Thread(target=_reader, args=(proc.stdout, lines), daemon=True).start()
    try:
        finished = _stream(lines, state, timeout_s, log_path)
    except KeyboardInterrupt:
        _stop(proc)
        return _result(state, False, "Build cancelled with Ctrl+C.")
    except OSError as e:
        _stop(proc)
        return _result(state, False, f"Could not write the build log: {e}")
    if not finished:
        _stop(proc)
        return _result(state, False, f"Build stopped after {timeout_s // 60} minutes. Use --timeout to allow longer.")
    code = _wait(proc)
    if code != 0:
        return _result(state, False, f"The TeX engine exited with code {code}.")
    if not os.path.isfile(os.path.join(workdir, "main.pdf")):
        return _result(state, False, "The engine finished but no main.pdf was produced.")
    return _result(state, True, "")
