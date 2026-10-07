#!/usr/bin/env python3
"""bookpdf: turn the arcs/volumes of a translated book into print-ready PDFs."""

import argparse
import os
import sys

from bookpdf import app
from bookpdf import console as con

TOOL_DIR = os.path.dirname(os.path.abspath(__file__))


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"'{value}' is not a whole number") from e
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


MAX_LOG_LINES = 30


def _log_lines(value: str) -> int:
    try:
        number = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"'{value}' is not a whole number") from e
    if not 0 <= number <= MAX_LOG_LINES:
        raise argparse.ArgumentTypeError(f"must be between 0 and {MAX_LOG_LINES}")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bookpdf",
        description="Build print-ready PDFs of translated book arcs/volumes.",
    )
    parser.add_argument("-l", "--library", default=os.path.join("..", "TranslateBook"),
                        help="folder that contains your book folders (default: ../TranslateBook)")
    parser.add_argument("-b", "--book", help="book folder name (or path) to open directly")
    parser.add_argument("--engine", choices=("auto", "tectonic", "latexmk"), default="auto",
                        help="TeX engine (default: auto, which prefers Tectonic)")
    parser.add_argument("--cjk-font", default=None,
                        help="Chinese font: a font file (.otf/.ttf/.ttc) or an installed font name (default: FandolSong)")
    parser.add_argument("--output", default="output", help="folder for finished PDFs (default: output)")
    parser.add_argument("--build-dir", default="build", help="folder for temporary build files (default: build)")
    parser.add_argument("--keep-build", action="store_true",
                        help="keep the build folder after a successful build")
    parser.add_argument("--timeout", type=_positive_int, default=180,
                        help="minutes before a build is stopped (default: 180)")
    parser.add_argument("--log-lines", type=_log_lines, default=8,
                        help="engine output lines shown under the progress bar, 0 to hide (default: 8)")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return app.run(args, TOOL_DIR)
    except KeyboardInterrupt:
        con.warn("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
