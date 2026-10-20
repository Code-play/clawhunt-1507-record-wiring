"""Schema 校验：必填字段、类型、时间、来源指针与访问标签。

校验器只读取 config/records_schema.json 与访问策略标签集合，不在代码里硬编码业务枚举。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping

from .model import Record, sha256_text

_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class SchemaError(ValueError):
    """记录不满足 Schema。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


def parse_timestamp(value: str) -> datetime:
    if not _TIMESTAMP_RE.match(value):
        raise SchemaError("timestamp_format", f"时间必须是 UTC ISO-8601（YYYY-MM-DDTHH:MM:SSZ）: {value!r}")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise SchemaError("timestamp_value", f"非法时间: {value!r}") from exc


@dataclass(frozen=True)
class Schema:
    data: Mapping[str, Any]

    @property
    def schema_id(self) -> str:
        return str(self.data["schema_id"])

    @property
    def record_id_pattern(self) -> re.Pattern[str]:
        return re.compile(str(self.data["record_id_pattern"]))

    @property
    def hash_pattern(self) -> re.Pattern[str]:
        return re.compile(str(self.data["hash_pattern"]))

    def validate(
        self,
        record: Record,
        *,
        allowed_labels: Iterable[str] | None = None,
        allowed_roles: Iterable[str] | None = None,
    ) -> None:
        data = self.data
        if not self.record_id_pattern.match(record.record_id):
            raise SchemaError("record_id", f"record_id 不符合格式: {record.record_id!r}")
        if record.version < 1:
            raise SchemaError("version", "version 必须 >= 1")
        if record.record_type not in data["record_types"]:
            raise SchemaError("record_type", f"未登记的记录类型: {record.record_type!r}")
        if not record.title.strip():
            raise SchemaError("title", "title 不能为空")
        if len(record.title) > int(data.get("max_title_length", 120)):
            raise SchemaError("title", "title 超出长度上限")
        if len(record.body.strip()) < int(data.get("min_body_length", 10)):
            raise SchemaError("body", "body 过短")
        if not record.department.strip():
            raise SchemaError("department", "department 不能为空")

        occurred = parse_timestamp(record.occurred_at)
        received = parse_timestamp(record.received_at)
        if received < occurred:
            raise SchemaError("received_at", "received_at 不能早于 occurred_at")
        parse_timestamp(record.source.captured_at)

        source = record.source
        if source.system not in data["source_systems"]:
            raise SchemaError("source.system", f"未登记的来源系统: {source.system!r}")
        if not source.uri.strip() or "://" not in source.uri:
            raise SchemaError("source.uri", f"来源 URI 必须是可解析 URI: {source.uri!r}")
        if source.record_id != record.record_id:
            raise SchemaError("source.record_id", "source.record_id 必须与 record_id 一致")
        if not self.hash_pattern.match(source.hash):
            raise SchemaError("source.hash", "source.hash 必须是 64 位小写十六进制")
        if source.hash != sha256_text(record.body):
            raise SchemaError("source.hash", "source.hash 与正文 SHA-256 不一致，来源指针不可信")

        access = record.access
        if not access.labels:
            raise SchemaError("access.labels", "每条记录必须带访问权限标签")
        if access.sensitivity not in data["sensitivity_levels"]:
            raise SchemaError("access.sensitivity", f"未知敏感级别: {access.sensitivity!r}")
        labels = set(allowed_labels or data.get("known_labels", []))
        if labels:
            unknown = sorted(set(access.labels) - labels)
            if unknown:
                raise SchemaError("access.labels", f"未登记的访问标签: {unknown}")
        if allowed_roles is not None and access.owner_role not in set(allowed_roles):
            raise SchemaError("access.owner_role", f"未登记的角色: {access.owner_role!r}")

    def validate_dict(
        self,
        data: Mapping[str, Any],
        *,
        allowed_labels: Iterable[str] | None = None,
        allowed_roles: Iterable[str] | None = None,
    ) -> Record:
        record = Record.from_dict(data)
        self.validate(record, allowed_labels=allowed_labels, allowed_roles=allowed_roles)
        return record


def load_schema(data: Mapping[str, Any]) -> Schema:
    return Schema(data=data)
