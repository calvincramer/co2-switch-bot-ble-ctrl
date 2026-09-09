#!/usr/bin/env python3

"""
Shared CSV log for co2Adv.py and co2Hist.py.

Both scripts write the same file, often at the same time, so every write goes
through here. The invariants held by every function below:

- one row per point in time, the newest write for that instant wins
- rows sorted oldest to newest
- an existing file is merged into, never truncated or duplicated

Timestamps are compared as instants, not as text, so the same moment written
with different UTC offsets (say, across a DST change) is still one row.
"""

from __future__ import annotations

import csv
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

CSV_COLUMNS = ["ts", "temp_c", "humidity_percent", "co2_ppm"]

Row = dict[str, object]

try:
    import fcntl
except ImportError:  # not Linux, so run unlocked and hope for the best
    fcntl = None  # type: ignore[assignment]


def normalize(row: Row) -> dict[str, str]:
    """A row as it will look on disk, so rows can be compared for equality."""
    return {column: "" if row.get(column) is None else str(row[column]) for column in CSV_COLUMNS}


def parse_timestamp(text: str) -> datetime:
    """The instant a row's `ts` column refers to. Naive times are read as local."""
    stamp = datetime.fromisoformat(text.strip())
    return stamp if stamp.tzinfo is not None else stamp.astimezone()


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    """Hold a lock on `path`, so the other script cannot write between our read and write.

    The lock lives in a sibling file: the log itself gets replaced during a
    merge, and a lock on a replaced inode holds nothing back.
    """
    if fcntl is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path.with_name(path.name + ".lock"), "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def read_rows(path: Path) -> dict[datetime, Row]:
    """Existing rows keyed by instant. Missing file means no rows."""
    if not path.exists() or path.stat().st_size == 0:
        return {}
    rows: dict[datetime, Row] = {}
    with path.open(newline="") as handle:
        for line_number, row in enumerate(csv.DictReader(handle), start=2):
            text = row.get("ts")
            if not text:
                raise ValueError(f"{path}:{line_number} has no ts column")
            try:
                stamp = parse_timestamp(text)
            except ValueError as error:
                raise ValueError(f"{path}:{line_number} has an unreadable ts {text!r}") from error
            rows[stamp] = {column: row.get(column, "") for column in CSV_COLUMNS}
    return rows


def _write_all(path: Path, rows: dict[datetime, Row]) -> None:
    """Replace `path` with `rows` in time order, atomically."""
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows[stamp] for stamp in sorted(rows))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def merge(path: Path, new_rows: Iterable[Row]) -> tuple[int, int]:
    """Fold `new_rows` into the log at `path`. Returns (added, replaced) counts.

    A new row wins over an existing row for the same instant: a re-download of
    history should refresh what is on disk rather than be dropped as a duplicate.
    """
    with _exclusive(path):
        existing = read_rows(path)
        added = replaced = 0
        for new_row in new_rows:
            row = normalize(new_row)
            stamp = parse_timestamp(row["ts"])
            if stamp not in existing:
                added += 1
            elif existing[stamp] != row:
                replaced += 1
            existing[stamp] = row
        _write_all(path, existing)
    return added, replaced


class CsvLog:
    """Row-at-a-time writer for the live monitor.

    A reading is normally newer than everything on disk, which is a plain
    append. When it is not, because the log already holds later rows from a
    history download, it falls back to a full merge so the file stays sorted.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._stamps: set[datetime] = set()
        self._newest: datetime | None = None
        self._state: tuple[int, int] | None = None
        with _exclusive(self.path):
            if not self.path.exists() or self.path.stat().st_size == 0:
                _write_all(self.path, {})
            self._reload()

    def _fingerprint(self) -> tuple[int, int]:
        stat = self.path.stat()
        return (stat.st_mtime_ns, stat.st_size)

    def _reload(self) -> None:
        self._stamps = set(read_rows(self.path))
        self._newest = max(self._stamps, default=None)
        self._state = self._fingerprint()

    def add(self, new_row: Row) -> bool:
        """Record one reading. False means the log already had that instant."""
        row = normalize(new_row)
        stamp = parse_timestamp(row["ts"])
        with _exclusive(self.path):
            if self._state != self._fingerprint():
                self._reload()  # the other script wrote since we last looked
            if stamp in self._stamps:
                return False
            if self._newest is not None and stamp < self._newest:
                rows = read_rows(self.path)
                rows[stamp] = row
                _write_all(self.path, rows)
            else:
                with self.path.open("a", newline="") as handle:
                    csv.DictWriter(handle, fieldnames=CSV_COLUMNS).writerow(row)
                    handle.flush()
                self._newest = stamp
            self._stamps.add(stamp)
            self._state = self._fingerprint()
        return True
