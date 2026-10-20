"""幂等导入：校验 -> 计算定位 -> 脱敏 -> 去重/版本判定 -> append-only 落盘。

幂等键： (record_id, source.hash)。同一 record_id + hash 重复导入不会新增行；
同一 record_id 的新正文会作为新版本追加，历史版本保持原样。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .access import AccessPolicy
from .config import DEFAULT_INGEST_AT, PROJECT_ROOT
from .model import ModelError, Record, sha256_text
from .privacy import PrivacyEngine
from .schema import Schema, SchemaError
from .store import AppendOnlyStore
from .trace import TraceRecorder


@dataclass
class IngestReport:
    input_file: str
    total_lines: int = 0
    added: int = 0
    skipped_duplicate: int = 0
    version_bumped: int = 0
    rejected: int = 0
    stored_rows: int = 0
    redaction_records: int = 0
    redaction_findings: int = 0
    rejections: list[dict[str, Any]] = field(default_factory=list)
    version_notes: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "input_file": self.input_file,
            "total_lines": self.total_lines,
            "added": self.added,
            "skipped_duplicate": self.skipped_duplicate,
            "version_bumped": self.version_bumped,
            "rejected": self.rejected,
            "stored_rows": self.stored_rows,
            "redaction_records": self.redaction_records,
            "redaction_findings": self.redaction_findings,
        }


class Ingestor:
    def __init__(
        self,
        store: AppendOnlyStore,
        schema: Schema,
        privacy: PrivacyEngine,
        policy: AccessPolicy,
        *,
        trace: TraceRecorder | None = None,
        ingest_at: str = DEFAULT_INGEST_AT,
    ) -> None:
        self.store = store
        self.schema = schema
        self.privacy = privacy
        self.policy = policy
        self.trace = trace
        self.ingest_at = ingest_at

    def _trace(self, event: str, **detail: Any) -> None:
        if self.trace is not None:
            self.trace.record(event, **detail)

    def ingest_file(self, path: Path) -> IngestReport:
        raw = path.read_bytes()
        try:
            source_file = path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
        except ValueError:
            source_file = path.name
        return self.ingest_bytes(raw, source_file=source_file)

    def ingest_bytes(self, raw: bytes, *, source_file: str) -> IngestReport:
        report = IngestReport(input_file=source_file)
        lines = raw.splitlines(keepends=True)
        existing = self.store.records()
        keys = {(str(item["record_id"]), str(item["source"]["hash"])) for item in existing}
        max_versions: dict[str, int] = {}
        for item in existing:
            rid = str(item["record_id"])
            max_versions[rid] = max(max_versions.get(rid, 0), int(item["version"]))

        byte_offset = 0
        for line_no, line_bytes in enumerate(lines, start=1):
            line_length = len(line_bytes)
            text = line_bytes.decode("utf-8", errors="replace").strip()
            if not text:
                byte_offset += line_length
                continue
            report.total_lines += 1
            try:
                data = json.loads(text)
            except json.JSONDecodeError as exc:
                self._reject(report, line_no, "", "json", f"JSON 解析失败: {exc}")
                byte_offset += line_length
                continue

            try:
                record = Record.from_dict(data)
            except (ModelError, TypeError, ValueError) as exc:
                self._reject(report, line_no, str(data.get("record_id", "")), "model", str(exc))
                byte_offset += line_length
                continue

            try:
                self.schema.validate(
                    record,
                    allowed_labels=self.policy.label_names(),
                    allowed_roles=self.policy.role_names(),
                )
            except SchemaError as exc:
                self._reject(report, line_no, record.record_id, exc.code, exc.message)
                byte_offset += line_length
                continue

            body_bytes = record.body.encode("utf-8")
            body_index = line_bytes.find(body_bytes)
            if body_index < 0:
                self._reject(report, line_no, record.record_id, "locator", "无法在源文件中定位正文字节")
                byte_offset += line_length
                continue

            source = record.source.with_locator(
                source_file=source_file,
                line_no=line_no,
                byte_offset=byte_offset,
                byte_length=line_length,
                body_offset=byte_offset + body_index,
                body_length=len(body_bytes),
            )
            redacted_body, findings = self.privacy.redact(record.body)
            if findings:
                report.redaction_records += 1
                report.redaction_findings += len(findings)

            key = (record.record_id, record.source.hash)
            if key in keys:
                report.skipped_duplicate += 1
                self._trace(
                    "ingest_skip",
                    line=line_no,
                    record_id=record.record_id,
                    reason="duplicate_record_id_and_hash",
                )
                byte_offset += line_length
                continue

            version = record.version
            max_version = max_versions.get(record.record_id, 0)
            if version <= max_version:
                version = max_version + 1
                report.version_bumped += 1
                note = {
                    "record_id": record.record_id,
                    "incoming_version": record.version,
                    "stored_version": version,
                }
                report.version_notes.append(note)
                self._trace("ingest_version_bump", line=line_no, **note)

            stored = record.as_dict()
            stored["version"] = version
            stored["body"] = redacted_body
            stored["source"] = source.as_dict()
            stored["body_sha256"] = sha256_text(redacted_body)
            stored["raw_body_sha256"] = record.source.hash
            stored["ingested_at"] = self.ingest_at
            stored["redaction"] = {
                "engine": self.privacy.rules_id,
                "engine_version": self.privacy.version,
                "field": "body",
                "count": len(findings),
                "rules": self.privacy.rule_summary(findings),
                "before_length": len(record.body),
                "after_length": len(redacted_body),
            }

            self.store.append(stored, raw_hash=record.source.hash, body_sha256=stored["body_sha256"])
            keys.add(key)
            max_versions[record.record_id] = version
            report.added += 1
            self._trace(
                "ingest_append",
                line=line_no,
                record_id=record.record_id,
                version=version,
                labels=list(record.access.labels),
                redactions=len(findings),
            )
            byte_offset += line_length

        report.stored_rows = self.store.count()
        self._trace("ingest_done", **report.summary())
        return report

    def _reject(self, report: IngestReport, line_no: int, record_id: str, code: str, message: str) -> None:
        report.rejected += 1
        item = {"line_no": line_no, "record_id": record_id, "code": code, "message": message}
        report.rejections.append(item)
        self._trace("ingest_reject", **item)


def ingest_path(
    input_path: Path,
    store_path: Path,
    *,
    schema: Schema,
    privacy: PrivacyEngine,
    policy: AccessPolicy,
    trace: TraceRecorder | None = None,
    ingest_at: str = DEFAULT_INGEST_AT,
) -> tuple[IngestReport, AppendOnlyStore]:
    store = AppendOnlyStore(store_path)
    ingestor = Ingestor(store, schema, privacy, policy, trace=trace, ingest_at=ingest_at)
    report = ingestor.ingest_file(input_path)
    return report, store
