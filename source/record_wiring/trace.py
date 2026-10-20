"""执行轨迹：确定性时间戳，结构化 JSONL，便于复跑比对。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


class TraceRecorder:
    def __init__(self, *, start_at: str = "2026-10-20T09:00:00Z", step_seconds: int = 1) -> None:
        self._clock = datetime.strptime(start_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self._step = timedelta(seconds=step_seconds)
        self._items: list[dict[str, Any]] = []

    def _at(self) -> str:
        return self._clock.strftime("%Y-%m-%dT%H:%M:%SZ")

    def record(self, event: str, **detail: Any) -> dict[str, Any]:
        item = {"seq": len(self._items) + 1, "at": self._at(), "event": event}
        item.update(detail)
        self._items.append(item)
        self._clock += self._step
        return item

    @property
    def items(self) -> list[dict[str, Any]]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def to_jsonl(self) -> str:
        if not self._items:
            return ""
        return "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in self._items) + "\n"

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_jsonl(), encoding="utf-8", newline="\n")

    @staticmethod
    def load(path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
