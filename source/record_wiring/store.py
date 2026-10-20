"""append-only 存储：只追加、不回写，带哈希链与版本保留。

每一行的结构：
  {"seq": 1, "chain_prev": "genesis", "chain_hash": "...", "record": {...}}

chain_hash = sha256(seq | chain_prev | record_id | version | raw_hash | redacted_body_hash)
因此任何历史行被改写、删除或调序，链校验都会失败。写入只使用 "a" 模式。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


GENESIS = "genesis"


class StoreError(ValueError):
    """存储层错误。"""


def _canonical(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def chain_hash(
    *,
    seq: int,
    prev: str,
    record_id: str,
    version: int,
    raw_hash: str,
    body_sha256: str,
) -> str:
    payload = _canonical(
        {
            "seq": seq,
            "prev": prev,
            "record_id": record_id,
            "version": version,
            "raw_hash": raw_hash,
            "body_sha256": body_sha256,
        }
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AppendOnlyStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_file()

    def rows(self) -> list[dict[str, Any]]:
        if not self.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise StoreError(f"存储第 {number} 行不是合法 JSON: {exc}") from exc
        return rows

    def records(self) -> list[dict[str, Any]]:
        return [row["record"] for row in self.rows()]

    def count(self) -> int:
        return len(self.rows())

    def append(self, record: Mapping[str, Any], *, raw_hash: str, body_sha256: str) -> dict[str, Any]:
        rows = self.rows()
        seq = (rows[-1]["seq"] + 1) if rows else 1
        prev = rows[-1]["chain_hash"] if rows else GENESIS
        record_id = str(record["record_id"])
        version = int(record["version"])
        digest = chain_hash(
            seq=seq,
            prev=prev,
            record_id=record_id,
            version=version,
            raw_hash=raw_hash,
            body_sha256=body_sha256,
        )
        row = {
            "seq": seq,
            "chain_prev": prev,
            "chain_hash": digest,
            "record": dict(record),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()
        return row

    def dedupe_keys(self) -> set[tuple[str, str]]:
        keys: set[tuple[str, str]] = set()
        for row in self.rows():
            record = row["record"]
            keys.add((str(record["record_id"]), str(record["source"]["hash"])))
        return keys

    def has_record(self, record_id: str, raw_hash: str) -> bool:
        return (record_id, raw_hash) in self.dedupe_keys()

    def max_version(self, record_id: str) -> int:
        versions = [
            int(row["record"]["version"])
            for row in self.rows()
            if str(row["record"]["record_id"]) == record_id
        ]
        return max(versions) if versions else 0

    def latest_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self.rows():
            record_id = str(row["record"]["record_id"])
            current = latest.get(record_id)
            if current is None or int(row["seq"]) > int(current["seq"]):
                latest[record_id] = row
        return [latest[key] for key in sorted(latest, key=lambda rid: int(latest[rid]["seq"]))]

    def integrity(self) -> dict[str, Any]:
        rows = self.rows()
        problems: list[str] = []
        prev = GENESIS
        for index, row in enumerate(rows, start=1):
            if int(row.get("seq", -1)) != index:
                problems.append(f"seq 不连续: 第 {index} 行 seq={row.get('seq')}")
            if row.get("chain_prev") != prev:
                problems.append(f"第 {index} 行 chain_prev 不匹配")
            record = row.get("record", {})
            expected = chain_hash(
                seq=int(row.get("seq", -1)),
                prev=str(row.get("chain_prev", "")),
                record_id=str(record.get("record_id", "")),
                version=int(record.get("version", 0)),
                raw_hash=str(record.get("source", {}).get("hash", "")),
                body_sha256=str(record.get("body_sha256", "")),
            )
            if expected != row.get("chain_hash"):
                problems.append(f"第 {index} 行 chain_hash 校验失败")
            prev = str(row.get("chain_hash", ""))
        return {"ok": not problems, "rows": len(rows), "head": prev, "problems": problems}


def row_records(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row["record"] for row in rows]
