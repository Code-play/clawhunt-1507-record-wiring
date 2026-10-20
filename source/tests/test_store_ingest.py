"""append-only 存储与幂等导入测试。"""

from __future__ import annotations

import hashlib
import json

from tests.helpers import SAMPLES_FILE, ingested, objects, raw_lines
from record_wiring.ingest import Ingestor


def test_ingest_counts() -> None:
    with ingested("counts") as ctx:
        report = ctx["report"]
        assert report.total_lines == 24
        assert report.added == 23
        assert report.skipped_duplicate == 1
        assert report.version_bumped == 0
        assert report.rejected == 0
        assert report.stored_rows == 23


def test_duplicate_key_is_record_id_plus_hash() -> None:
    lines = raw_lines()
    keys = [(item["record_id"], item["source"]["hash"]) for item in lines]
    assert len(keys) == 24
    assert len(set(keys)) == 23
    assert keys[2] == keys[3]


def test_second_import_adds_zero_rows() -> None:
    with ingested("idempotent") as ctx:
        store = ctx["store"]
        before = store.count()
        schema, privacy, policy = objects()
        ingestor = Ingestor(store, schema, privacy, policy)
        report = ingestor.ingest_file(SAMPLES_FILE)
        assert report.added == 0
        assert report.skipped_duplicate == 24
        assert store.count() == before == 23


def test_store_bytes_unchanged_after_reimport() -> None:
    with ingested("bytes") as ctx:
        store = ctx["store"]
        before = store.path.read_bytes()
        schema, privacy, policy = objects()
        report = Ingestor(store, schema, privacy, policy).ingest_file(SAMPLES_FILE)
        after = store.path.read_bytes()
        assert report.added == 0
        assert hashlib.sha256(before).hexdigest() == hashlib.sha256(after).hexdigest()
        assert after.startswith(before)


def test_versions_are_appended_not_rewritten() -> None:
    with ingested("versions") as ctx:
        rows = ctx["rows"]
        versions = [row["record"] for row in rows if row["record"]["record_id"] == "MR-2026-0010"]
        assert [item["version"] for item in versions] == [1, 2]
        assert versions[0]["body"] != versions[1]["body"]
        assert versions[0]["source"]["hash"] != versions[1]["source"]["hash"]


def test_chain_integrity() -> None:
    with ingested("chain") as ctx:
        result = ctx["store"].integrity()
        assert result["ok"] is True
        assert result["rows"] == 23
        assert result["problems"] == []
        rows = ctx["store"].rows()
        assert rows[0]["chain_prev"] == "genesis"
        assert all(rows[i]["chain_prev"] == rows[i - 1]["chain_hash"] for i in range(1, len(rows)))


def test_invalid_record_is_rejected_and_not_stored() -> None:
    with ingested("reject") as ctx:
        store = ctx["store"]
        bad = json.loads(json.dumps(raw_lines()[0]))
        bad["source"]["hash"] = "0" * 64
        path = ctx["base"] / "bad.jsonl"
        path.write_text(json.dumps(bad, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        schema, privacy, policy = objects()
        before = store.count()
        report = Ingestor(store, schema, privacy, policy).ingest_file(path)
        assert report.rejected == 1
        assert report.added == 0
        assert store.count() == before
        assert report.rejections[0]["code"] == "source.hash"


def test_append_only_rows_never_modified() -> None:
    with ingested("appendonly") as ctx:
        path = ctx["store"].path
        first = path.read_bytes().splitlines(keepends=True)
        schema, privacy, policy = objects()
        Ingestor(ctx["store"], schema, privacy, policy).ingest_file(SAMPLES_FILE)
        second = path.read_bytes().splitlines(keepends=True)
        assert len(second) == len(first)
        assert all(second[index] == line for index, line in enumerate(first))
