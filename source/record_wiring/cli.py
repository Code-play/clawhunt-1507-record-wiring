"""命令行入口：demo / ingest / query / export / cite / integrity。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .access import AccessController, load_policy
from .citation import build_citation, read_citations, resolve_citation
from .config import (
    DEFAULT_INGEST_AT,
    OUT_DIR,
    PROJECT_ROOT,
    SAMPLES_FILE,
    STORE_FILE,
    load_access_policy,
    load_privacy_rules,
    load_records_schema,
)
from .export import (
    export_for_role,
    record_view,
    render_import_report,
    render_redaction_diff,
    write_jsonl,
)
from .ingest import Ingestor
from .privacy import load_engine
from .schema import load_schema
from .store import AppendOnlyStore
from .trace import TraceRecorder


def _objects():
    schema = load_schema(load_records_schema())
    privacy = load_engine(load_privacy_rules())
    policy = load_policy(load_access_policy())
    return schema, privacy, policy


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_demo(args: argparse.Namespace) -> int:
    schema, privacy, policy = _objects()
    store_path = Path(args.store)
    if store_path.exists():
        store_path.unlink()
    store = AppendOnlyStore(store_path)
    trace = TraceRecorder()
    ingestor = Ingestor(store, schema, privacy, policy, trace=trace, ingest_at=DEFAULT_INGEST_AT)
    report = ingestor.ingest_file(Path(args.input))
    rows = store.rows()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "records_imported.jsonl", record_view(rows))
    (out_dir / "import_report.md").write_text(
        render_import_report(report, rows), encoding="utf-8", newline="\n"
    )
    (out_dir / "redaction_diff.md").write_text(
        render_redaction_diff(rows), encoding="utf-8", newline="\n"
    )

    citations = 0
    with (out_dir / "citations.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            citation = build_citation(row["record"])
            resolve_citation(citation["citation"])
            handle.write(json.dumps(citation, ensure_ascii=False, sort_keys=True) + "\n")
            citations += 1

    controller = AccessController(policy)
    role_counts: dict[str, int] = {}
    analyst_export: list[dict[str, Any]] = []
    for role in policy.role_names():
        exported, _decisions = export_for_role(rows, controller, role)
        role_counts[role] = len(exported)
        if role == "analyst":
            analyst_export = exported
        trace.record("access_export", role=role, visible=len(exported), total=len(rows))
    write_jsonl(out_dir / "export_analyst.jsonl", analyst_export)
    write_jsonl(out_dir / "access_log.jsonl", controller.decisions)
    trace.write(out_dir / "trace.jsonl")

    integrity = store.integrity()
    print("订单 #1507 管理记录知识接线 - demo")
    print(f"输入: {report.input_file}")
    print(
        "总行数={total} 新增={added} 去重跳过={skipped} 版本提升={bumped} 拒绝={rejected}".format(
            total=report.total_lines,
            added=report.added,
            skipped=report.skipped_duplicate,
            bumped=report.version_bumped,
            rejected=report.rejected,
        )
    )
    print(
        f"存储行数={report.stored_rows} 脱敏记录={report.redaction_records} 脱敏命中={report.redaction_findings}"
    )
    print(f"引用={citations} 可定位={citations} 链校验={'通过' if integrity['ok'] else '失败'}")
    print("角色可见: " + " ".join(f"{role}={role_counts[role]}" for role in policy.role_names()))
    print(
        "产物: out/records_imported.jsonl out/import_report.md "
        "out/redaction_diff.md out/citations.jsonl out/access_log.jsonl out/trace.jsonl"
    )
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    schema, privacy, policy = _objects()
    trace = TraceRecorder() if args.trace else None
    store = AppendOnlyStore(Path(args.store))
    ingestor = Ingestor(store, schema, privacy, policy, trace=trace, ingest_at=args.now)
    report = ingestor.ingest_file(Path(args.input))
    if trace is not None and args.trace:
        trace.write(Path(args.trace))
    _print_json(report.summary())
    if report.rejections:
        _print_json({"rejections": report.rejections})
    return 0 if report.rejected == 0 else 2


def cmd_query(args: argparse.Namespace) -> int:
    _schema, _privacy, policy = _objects()
    store = AppendOnlyStore(Path(args.store))
    rows = store.rows()
    controller = AccessController(policy)
    visible: list[dict[str, Any]] = []
    denied = 0
    for row in rows:
        record = row["record"]
        decision = controller.decide(record, args.role)
        if not decision["allowed"]:
            denied += 1
            continue
        if args.record_type and record["record_type"] != args.record_type:
            continue
        if args.label and args.label not in record["access"]["labels"]:
            continue
        visible.append(
            {
                "record_id": record["record_id"],
                "version": record["version"],
                "record_type": record["record_type"],
                "title": record["title"],
                "labels": record["access"]["labels"],
                "source": f"{record['source']['source_file']}:{record['source']['line_no']}",
            }
        )
    _print_json({"role": args.role, "visible": len(visible), "denied": denied, "records": visible})
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    _schema, _privacy, policy = _objects()
    store = AppendOnlyStore(Path(args.store))
    rows = store.rows()
    controller = AccessController(policy)
    exported, decisions = export_for_role(rows, controller, args.role)
    write_jsonl(Path(args.out), exported)
    denied = [item for item in decisions if not item["allowed"]]
    _print_json(
        {
            "role": args.role,
            "exported": len(exported),
            "denied": len(denied),
            "out": str(args.out),
        }
    )
    return 0


def cmd_cite(args: argparse.Namespace) -> int:
    store = AppendOnlyStore(Path(args.store))
    rows = store.rows()
    candidates = [row["record"] for row in rows if row["record"]["record_id"] == args.record_id]
    if args.version is not None:
        candidates = [record for record in candidates if int(record["version"]) == args.version]
    if not candidates:
        print(f"未找到记录: {args.record_id}")
        return 2
    record = candidates[-1]
    citation = build_citation(record)
    _print_json(citation)
    return 0


def cmd_integrity(args: argparse.Namespace) -> int:
    store = AppendOnlyStore(Path(args.store))
    result = store.integrity()
    _print_json(result)
    return 0 if result["ok"] else 1


def cmd_citations_check(args: argparse.Namespace) -> int:
    citations = read_citations(Path(args.path))
    failures: list[str] = []
    for citation in citations:
        try:
            resolve_citation(citation["citation"])
        except Exception as exc:  # noqa: BLE001 - 报告中如实记录失败原因
            failures.append(f"{citation.get('record_id')}: {exc}")
    _print_json({"citations": len(citations), "failures": failures, "ok": not failures})
    return 0 if not failures else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="record_wiring", description="管理记录知识接线工具（订单 #1507）")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="一键复跑：重置演示库并生成 out/ 全部产物")
    demo.add_argument("--input", default=str(SAMPLES_FILE))
    demo.add_argument("--store", default=str(STORE_FILE))
    demo.add_argument("--out", default=str(OUT_DIR))
    demo.set_defaults(func=cmd_demo)

    ingest = sub.add_parser("ingest", help="幂等导入（只追加，不清空）")
    ingest.add_argument("--input", default=str(SAMPLES_FILE))
    ingest.add_argument("--store", default=str(STORE_FILE))
    ingest.add_argument("--now", default=DEFAULT_INGEST_AT)
    ingest.add_argument("--trace", default="")
    ingest.set_defaults(func=cmd_ingest)

    query = sub.add_parser("query", help="按角色权限检索")
    query.add_argument("--role", required=True)
    query.add_argument("--store", default=str(STORE_FILE))
    query.add_argument("--record-type", default="")
    query.add_argument("--label", default="")
    query.set_defaults(func=cmd_query)

    export = sub.add_parser("export", help="按角色权限导出（带授权标记）")
    export.add_argument("--role", required=True)
    export.add_argument("--store", default=str(STORE_FILE))
    export.add_argument("--out", required=True)
    export.set_defaults(func=cmd_export)

    cite = sub.add_parser("cite", help="生成单条记录的可定位引用")
    cite.add_argument("--record-id", required=True)
    cite.add_argument("--version", type=int)
    cite.add_argument("--store", default=str(STORE_FILE))
    cite.set_defaults(func=cmd_cite)

    integrity = sub.add_parser("integrity", help="校验存储哈希链与 seq")
    integrity.add_argument("--store", default=str(STORE_FILE))
    integrity.set_defaults(func=cmd_integrity)

    check = sub.add_parser("check-citations", help="逐条解析引用并校验切片")
    check.add_argument("--path", default=str(OUT_DIR / "citations.jsonl"))
    check.set_defaults(func=cmd_citations_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
