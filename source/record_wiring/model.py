"""领域模型：管理记录、来源指针、访问标签。

设计要点：
- 来源指针是可解析指针，不是自由文本备注：system + uri + record_id + hash。
- hash 是「原始记录正文」的 SHA-256（UTF-8 字节），与存储层是否脱敏无关。
- 定位信息（源文件、行号、字节区间）由导入器在读取源文件时计算，不手工填写。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping


class ModelError(ValueError):
    """模型层错误（字段缺失、类型不符等）。"""


def sha256_text(text: str) -> str:
    """对文本按 UTF-8 计算 SHA-256 十六进制摘要。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require(data: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in data:
        raise ModelError(f"{where} 缺少字段 {key}")
    return data[key]


@dataclass(frozen=True)
class AccessTag:
    """记录的访问权限标签。

    labels      记录所属标签集合，检索/导出时按标签做子集判断。
    owner_role  记录的业务归属角色（用于审计，不直接授予读取权）。
    sensitivity 敏感级别 low / medium / high。
    """

    labels: tuple[str, ...]
    owner_role: str
    sensitivity: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AccessTag":
        labels = _require(data, "labels", "access")
        if not isinstance(labels, (list, tuple)):
            raise ModelError("access.labels 必须是字符串数组")
        clean = tuple(str(x) for x in labels)
        if not clean:
            raise ModelError("access.labels 不能为空：每条记录必须带访问权限标签")
        if len(set(clean)) != len(clean):
            raise ModelError("access.labels 存在重复标签")
        return cls(
            labels=clean,
            owner_role=str(_require(data, "owner_role", "access")),
            sensitivity=str(_require(data, "sensitivity", "access")),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "labels": list(self.labels),
            "owner_role": self.owner_role,
            "sensitivity": self.sensitivity,
        }


@dataclass(frozen=True)
class SourcePointer:
    """可解析的来源指针。

    system / uri / record_id / hash 是必填核心字段；captured_at 为采集时间。
    其余 locator 字段由导入器回填：source_file 相对路径、line_no（1 起）、
    byte_offset/byte_length（整行字节区间）、body_offset/body_length（正文在源文件中的字节区间）。
    """

    system: str
    uri: str
    record_id: str
    hash: str
    captured_at: str
    source_file: str | None = None
    line_no: int | None = None
    byte_offset: int | None = None
    byte_length: int | None = None
    body_offset: int | None = None
    body_length: int | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourcePointer":
        return cls(
            system=str(_require(data, "system", "source")),
            uri=str(_require(data, "uri", "source")),
            record_id=str(_require(data, "record_id", "source")),
            hash=str(_require(data, "hash", "source")),
            captured_at=str(_require(data, "captured_at", "source")),
            source_file=data.get("source_file"),
            line_no=data.get("line_no"),
            byte_offset=data.get("byte_offset"),
            byte_length=data.get("byte_length"),
            body_offset=data.get("body_offset"),
            body_length=data.get("body_length"),
        )

    def with_locator(
        self,
        *,
        source_file: str,
        line_no: int,
        byte_offset: int,
        byte_length: int,
        body_offset: int,
        body_length: int,
    ) -> "SourcePointer":
        return SourcePointer(
            system=self.system,
            uri=self.uri,
            record_id=self.record_id,
            hash=self.hash,
            captured_at=self.captured_at,
            source_file=source_file,
            line_no=line_no,
            byte_offset=byte_offset,
            byte_length=byte_length,
            body_offset=body_offset,
            body_length=body_length,
        )

    def has_locator(self) -> bool:
        return all(
            value is not None
            for value in (self.source_file, self.line_no, self.byte_offset, self.body_offset, self.body_length)
        )

    def dedupe_key(self) -> tuple[str, str]:
        return (self.record_id, self.hash)

    def as_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "system": self.system,
            "uri": self.uri,
            "record_id": self.record_id,
            "hash": self.hash,
            "captured_at": self.captured_at,
        }
        for key in (
            "source_file",
            "line_no",
            "byte_offset",
            "byte_length",
            "body_offset",
            "body_length",
        ):
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data


@dataclass(frozen=True)
class Record:
    """一条管理记录（原始形态，body 尚未脱敏）。"""

    record_id: str
    version: int
    record_type: str
    title: str
    body: str
    department: str
    occurred_at: str
    received_at: str
    source: SourcePointer
    access: AccessTag

    @property
    def body_hash(self) -> str:
        return sha256_text(self.body)

    def dedupe_key(self) -> tuple[str, str]:
        return self.source.dedupe_key()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Record":
        try:
            version = int(_require(data, "version", "record"))
        except (TypeError, ValueError) as exc:
            raise ModelError("record.version 必须是整数") from exc
        return cls(
            record_id=str(_require(data, "record_id", "record")),
            version=version,
            record_type=str(_require(data, "record_type", "record")),
            title=str(_require(data, "title", "record")),
            body=str(_require(data, "body", "record")),
            department=str(_require(data, "department", "record")),
            occurred_at=str(_require(data, "occurred_at", "record")),
            received_at=str(_require(data, "received_at", "record")),
            source=SourcePointer.from_dict(_require(data, "source", "record")),
            access=AccessTag.from_dict(_require(data, "access", "record")),
        )

    def as_dict(self, *, include_locator: bool = False) -> dict[str, Any]:
        source = self.source
        if not include_locator:
            source = SourcePointer(
                system=source.system,
                uri=source.uri,
                record_id=source.record_id,
                hash=source.hash,
                captured_at=source.captured_at,
            )
        return {
            "record_id": self.record_id,
            "version": self.version,
            "record_type": self.record_type,
            "title": self.title,
            "body": self.body,
            "department": self.department,
            "occurred_at": self.occurred_at,
            "received_at": self.received_at,
            "source": source.as_dict(),
            "access": self.access.as_dict(),
        }
