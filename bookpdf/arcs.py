"""Arcs.json, shared with the translator (its booktl/arcs.py writes the same schema).

    {
      "version": 1,
      "bookName": "Forty Millenniums of Cultivation",
      "author": "Wo Niu Zhen Ren (卧牛真人)",
      "arcs": [
        {"endChapter": 2001, "storyEndChapter": 2000, "name": "Volume 1", "type": "volume", "source": "model"},
        {"endChapter": 3000, "name": "Volume 2", "type": "volume", "source": "user"}
      ]
    }

Each arc stores only its last chapter and starts one chapter after the previous arc.
storyEndChapter (optional) marks where the story ended before an afterword was folded in.
Unknown keys are preserved on every write.
"""

import json
import os
import shutil
from dataclasses import dataclass

ARCS_FILENAME = "Arcs.json"
SCHEMA_VERSION = 1
KINDS = ("volume", "arc")


@dataclass(frozen=True)
class ArcRange:
    index: int      # 1-based position in the book
    name: str
    kind: str       # "volume" or "arc"
    start: int
    end: int
    story_end: int  # equals end unless an afterword was folded in
    source: str     # "user", "model" or ""

    def is_afterword(self, chapter: int) -> bool:
        return self.story_end < chapter <= self.end


def arcs_path(book_dir: str) -> str:
    return os.path.join(book_dir, ARCS_FILENAME)


def arcs_exist(book_dir: str) -> bool:
    return os.path.isfile(arcs_path(book_dir))


def _empty_data() -> dict:
    return {"version": SCHEMA_VERSION, "bookName": "", "author": "", "arcs": []}


def load_arcs(book_dir: str) -> tuple[dict | None, str | None]:
    """Return (data, None), or (None, error) when Arcs.json exists but is unusable.

    A missing file is not an error; it yields an empty structure.
    """
    path = arcs_path(book_dir)
    if not os.path.exists(path):
        return _empty_data(), None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, f"Could not read {ARCS_FILENAME}: {e}"
    if not isinstance(data, dict) or not isinstance(data.get("arcs", []), list):
        return None, f"{ARCS_FILENAME} does not have the expected structure"
    for key, default in _empty_data().items():
        data.setdefault(key, default)
    return data, None


def save_arcs(book_dir: str, data: dict) -> None:
    """Write Arcs.json via a temp file and rename, so a crash never leaves half a file."""
    path = arcs_path(book_dir)
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except OSError:
        _discard_temp(tmp_path)
        raise


def _discard_temp(tmp_path: str) -> None:
    """Best-effort cleanup after a failed save; the caller re-raises the original error."""
    try:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass  # the save error being re-raised is the one that matters


def backup_arcs(book_dir: str) -> str | None:
    """Copy Arcs.json to Arcs.json.bak. Returns the backup path, or None if there is no file."""
    path = arcs_path(book_dir)
    if not os.path.isfile(path):
        return None
    backup = path + ".bak"
    shutil.copyfile(path, backup)
    return backup


def _positive_int(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def arc_ranges(data: dict) -> list[ArcRange]:
    """Turn stored end chapters into consecutive start–end ranges."""
    entries = [a for a in data.get("arcs", []) if isinstance(a, dict) and _positive_int(a.get("endChapter"))]
    entries.sort(key=lambda a: a["endChapter"])
    ranges, start = [], 1
    for arc in entries:
        end = arc["endChapter"]
        if end < start:
            continue  # duplicate end chapter; the first one wins
        kind = arc.get("type") if arc.get("type") in KINDS else "volume"
        story_end = _positive_int(arc.get("storyEndChapter"))
        if story_end is None or not start <= story_end <= end:
            story_end = end
        number = len(ranges) + 1
        name = str(arc.get("name") or "").strip() or f"{kind.title()} {number}"
        ranges.append(ArcRange(number, name, kind, start, end, story_end, str(arc.get("source") or "")))
        start = end + 1
    return ranges


def next_start(data: dict) -> int:
    """First chapter not covered by any arc."""
    ranges = arc_ranges(data)
    return ranges[-1].end + 1 if ranges else 1


def book_title(data: dict, folder: str) -> str:
    return str(data.get("bookName") or "").strip() or folder
