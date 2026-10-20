"""引用生成与解析：把来源指针变成可定位、可机器解析的引用。

引用 URI 形如：
  clawhunt://hr-system/samples/raw_records.jsonl?record_id=MR-2026-0001&version=1
    &hash=...&line=1&byte_offset=0&byte_length=420&body_offset=180&body_length=96

定位语义：
- line 是 1 起的行号；byte_offset/byte_length 是整行在源文件中的字节区间；
- body_offset/body_length 是「正文」在源文件中的字节区间；
- hash 是正文的 SHA-256。build 与 resolve 都会真的读文件切片并比对哈希。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

from .config import PROJECT_ROOT


class CitationError(ValueError):
    """引用无法解析或与源文件不一致。"""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_locator(source: Mapping[str, Any]) -> None:
    for key in ("source_file", "line_no", "byte_offset", "byte_length", "body_offset", "body_length"):
        if source.get(key) is None:
            raise CitationError(f"来源指针缺少定位字段: {key}")


def _safe_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CitationError(f"引用路径越界: {relative!r}") from exc
    if not candidate.is_file():
        raise CitationError(f"源文件不存在: {relative!r}")
    return candidate


def build_citation(record: Mapping[str, Any], *, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    source = record["source"]
    _require_locator(source)
    source_file = str(source["source_file"])
    path = _safe_path(root, source_file)
    raw = path.read_bytes()

    body_offset = int(source["body_offset"])
    body_length = int(source["body_length"])
    body_bytes = raw[body_offset : body_offset + body_length]
    digest = _sha256_bytes(body_bytes)
    if digest != str(source["hash"]):
        raise CitationError(
            f"{record.get('record_id')} 的正文切片哈希与来源指针不一致: {digest} != {source['hash']}"
        )

    line_offset = int(source["byte_offset"])
    line_length = int(source["byte_length"])
    line_bytes = raw[line_offset : line_offset + line_length]
    try:
        line_record = json.loads(line_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CitationError(f"行区间无法解析为源记录: {exc}") from exc
    if str(line_record.get("record_id")) != str(record["record_id"]):
        raise CitationError(
            f"行区间定位到 {line_record.get('record_id')!r}，与 {record['record_id']!r} 不一致"
        )

    params = {
        "record_id": record["record_id"],
        "version": record["version"],
        "hash": source["hash"],
        "line": source["line_no"],
        "byte_offset": source["byte_offset"],
        "byte_length": source["byte_length"],
        "body_offset": source["body_offset"],
        "body_length": source["body_length"],
    }
    uri = "clawhunt://{system}/{path}?{query}".format(
        system=source["system"],
        path=quote(source_file, safe="/"),
        query=urlencode(params),
    )
    return {
        "record_id": record["record_id"],
        "version": record["version"],
        "system": source["system"],
        "source_uri": source["uri"],
        "source_file": source_file,
        "hash": source["hash"],
        "line_no": source["line_no"],
        "byte_offset": source["byte_offset"],
        "byte_length": source["byte_length"],
        "body_offset": source["body_offset"],
        "body_length": source["body_length"],
        "slice_sha256": digest,
        "citation": uri,
        "human": (
            f"{source_file} 第 {source['line_no']} 行；正文字节区间 "
            f"{source['body_offset']}-{int(source['body_offset']) + int(source['body_length'])}；"
            f"sha256={source['hash']}"
        ),
    }


def resolve_citation(uri: str, *, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    parts = urlsplit(uri)
    if parts.scheme != "clawhunt":
        raise CitationError(f"引用 scheme 必须是 clawhunt: {uri!r}")
    if not parts.netloc:
        raise CitationError("引用缺少来源系统（netloc）")
    relative = unquote(parts.path.lstrip("/"))
    params = parse_qs(parts.query)
    for key in ("record_id", "hash", "line", "byte_offset", "byte_length", "body_offset", "body_length"):
        if key not in params:
            raise CitationError(f"引用缺少参数: {key}")
    path = _safe_path(root, relative)
    raw = path.read_bytes()

    line_offset = int(params["byte_offset"][0])
    line_length = int(params["byte_length"][0])
    try:
        line_record = json.loads(raw[line_offset : line_offset + line_length].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CitationError(f"行区间无法解析为源记录: {exc}") from exc
    if str(line_record.get("record_id")) != params["record_id"][0]:
        raise CitationError("引用行区间中的 record_id 与参数不一致")

    body_offset = int(params["body_offset"][0])
    body_length = int(params["body_length"][0])
    body_bytes = raw[body_offset : body_offset + body_length]
    digest = _sha256_bytes(body_bytes)
    expected_hash = params["hash"][0]
    if digest != expected_hash:
        raise CitationError("引用切片哈希与 hash 参数不一致")
    if body_bytes != str(line_record.get("body", "")).encode("utf-8"):
        raise CitationError("引用正文切片与源记录 body 字段不一致")
    line_no = int(params["line"][0])
    body_text = body_bytes.decode("utf-8")
    return {
        "system": parts.netloc,
        "source_file": relative,
        "record_id": params["record_id"][0],
        "hash": expected_hash,
        "line_no": line_no,
        "body_offset": body_offset,
        "body_length": body_length,
        "body": body_text,
    }


def write_citations(rows: Iterable[Mapping[str, Any]], path: Path, *, root: Path = PROJECT_ROOT) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            record = row.get("record", row)
            citation = build_citation(record, root=root)
            handle.write(json.dumps(citation, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_citations(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
