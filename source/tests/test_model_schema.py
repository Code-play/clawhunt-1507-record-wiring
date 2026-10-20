"""模型与 Schema 校验测试。"""

from __future__ import annotations

from dataclasses import replace

from tests.helpers import objects, raw_record
from record_wiring.model import AccessTag, SourcePointer
from record_wiring.schema import SchemaError


def test_source_pointer_roundtrip() -> None:
    pointer = SourcePointer(
        system="wiki",
        uri="wiki://records/MR-2026-0001",
        record_id="MR-2026-0001",
        hash="a" * 64,
        captured_at="2026-03-02T10:15:00Z",
        source_file="samples/raw_records.jsonl",
        line_no=1,
        byte_offset=0,
        byte_length=100,
        body_offset=10,
        body_length=80,
    )
    again = SourcePointer.from_dict(pointer.as_dict())
    assert again == pointer
    assert again.has_locator()
    assert again.dedupe_key() == ("MR-2026-0001", "a" * 64)


def test_record_hash_matches_body() -> None:
    record = raw_record(0)
    assert record.source.hash == record.body_hash
    assert len(record.body_hash) == 64


def test_schema_accepts_valid_record() -> None:
    schema, _privacy, policy = objects()
    record = raw_record(0)
    schema.validate(record, allowed_labels=policy.label_names(), allowed_roles=policy.role_names())
    assert record.access.labels == ("internal", "finance")


def test_schema_rejects_missing_access_labels() -> None:
    schema, _privacy, policy = objects()
    record = replace(
        raw_record(0),
        access=AccessTag(labels=(), owner_role="analyst", sensitivity="low"),
    )
    try:
        schema.validate(record, allowed_labels=policy.label_names(), allowed_roles=policy.role_names())
    except SchemaError as exc:
        assert exc.code == "access.labels"
    else:
        raise AssertionError("缺少访问标签必须被拒绝")


def test_schema_rejects_hash_mismatch() -> None:
    schema, _privacy, policy = objects()
    record = raw_record(0)
    bad = replace(record, body=record.body + "篡改")
    try:
        schema.validate(bad, allowed_labels=policy.label_names(), allowed_roles=policy.role_names())
    except SchemaError as exc:
        assert exc.code == "source.hash"
    else:
        raise AssertionError("正文被改写后 hash 不一致必须被拒绝")


def test_schema_rejects_bad_record_id() -> None:
    schema, _privacy, policy = objects()
    record = raw_record(0)
    bad = replace(
        record,
        record_id="BAD-ID",
        source=replace(record.source, record_id="BAD-ID"),
    )
    try:
        schema.validate(bad, allowed_labels=policy.label_names(), allowed_roles=policy.role_names())
    except SchemaError as exc:
        assert exc.code == "record_id"
    else:
        raise AssertionError("非法 record_id 必须被拒绝")


def test_source_record_id_must_match() -> None:
    schema, _privacy, policy = objects()
    record = raw_record(0)
    bad = replace(record, source=replace(record.source, record_id="MR-2026-9999"))
    try:
        schema.validate(bad, allowed_labels=policy.label_names(), allowed_roles=policy.role_names())
    except SchemaError as exc:
        assert exc.code == "source.record_id"
    else:
        raise AssertionError("source.record_id 与 record_id 不一致必须被拒绝")
