from __future__ import annotations

from pathlib import Path


class LogTailer:
    def __init__(self, path: Path, start_at_end: bool = True) -> None:
        self.path = Path(path)
        self.position = self.path.stat().st_size if start_at_end and self.path.exists() else 0

    def read_available(self) -> list[str]:
        if not self.path.exists():
            return []

        file_size = self.path.stat().st_size
        if file_size < self.position:
            self.position = 0

        with self.path.open(encoding="utf-8", errors="replace") as handle:
            handle.seek(self.position)
            lines = handle.readlines()
            self.position = handle.tell()

        return lines
