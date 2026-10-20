"""导出：脱敏后的记录快照、导入报告、脱敏前后对照、按角色过滤的导出。

所有渲染都是确定性的（固定生成时间、固定排序），便于复跑比对。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import quote

from .access import AccessController
from .citation import resolve_citation
from .config import PROJECT_ROOT
from .ingest import IngestReport


GENERATED_AT = "2026-10-20T09:30:00Z"


def write_jsonl(path: Path, items: Iterable[Mapping[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def record_view(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row["record"]) for row in rows]


def _cell(value: Any, limit: int = 0) -> str:
    text = str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    if limit and len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def render_import_report(
    report: IngestReport,
    rows: Iterable[Mapping[str, Any]],
    *,
    generated_at: str = GENERATED_AT,
) -> str:
    rows = list(rows)
    lines = [
        "# 导入报告（脱敏后）",
        "",
        f"- 生成时间（UTC）：{generated_at}",
        f"- 输入文件：`{report.input_file}`",
        f"- 总行数：{report.total_lines}",
        f"- 新增行数：{report.added}",
        f"- 去重跳过：{report.skipped_duplicate}",
        f"- 版本提升：{report.version_bumped}",
        f"- 校验拒绝：{report.rejected}",
        f"- 存储总行数：{report.stored_rows}",
        f"- 含脱敏字段的记录：{report.redaction_records}",
        f"- 脱敏命中次数：{report.redaction_findings}",
        "",
        "## 逐条结果",
        "",
        "| 序号 | 记录 | 版本 | 类型 | 访问标签 | 敏感级 | 发生时间 | 脱敏命中 | 来源定位 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        record = row["record"]
        source = record["source"]
        rules = ",".join(record.get("redaction", {}).get("rules", [])) or "-"
        lines.append(
            "| {seq} | {rid} | {version} | {rtype} | {labels} | {sensitivity} | {occurred} | {hits} | {loc} |".format(
                seq=row["seq"],
                rid=_cell(record["record_id"]),
                version=record["version"],
                rtype=_cell(record["record_type"]),
                labels=_cell(",".join(record["access"]["labels"])),
                sensitivity=_cell(record["access"]["sensitivity"]),
                occurred=_cell(record["occurred_at"]),
                hits=f"{rules} ({record.get('redaction', {}).get('count', 0)})",
                loc=f"{source['source_file']}:{source['line_no']}",
            )
        )
    if report.rejections:
        lines.extend(["", "## 拒绝明细", "", "| 行号 | 记录 | 错误码 | 原因 |", "|---|---|---|---|"])
        for item in report.rejections:
            lines.append(
                f"| {item['line_no']} | {_cell(item['record_id'])} | {item['code']} | {_cell(item['message'])} |"
            )
    if report.version_notes:
        lines.extend(["", "## 版本提升说明", "", "| 记录 | 输入版本 | 存储版本 |", "|---|---|---|"])
        for note in report.version_notes:
            lines.append(f"| {note['record_id']} | {note['incoming_version']} | {note['stored_version']} |")
    lines.append("")
    return "\n".join(lines)


def render_redaction_diff(
    rows: Iterable[Mapping[str, Any]],
    *,
    root: Path = PROJECT_ROOT,
    limit: int = 40,
) -> str:
    rows = list(rows)
    lines = [
        "# 脱敏前后对照表",
        "",
        "脱敏前正文由引用 `clawhunt://...` 从源文件按字节区间切片还原，脱敏后正文取自导入产物。",
        "token 由 sha256(规则 ID + 原值) 前 6 位生成，同一原值稳定映射到同一 token。",
        "",
        "| 序号 | 记录 | 版本 | 命中规则 | 脱敏前（原文） | 脱敏后（导入产物） |",
        "|---|---|---|---|---|---|",
    ]
    count = 0
    for row in rows:
        record = row["record"]
        redaction = record.get("redaction", {})
        if int(redaction.get("count", 0)) <= 0:
            continue
        if count >= limit:
            break
        citation = record["source"]
        params = (
            f"?record_id={citation['record_id']}&hash={citation['hash']}"
            f"&line={citation['line_no']}&byte_offset={citation['byte_offset']}"
            f"&byte_length={citation['byte_length']}&body_offset={citation['body_offset']}"
            f"&body_length={citation['body_length']}"
        )
        uri = "clawhunt://{system}/{path}{params}".format(
            system=citation["system"],
            path=quote(citation["source_file"], safe="/"),
            params=params,
        )
        raw_body = resolve_citation(uri, root=root)["body"]
        rules = ",".join(redaction.get("rules", [])) or "-"
        lines.append(
            "| {seq} | {rid} | {version} | {rules} | {before} | {after} |".format(
                seq=row["seq"],
                rid=_cell(record["record_id"]),
                version=record["version"],
                rules=rules,
                before=_cell(raw_body),
                after=_cell(record["body"]),
            )
        )
        count += 1
    lines.extend(["", f"共 {count} 条记录给出脱敏前后对照。", ""])
    return "\n".join(lines)


def export_for_role(
    rows: Iterable[Mapping[str, Any]],
    controller: AccessController,
    role: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    exported: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    for row in rows:
        record = row.get("record", row)
        decision = controller.decide(record, role)
        decisions.append(decision)
        if decision["allowed"]:
            item = dict(record)
            item["_grant"] = controller.grant_marker(decision, record)
            exported.append(item)
    return exported, decisions
