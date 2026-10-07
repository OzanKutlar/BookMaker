"""Locate a TeX engine and build its command line."""

import os
import shutil
from dataclasses import dataclass

INSTALL_HINT = (
    "bookpdf needs Tectonic (recommended) or TeX Live / MacTeX with latexmk.\n\n"
    "Windows: download tectonic.exe (see README, 'Installing Tectonic') and put it next to bookpdf.py "
    "or in a folder on your PATH.\n"
    "Mac: brew install tectonic\n"
    "Then run bookpdf again."
)


@dataclass(frozen=True)
class Engine:
    name: str
    command: tuple


def _tectonic_path(tool_dir: str) -> str | None:
    found = shutil.which("tectonic")
    if found:
        return found
    for folder in (os.getcwd(), tool_dir):
        for exe in ("tectonic.exe", "tectonic"):
            candidate = os.path.join(folder, exe)
            if os.path.isfile(candidate):
                return candidate
    return None


def _tectonic(tool_dir: str) -> Engine | None:
    path = _tectonic_path(tool_dir)
    if path is None:
        return None
    # --print streams TeX's own output, which carries the page markers the progress bar needs.
    return Engine("tectonic", (path, "--keep-logs", "--print", "main.tex"))


def _latexmk() -> Engine | None:
    latexmk, xelatex = shutil.which("latexmk"), shutil.which("xelatex")
    if not latexmk or not xelatex:
        return None
    return Engine("latexmk", (latexmk, "-xelatex", "-interaction=nonstopmode", "-halt-on-error",
                              "-file-line-error", "main.tex"))


def find_engine(preference: str, tool_dir: str) -> tuple[Engine | None, str]:
    """Return (engine, "") or (None, explanation of what to install)."""
    if preference == "tectonic":
        found = _tectonic(tool_dir)
        return found, "" if found else "Tectonic was not found.\n\n" + INSTALL_HINT
    if preference == "latexmk":
        found = _latexmk()
        return found, "" if found else "latexmk/xelatex were not found.\n\n" + INSTALL_HINT
    found = _tectonic(tool_dir) or _latexmk()
    return found, "" if found else INSTALL_HINT
