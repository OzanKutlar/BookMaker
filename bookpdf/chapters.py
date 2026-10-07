"""Discovery of translated 'Chapter N.md' files in a book folder."""

import os
import re
from dataclasses import dataclass

MAX_RANGES_SHOWN = 8

# The translator saves "Chapter 12.md"; "Chapter 12 - Title.md" is accepted too.
_CHAPTER_FILE_RE = re.compile(r"^Chapter\s+(\d+)(?:\s*-\s*.+)?\.md$", re.IGNORECASE)


@dataclass(frozen=True)
class ChapterIndex:
    files: dict        # chapter number -> file path
    duplicates: tuple  # (chapter number, ignored file path)

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def highest(self) -> int:
        return max(self.files) if self.files else 0

    def path(self, number: int) -> str:
        return self.files[number]

    def present_in(self, start: int, end: int) -> list[int]:
        return sorted(n for n in self.files if start <= n <= end)

    def missing_in(self, start: int, end: int) -> list[int]:
        if end < start:
            return []
        return [n for n in range(start, end + 1) if n not in self.files]


def scan_chapters(book_dir: str) -> ChapterIndex:
    """Map chapter numbers to files. Raises OSError if the folder cannot be read."""
    files, duplicates = {}, []
    # Shortest names first, so "Chapter 12.md" wins over "Chapter 12 - Title.md".
    for name in sorted(os.listdir(book_dir), key=lambda n: (len(n), n.lower())):
        match = _CHAPTER_FILE_RE.match(name)
        path = os.path.join(book_dir, name)
        if not match or not os.path.isfile(path):
            continue
        number = int(match.group(1))
        if number <= 0:
            continue
        if number in files:
            duplicates.append((number, path))
        else:
            files[number] = path
    duplicates.sort()
    return ChapterIndex(files=files, duplicates=tuple(duplicates))


def format_ranges(numbers) -> str:
    """Compress chapter numbers into text like '12, 40–42, … +3 more'."""
    nums = sorted(set(numbers))
    if not nums:
        return ""
    spans = []
    start = prev = nums[0]
    for num in nums[1:]:
        if num != prev + 1:
            spans.append((start, prev))
            start = num
        prev = num
    spans.append((start, prev))
    parts = [str(a) if a == b else f"{a}–{b}" for a, b in spans[:MAX_RANGES_SHOWN]]
    if len(spans) > MAX_RANGES_SHOWN:
        parts.append(f"… +{len(spans) - MAX_RANGES_SHOWN} more")
    return ", ".join(parts)
