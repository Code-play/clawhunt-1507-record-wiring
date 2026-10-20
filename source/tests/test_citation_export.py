"""引用定位与导出渲染测试。"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tests.helpers import ROOT, ingested
from record_wiring.citation import build_citation, resolve_citation
from record_wiring.export import render_import_report, render_redaction_diff


def test_citation_uri_is_parseable() -> None:
    with ingested("cite_parse") as ctx:
        citation = build_citation(ctx["rows"][0]["record"])
        parts = urlsplit(citation["citation"])
        params = parse_qs(parts.query)
        assert parts.scheme == "clawhunt"
        assert parts.netloc == citation["system"]
        assert params["record_id"] == [citation["record_id"]]
        assert params["hash"] == [citation["hash"]]
        assert params["line"] == [str(citation["line_no"])]


def test_citation_slice_matches_hash() -> None:
    with ingested("cite_slice") as ctx:
        record = ctx["rows"][0]["record"]
        citation = build_citation(record)
        resolved = resolve_citation(citation["citation"])
        assert resolved["body"] != record["body"]
        assert "[NAME:" in record["body"]
        assert resolved["hash"] == record["source"]["hash"]
        raw = (ROOT / resolved["source_file"]).read_bytes()
        chunk = raw[resolved["body_offset"] : resolved["body_offset"] + resolved["body_length"]]
        assert chunk.decode("utf-8") == resolved["body"]
        assert citation["slice_sha256"] == record["source"]["hash"]


def test_every_stored_record_citation_resolves() -> None:
    with ingested("cite_all") as ctx:
        for row in ctx["rows"]:
            citation = build_citation(row["record"])
            resolved = resolve_citation(citation["citation"])
            assert resolved["record_id"] == row["record"]["record_id"]
            assert resolved["line_no"] == row["record"]["source"]["line_no"]


def test_body_offset_is_inside_line_range() -> None:
    with ingested("cite_offsets") as ctx:
        for row in ctx["rows"]:
            source = row["record"]["source"]
            assert source["byte_offset"] <= source["body_offset"]
            assert source["body_offset"] + source["body_length"] <= source["byte_offset"] + source["byte_length"]


def test_import_report_contains_stats() -> None:
    with ingested("report") as ctx:
        text = render_import_report(ctx["report"], ctx["rows"])
        assert "总行数：24" in text
        assert "新增行数：23" in text
        assert "去重跳过：1" in text
        assert "校验拒绝：0" in text


def test_redaction_diff_has_at_least_eight_rows() -> None:
    with ingested("diff") as ctx:
        text = render_redaction_diff(ctx["rows"])
        rows = [line for line in text.splitlines() if line.startswith("| ") and "MR-2026-" in line]
        assert len(rows) >= 8
        assert "脱敏前（原文）" in text
        assert "脱敏后（导入产物）" in text
        for line in rows:
            cells = line.split("|")
            assert cells[5].strip() != cells[6].strip()
