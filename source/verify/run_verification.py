"""独立验收脚本（订单 #1507 · 管理记录知识接线）。

    python verify/run_verification.py

逐条验证验收标准与买家关注点：
  1 来源是可解析指针（system + uri + hash + record_id）
  2 append-only 存储，保留版本与接收时间
  3 每条记录带访问标签，检索/导出按权限过滤并留授权标记
  4 导入幂等（record_id + hash 重复不新增）
  5 脱敏真的执行，留下前后对照

真实原始输出写入 verify/records/：
  verification_output.txt  本脚本完整输出
  assertions.txt           每条断言一行
  tests_output.txt         tests/test_runner.py 原始输出
  ingest_run1.txt          第一次导入 CLI 原始输出
  ingest_run2.txt          第二次导入 CLI 原始输出
  demo_run.txt             复跑 demo 的原始输出
  environment.txt          Python 版本与平台
  commands.md              命令、退出码、产物对照
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from record_wiring.access import AccessController, load_policy  # noqa: E402
from record_wiring.citation import build_citation, read_citations, resolve_citation  # noqa: E402
from record_wiring.config import (  # noqa: E402
    SAMPLES_FILE,
    load_access_policy,
    load_privacy_rules,
    load_records_schema,
)
from record_wiring.export import export_for_role, render_import_report, render_redaction_diff  # noqa: E402
from record_wiring.ingest import Ingestor  # noqa: E402
from record_wiring.model import Record, sha256_text  # noqa: E402
from record_wiring.privacy import load_engine  # noqa: E402
from record_wiring.schema import SchemaError, load_schema  # noqa: E402
from record_wiring.store import AppendOnlyStore  # noqa: E402

RECORDS_DIR = ROOT / "verify" / "records"
TMP_DIR = ROOT / "verify" / "_tmp_verify"
OUT = ROOT / "out"
PY = sys.executable
SAMPLES = SAMPLES_FILE

EMOJI_RE = re.compile("[\U0001f300-\U0001faff\u2600-\u27bf\ufe0f]")
NS = "2026-10-20T09:30:00Z"


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def short(value: Any, limit: int = 160) -> str:
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def run(args: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        args,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


class Verifier:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.checks: list[dict[str, Any]] = []
        self.commands: list[dict[str, Any]] = []

    def emit(self, text: str = "") -> None:
        print(text)
        self.lines.append(text)

    def section(self, title: str) -> None:
        self.emit("")
        self.emit("=" * 78)
        self.emit(title)
        self.emit("=" * 78)

    def check(self, name: str, expected: Any, actual: Any, ok: bool) -> None:
        index = len(self.checks) + 1
        passed = bool(ok)
        item = {
            "index": index,
            "name": name,
            "expected": short(expected, 240),
            "actual": short(actual, 240),
            "passed": passed,
        }
        self.checks.append(item)
        status = "PASS" if passed else "FAIL"
        self.emit(f"[{status}] {index:02d} {name} | 预期: {short(expected)} | 实际: {short(actual)}")

    def command(self, step: str, args: list[str], proc: subprocess.CompletedProcess[str], output: str) -> None:
        self.commands.append(
            {
                "step": step,
                "command": " ".join(args),
                "exit_code": proc.returncode,
                "output": output,
            }
        )
        self.check(f"命令退出码：{step}", 0, proc.returncode, proc.returncode == 0)

    def failed(self) -> list[dict[str, Any]]:
        return [item for item in self.checks if not item["passed"]]

    def result(self) -> dict[str, Any]:
        failed = self.failed()
        return {
            "order": 1507,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "python": sys.version,
            "assertions_total": len(self.checks),
            "assertions_passed": len(self.checks) - len(failed),
            "assertions_failed": len(failed),
            "all_passed": not failed,
            "checks": self.checks,
        }


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def ascii_paths(paths: Iterable[Path]) -> tuple[bool, str]:
    bad = []
    for path in paths:
        rel = path.relative_to(ROOT).as_posix()
        if not rel.isascii():
            bad.append(rel)
    return (not bad), ",".join(bad) if bad else "全部 ASCII"


def collect_files() -> list[Path]:
    skip = {".store", "__pycache__", ".tmp", "_tmp_verify", ".git"}
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip for part in path.relative_to(ROOT).parts):
            continue
        files.append(path)
    return files


def check_encoding_and_deps(v: Verifier) -> None:
    v.section("9 编码、命名与零依赖")
    files = collect_files()
    ok, detail = ascii_paths(files)
    v.check("目录与文件名全部 ASCII", "全部 ASCII", detail, ok)

    text_exts = {".py", ".md", ".json", ".jsonl", ".txt", ".gitignore", ""}
    bom_bad: list[str] = []
    emoji_bad: list[str] = []
    for path in files:
        if path.suffix not in text_exts and path.name != ".gitignore":
            continue
        data = path.read_bytes()
        if data.startswith(b"\xef\xbb\xbf"):
            bom_bad.append(path.relative_to(ROOT).as_posix())
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if EMOJI_RE.search(text):
            emoji_bad.append(path.relative_to(ROOT).as_posix())
    v.check("UTF-8 无 BOM", "0 个 BOM 文件", ",".join(bom_bad) or "0", not bom_bad)
    v.check("文档与代码无 emoji", "0 个", ",".join(emoji_bad) or "0", not emoji_bad)

    stdlib = set(sys.stdlib_module_names)
    local = {"record_wiring", "tests", "verify"}
    third_party: list[str] = []
    parsed = 0
    for path in files:
        if path.suffix != ".py":
            continue
        parsed += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                if name not in stdlib and name not in local:
                    third_party.append(f"{path.name}:{name}")
    v.check("仅标准库导入（无第三方依赖）", "0 个第三方导入", ",".join(sorted(set(third_party))) or "0", not third_party)
    v.emit(f"- 扫描 Python 文件 {parsed} 个；文件总数 {len(files)} 个")


def check_files(v: Verifier) -> None:
    v.section("1 交付物完整性")
    required = [
        "SOLUTION.md",
        "README.md",
        "DELIVERY.md",
        ".gitignore",
        "config/records_schema.json",
        "config/privacy_rules.json",
        "config/access_policy.json",
        "samples/raw_records.jsonl",
        "tests/test_runner.py",
        "verify/run_verification.py",
        "out/records_imported.jsonl",
        "out/import_report.md",
        "out/redaction_diff.md",
        "out/citations.jsonl",
    ]
    modules = [
        "model.py",
        "config.py",
        "schema.py",
        "privacy.py",
        "ingest.py",
        "store.py",
        "access.py",
        "citation.py",
        "export.py",
        "trace.py",
        "cli.py",
        "__init__.py",
        "__main__.py",
    ]
    required.extend(f"record_wiring/{name}" for name in modules)
    missing = [rel for rel in required if not (ROOT / rel).is_file()]
    v.check("必需文件齐全", f"{len(required)} 个", f"缺失 {missing}" if missing else f"{len(required)} 个", not missing)

    empty = [rel for rel in required if (ROOT / rel).is_file() and (ROOT / rel).stat().st_size == 0]
    v.check("必需文件非空", "0 个空文件", ",".join(empty) or "0", not empty)

    sample_lines = SAMPLES.read_text(encoding="utf-8").splitlines()
    v.check("合成原始记录不少于 20 条", ">=20", len([x for x in sample_lines if x.strip()]), len(sample_lines) >= 20)
    v.check("SOLUTION 含两个链接占位", "REPO_LINK_HERE + ZIP_LINK_HERE",
            "REPO_LINK_HERE" in (ROOT / "SOLUTION.md").read_text(encoding="utf-8")
            and "ZIP_LINK_HERE" in (ROOT / "SOLUTION.md").read_text(encoding="utf-8"),
            "REPO_LINK_HERE" in (ROOT / "SOLUTION.md").read_text(encoding="utf-8")
            and "ZIP_LINK_HERE" in (ROOT / "SOLUTION.md").read_text(encoding="utf-8"))


def check_schema(v: Verifier) -> tuple[list[dict[str, Any]], Any, Any, Any]:
    v.section("2 Schema 与来源指针（验收标准：可定位原始记录的引用）")
    schema = load_schema(load_records_schema())
    privacy = load_engine(load_privacy_rules())
    policy = load_policy(load_access_policy())
    lines = [line for line in SAMPLES.read_bytes().splitlines(keepends=True) if line.strip()]
    records: list[Record] = []
    parse_errors: list[str] = []
    for line in lines:
        try:
            records.append(Record.from_dict(json.loads(line.decode("utf-8"))))
        except Exception as exc:  # noqa: BLE001
            parse_errors.append(str(exc))
    v.check("原始记录全部可解析", f"0 错误 / {len(lines)} 条", f"{len(parse_errors)} 错误",
            not parse_errors)
    v.check("原始记录条数", len(lines), len(records), len(records) == len(lines))

    valid_errors: list[str] = []
    for record in records:
        try:
            schema.validate(record, allowed_labels=policy.label_names(), allowed_roles=policy.role_names())
        except SchemaError as exc:
            valid_errors.append(f"{record.record_id}:{exc.code}")
    v.check("全部记录通过 Schema 校验", "0 错误", ",".join(valid_errors) or "0", not valid_errors)

    hash_bad = [record.record_id for record in records if record.source.hash != sha256_text(record.body)]
    v.check("hash = SHA-256(原始正文)", "全部一致", f"{len(records) - len(hash_bad)}/{len(records)}", not hash_bad)

    pointer_bad = [
        record.record_id
        for record in records
        if not all([record.source.system, record.source.uri, record.source.record_id, record.source.hash])
    ]
    v.check("来源指针四要素齐全（system/uri/record_id/hash）", "全部齐全", f"{len(records) - len(pointer_bad)}/{len(records)}",
            not pointer_bad)

    system_bad = [record.record_id for record in records if record.source.system not in load_records_schema()["source_systems"]]
    uri_bad = [record.record_id for record in records if "://" not in record.source.uri]
    v.check("来源系统在登记清单内", "全部合规", f"{len(records) - len(system_bad)}/{len(records)}", not system_bad)
    v.check("来源 URI 可解析（含 scheme）", "全部合规", f"{len(records) - len(uri_bad)}/{len(records)}", not uri_bad)

    offset_ok = 0
    offset_bad: list[str] = []
    for record, line in zip(records, lines):
        needle = record.body.encode("utf-8")
        if line.find(needle) >= 0:
            offset_ok += 1
        else:
            offset_bad.append(record.record_id)
    v.check("正文可在源文件中按字节定位", f"{len(records)}/{len(records)}", f"{offset_ok}/{len(records)}", not offset_bad)

    bad_record = Record.from_dict(json.loads(lines[0].decode("utf-8")))
    try:
        schema.validate(
            Record(
                record_id=bad_record.record_id,
                version=bad_record.version,
                record_type=bad_record.record_type,
                title=bad_record.title,
                body=bad_record.body + "X",
                department=bad_record.department,
                occurred_at=bad_record.occurred_at,
                received_at=bad_record.received_at,
                source=bad_record.source,
                access=bad_record.access,
            ),
            allowed_labels=policy.label_names(),
            allowed_roles=policy.role_names(),
        )
        hash_rejected = False
    except SchemaError as exc:
        hash_rejected = exc.code == "source.hash"
    v.check("正文被改写后 hash 校验拒绝", "拒绝 source.hash", hash_rejected, hash_rejected)

    v.emit(f"- 样例来源：{records[0].source.system} / {records[0].source.uri}")
    v.emit(f"- 样例正文 hash：{records[0].source.hash}")
    return [json.loads(line.decode("utf-8")) for line in lines], schema, privacy, policy


def check_ingest(v: Verifier) -> tuple[AppendOnlyStore, dict[str, Any], bytes]:
    v.section("3 幂等导入与 append-only（买家关注点 2、4）")
    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    store_path = TMP_DIR / "records.jsonl"
    trace_path = TMP_DIR / "ingest_trace.jsonl"

    args1 = [PY, "-m", "record_wiring", "ingest", "--store", str(store_path), "--trace", str(trace_path)]
    proc1 = run(args1)
    write_text(RECORDS_DIR / "ingest_run1.txt", proc1.stdout + ("\n[stderr]\n" + proc1.stderr if proc1.stderr else ""))
    v.command("第一次导入", args1, proc1, "verify/records/ingest_run1.txt")
    try:
        summary1 = json.loads(proc1.stdout)
    except json.JSONDecodeError:
        summary1 = {}
    v.check("第一次导入统计可解析", "JSON", bool(summary1), bool(summary1))
    v.check("第一次导入：总行数 24", 24, summary1.get("total_lines"), summary1.get("total_lines") == 24)
    v.check("第一次导入：新增 23", 23, summary1.get("added"), summary1.get("added") == 23)
    v.check("第一次导入：去重 1（文件内重复行）", 1, summary1.get("skipped_duplicate"),
            summary1.get("skipped_duplicate") == 1)
    v.check("第一次导入：拒绝 0", 0, summary1.get("rejected"), summary1.get("rejected") == 0)

    store = AppendOnlyStore(store_path)
    rows = store.rows()
    after_first = store_path.read_bytes()
    v.check("存储行数等于新增行数", 23, len(rows), len(rows) == 23)
    v.check("存储链完整性", "ok", store.integrity()["ok"], store.integrity()["ok"])

    args2 = [PY, "-m", "record_wiring", "ingest", "--store", str(store_path)]
    proc2 = run(args2)
    write_text(RECORDS_DIR / "ingest_run2.txt", proc2.stdout + ("\n[stderr]\n" + proc2.stderr if proc2.stderr else ""))
    v.command("第二次导入（幂等）", args2, proc2, "verify/records/ingest_run2.txt")
    try:
        summary2 = json.loads(proc2.stdout)
    except json.JSONDecodeError:
        summary2 = {}
    v.check("第二次导入：新增 0", 0, summary2.get("added"), summary2.get("added") == 0)
    v.check("第二次导入：整份去重 24", 24, summary2.get("skipped_duplicate"),
            summary2.get("skipped_duplicate") == 24)
    after_second = store_path.read_bytes()
    v.check("重复导入后文件字节不变", "sha256 相同", sha_bytes(after_first) == sha_bytes(after_second),
            sha_bytes(after_first) == sha_bytes(after_second))
    v.check("第二次写入只追加不截断", "前缀一致", after_second.startswith(after_first),
            after_second.startswith(after_first))
    v.check("重复导入后行数仍为 23", 23, len(store.rows()), len(store.rows()) == 23)

    version_rows = [row["record"] for row in store.rows() if row["record"]["record_id"] == "MR-2026-0010"]
    v.check("同一 record_id 保留两个版本", "[1, 2]", [item["version"] for item in version_rows],
            [item["version"] for item in version_rows] == [1, 2])
    v1_hash_ok = version_rows and version_rows[0]["source"]["hash"] == sha256_text(
        next(record.body for record in [Record.from_dict(x) for x in read_jsonl(SAMPLES)] if record.record_id == "MR-2026-0010" and record.version == 1)
    )
    v.check("历史版本正文哈希未被改写", "一致", v1_hash_ok, bool(v1_hash_ok))

    trace = read_jsonl(trace_path)
    events = [item["event"] for item in trace]
    v.check("导入轨迹含跳过与完成事件", "ingest_skip + ingest_done",
            f"ingest_skip={events.count('ingest_skip')} ingest_done={events.count('ingest_done')}",
            events.count("ingest_skip") == 1 and events.count("ingest_done") == 1)

    v.emit(f"- 第一次导入：{summary1}")
    v.emit(f"- 第二次导入：{summary2}")
    v.emit(f"- 存储链 head：{store.integrity()['head'][:16]}...；行数 {store.count()}")
    return store, summary1, after_first


def check_access(v: Verifier, store: AppendOnlyStore, policy: Any) -> None:
    v.section("4 访问权限过滤与授权标记（买家关注点 3）")
    rows = store.rows()
    missing_labels = [row["record"]["record_id"] for row in rows if not row["record"]["access"]["labels"]]
    v.check("每条记录都有访问标签", "0 条缺失", ",".join(missing_labels) or "0", not missing_labels)

    controller = AccessController(policy)
    by_id = {row["record"]["record_id"]: row["record"] for row in rows}
    hr_record = by_id["MR-2026-0002"]

    deny = controller.decide(hr_record, "analyst")
    v.check("analyst 无法读取 HR 记录", "allowed=False", f"allowed={deny['allowed']} missing={deny['missing_labels']}",
            deny["allowed"] is False)
    allow = controller.decide(hr_record, "compliance_auditor")
    v.check("compliance_auditor 可读 HR 记录", "allowed=True", f"allowed={allow['allowed']}", allow["allowed"] is True)

    analyst_rows, analyst_decisions = export_for_role(rows, AccessController(policy), "analyst")
    v.check("analyst 导出仅 3 条（内部/聚合）", 3, len(analyst_rows), len(analyst_rows) == 3)
    v.check("analyst 导出不含 HR 记录", "不含 MR-2026-0002", [item["record_id"] for item in analyst_rows],
            all(item["record_id"] != "MR-2026-0002" for item in analyst_rows))
    v.check("导出记录带授权标记 _grant", "全部带标记", f"{sum(1 for x in analyst_rows if x.get('_grant'))}/{len(analyst_rows)}",
            all(item.get("_grant", {}).get("policy_id") == policy.policy_id for item in analyst_rows))
    denied = [item for item in analyst_decisions if not item["allowed"]]
    v.check("拒绝判定被记录（含 decision_id）", ">0 且带 decision_id",
            f"denied={len(denied)} first={denied[0]['decision_id'] if denied else '-'}",
            bool(denied) and all(item["decision_id"].startswith("AD-") for item in denied))

    unknown = AccessController(policy).decide(rows[0]["record"], "guest")
    v.check("未知角色默认拒绝", "allowed=False", f"allowed={unknown['allowed']}", unknown["allowed"] is False)

    intern_rows, _ = export_for_role(rows, AccessController(policy), "intern")
    v.check("intern 仅见普通内部记录 1 条", 1, len(intern_rows), len(intern_rows) == 1)

    compliance_rows, _ = export_for_role(rows, AccessController(policy), "compliance_auditor")
    v.check("合规审计员可见全部 23 条", 23, len(compliance_rows), len(compliance_rows) == 23)

    v.emit(f"- analyst 可见：{[item['record_id'] for item in analyst_rows]}")
    v.emit(f"- 拒绝示例：{deny}")
    v.emit(f"- 授权标记示例：{analyst_rows[0]['_grant'] if analyst_rows else '{}'}")


def check_privacy(v: Verifier, store: AppendOnlyStore, privacy: Any, policy: Any) -> None:
    v.section("5 脱敏执行与前后对照（买家关注点 5）")
    rows = store.rows()
    residual: list[str] = []
    for row in rows:
        body = row["record"]["body"]
        if privacy.residue(body):
            residual.append(row["record"]["record_id"])
        for term in privacy.name_terms:
            if term in body:
                residual.append(f"{row['record']['record_id']}:name")
    v.check("导入产物无残留敏感信息", "0 处", ",".join(sorted(set(residual))) or "0", not residual)

    redacted_count = sum(1 for row in rows if int(row["record"].get("redaction", {}).get("count", 0)) > 0)
    v.check("实际执行了脱敏（记录数）", ">=20", redacted_count, redacted_count >= 20)
    total_findings = sum(int(row["record"].get("redaction", {}).get("count", 0)) for row in rows)
    v.check("脱敏命中总数", ">0", total_findings, total_findings > 0)

    diff = render_redaction_diff(rows)
    diff_rows = [line for line in diff.splitlines() if line.startswith("| ") and "MR-2026-" in line]
    v.check("脱敏前后对照不少于 8 条", ">=8", len(diff_rows), len(diff_rows) >= 8)
    changed = 0
    for line in diff_rows:
        cells = line.split("|")
        if len(cells) >= 7 and cells[5].strip() != cells[6].strip():
            changed += 1
    v.check("对照表中前后确实不同", f"{len(diff_rows)}/{len(diff_rows)}", f"{changed}/{len(diff_rows)}",
            changed == len(diff_rows))

    body_0001 = next(row["record"]["body"] for row in rows if row["record"]["record_id"] == "MR-2026-0001")
    body_0008 = next(row["record"]["body"] for row in rows if row["record"]["record_id"] == "MR-2026-0008")
    token_0001 = re.findall(r"\[PHONE:[0-9a-f]{6}\]", body_0001)
    token_0008 = re.findall(r"\[PHONE:[0-9a-f]{6}\]", body_0008)
    v.check("同一手机号映射到同一 token", "token 相同", f"{token_0001} == {token_0008}",
            bool(token_0001) and token_0001 == token_0008)

    sample_body = SAMPLES.read_text(encoding="utf-8")
    again1, _ = privacy.redact("张伟 13800001111")
    again2, _ = privacy.redact("张伟 13800001111")
    v.check("脱敏结果确定性（同输入同输出）", "两次一致", again1 == again2, again1 == again2)

    v.check("原始样例明确为合成数据", "含 synthetic 标记或说明", "合成" in (ROOT / "SOLUTION.md").read_text(encoding="utf-8"),
            "合成" in (ROOT / "SOLUTION.md").read_text(encoding="utf-8"))
    v.emit(f"- 含脱敏字段记录 {redacted_count} 条，命中 {total_findings} 次；对照 {len(diff_rows)} 条")
    v.emit(f"- 示例：{body_0001[:90]}...")


def check_citations(v: Verifier, store: AppendOnlyStore) -> None:
    v.section("6 原始记录定位引用（验收标准核心）")
    citations = read_citations(OUT / "citations.jsonl")
    v.check("citations.jsonl 条数等于存储行数", store.count(), len(citations), len(citations) == store.count())
    failures: list[str] = []
    line_mismatch: list[str] = []
    offset_out: list[str] = []
    for citation in citations:
        try:
            resolved = resolve_citation(citation["citation"])
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{citation.get('record_id')}:{exc}")
            continue
        raw = (ROOT / resolved["source_file"]).read_bytes()
        chunk = raw[resolved["body_offset"] : resolved["body_offset"] + resolved["body_length"]]
        if sha_bytes(chunk) != citation["hash"]:
            failures.append(f"{citation['record_id']}:hash")
        if resolved["line_no"] != citation["line_no"]:
            line_mismatch.append(citation["record_id"])
        source = next(
            (row["record"]["source"] for row in store.rows()
             if row["record"]["record_id"] == citation["record_id"] and row["record"]["version"] == citation["version"]),
            None,
        )
        if not source or not (
            source["byte_offset"] <= source["body_offset"]
            and source["body_offset"] + source["body_length"] <= source["byte_offset"] + source["byte_length"]
        ):
            offset_out.append(citation["record_id"])
    v.check("每条引用都能切片定位并哈希一致", f"{len(citations)}/{len(citations)}",
            ",".join(failures) or "全部通过", not failures)
    v.check("引用行号与存储定位一致", "0 不一致", ",".join(line_mismatch) or "0", not line_mismatch)
    v.check("正文区间落在整行区间内", "0 越界", ",".join(offset_out) or "0", not offset_out)

    example = citations[0]
    resolved = resolve_citation(example["citation"])
    v.check("示例引用可解析出原始正文", "非空", short(resolved["body"], 80), bool(resolved["body"]))
    v.check("示例引用 hash 与正文切片一致", example["hash"], sha_bytes(resolved["body"].encode("utf-8")),
            example["hash"] == sha_bytes(resolved["body"].encode("utf-8")))

    v.emit("")
    v.emit("原始记录定位引用示例：")
    v.emit(f"  URI      : {example['citation']}")
    v.emit(f"  人可读   : {example['human']}")
    v.emit(f"  system   : {example['system']}")
    v.emit(f"  record_id: {example['record_id']} (v{example['version']})")
    v.emit(f"  hash     : {example['hash']}")
    v.emit(f"  切片校验 : sha256(slice) == hash -> {example['hash'] == sha_bytes(resolved['body'].encode('utf-8'))}")
    v.emit(f"  原文切片 : {short(resolved['body'], 100)}")


def check_artifacts(v: Verifier, store: AppendOnlyStore, report_summary: Mapping[str, Any]) -> None:
    v.section("7 out 产物与导入报告")
    imported = read_jsonl(OUT / "records_imported.jsonl")
    v.check("out/records_imported.jsonl 行数", 23, len(imported), len(imported) == 23)
    v.check("导入产物全部脱敏（有 redaction 元数据）", "23/23", f"{sum(1 for x in imported if 'redaction' in x)}/{len(imported)}",
            all("redaction" in item for item in imported))
    v.check("导入产物保留访问标签", "23/23", f"{sum(1 for x in imported if x.get('access', {}).get('labels'))}/{len(imported)}",
            all(item.get("access", {}).get("labels") for item in imported))
    v.check("导入产物保留来源定位", "23/23",
            f"{sum(1 for x in imported if x.get('source', {}).get('line_no'))}/{len(imported)}",
            all(item.get("source", {}).get("line_no") for item in imported))
    v.check("导入产物保留接收时间", "23/23",
            f"{sum(1 for x in imported if x.get('received_at'))}/{len(imported)}",
            all(item.get("received_at") for item in imported))

    report_text = (OUT / "import_report.md").read_text(encoding="utf-8")
    for line in ["总行数：24", "新增行数：23", "去重跳过：1", "校验拒绝：0", "存储总行数：23"]:
        v.check(f"导入报告含「{line}」", True, line in report_text, line in report_text)
    v.check("报告统计与 CLI 一致", report_summary.get("added"),
            "新增行数：23" in report_text and report_summary.get("added") == 23,
            report_summary.get("added") == 23)

    diff_text = (OUT / "redaction_diff.md").read_text(encoding="utf-8")
    diff_rows = [line for line in diff_text.splitlines() if line.startswith("| ") and "MR-2026-" in line]
    v.check("out/redaction_diff.md 至少 8 条对照", ">=8", len(diff_rows), len(diff_rows) >= 8)
    v.check("对照表含原文与脱敏后两列", "两列齐全", "脱敏前（原文）" in diff_text and "脱敏后（导入产物）" in diff_text,
            "脱敏前（原文）" in diff_text and "脱敏后（导入产物）" in diff_text)

    citations = read_jsonl(OUT / "citations.jsonl")
    v.check("citations.jsonl 含 system/uri/hash/record_id", "全部含",
            f"{sum(1 for c in citations if all(k in c for k in ('system', 'source_uri', 'hash', 'record_id', 'line_no')))}/{len(citations)}",
            all(all(k in c for k in ("system", "source_uri", "hash", "record_id", "line_no")) for c in citations))
    v.check("citations.jsonl 含字节偏移", "全部含",
            f"{sum(1 for c in citations if all(k in c for k in ('body_offset', 'body_length', 'byte_offset', 'byte_length')))}/{len(citations)}",
            all(all(k in c for k in ("body_offset", "body_length", "byte_offset", "byte_length")) for c in citations))

    access_log = read_jsonl(OUT / "access_log.jsonl")
    v.check("out/access_log.jsonl 有授权判定记录", ">0", len(access_log), len(access_log) > 0)
    v.check("授权日志同时含允许与拒绝", "两类都有", f"allow={sum(1 for x in access_log if x['allowed'])} deny={sum(1 for x in access_log if not x['allowed'])}",
            any(item["allowed"] for item in access_log) and any(not item["allowed"] for item in access_log))

    imported_hash = sha_bytes((OUT / "records_imported.jsonl").read_bytes())
    v.check("导入产物与存储一致（行数）", store.count(), len(imported), len(imported) == store.count())
    v.emit(f"- records_imported.jsonl sha256={imported_hash[:16]}...；report/redaction/citations 均已校验")


def check_tests(v: Verifier) -> None:
    v.section("8 单元测试原始输出")
    args = [PY, "tests/test_runner.py"]
    proc = run(args)
    output = proc.stdout + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    write_text(RECORDS_DIR / "tests_output.txt", output)
    v.command("单元测试", args, proc, "verify/records/tests_output.txt")
    match = re.search(r"(\d+)/(\d+) tests passed", proc.stdout)
    v.check("测试输出含 N/N tests passed", "存在", match.group(0) if match else "未找到", bool(match))
    if match:
        v.check("测试全部通过", f"{match.group(2)}/{match.group(2)}", match.group(0),
                match.group(1) == match.group(2))
    else:
        v.check("测试全部通过", "N/N", "无法解析", False)


def check_demo_determinism(v: Verifier) -> None:
    v.section("10 一键复跑确定性")
    names = [
        "records_imported.jsonl",
        "import_report.md",
        "redaction_diff.md",
        "citations.jsonl",
        "access_log.jsonl",
    ]
    before = {name: sha_bytes((OUT / name).read_bytes()) for name in names if (OUT / name).is_file()}
    args = [PY, "-m", "record_wiring", "demo"]
    proc = run(args, timeout=300)
    output = proc.stdout + ("\n[stderr]\n" + proc.stderr if proc.stderr else "")
    write_text(RECORDS_DIR / "demo_run.txt", output)
    v.command("复跑 demo", args, proc, "verify/records/demo_run.txt")
    after = {name: sha_bytes((OUT / name).read_bytes()) for name in names if (OUT / name).is_file()}
    same = bool(before) and before == after
    v.check("demo 两次产物逐字节一致", "全部相同", ",".join(f"{k}:{'同' if before.get(k) == val else '异'}" for k, val in after.items()),
            same)
    v.check("demo 输出含统计行", "总行数=24 新增=23", "总行数=24 新增=23 去重跳过=1" in proc.stdout,
            "总行数=24 新增=23 去重跳过=1" in proc.stdout)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    RECORDS_DIR.mkdir(parents=True, exist_ok=True)
    v = Verifier()
    started = datetime.now(timezone.utc)
    v.emit("# 验收运行记录 · 订单 #1507 管理记录知识接线")
    v.emit(f"时间（UTC）：{started.isoformat()}")
    v.emit(f"Python：{sys.version.splitlines()[0]}（{sys.executable}）")
    v.emit(f"项目根：{ROOT}")
    v.emit("命令：python verify/run_verification.py")

    try:
        check_files(v)
        _sample_data, schema, privacy, policy = check_schema(v)
        store, summary1, _first_bytes = check_ingest(v)
        check_access(v, store, policy)
        check_privacy(v, store, privacy, policy)
        check_citations(v, store)
        check_artifacts(v, store, summary1)
        check_tests(v)
        check_encoding_and_deps(v)
        check_demo_determinism(v)
    except Exception:  # noqa: BLE001 - 验收脚本必须把异常写进记录
        v.emit("")
        v.emit("[FATAL] 验收脚本异常：")
        v.emit(traceback.format_exc())
        v.check("验收脚本无异常", "无异常", "异常", False)

    failed = v.failed()
    passed = len(v.checks) - len(failed)
    v.emit("")
    v.emit("=" * 78)
    v.emit("结果汇总")
    v.emit("=" * 78)
    if failed:
        for item in failed:
            v.emit(f"[FAIL] {item['index']:02d} {item['name']} | 预期 {item['expected']} | 实际 {item['actual']}")
    else:
        v.emit("全部断言通过，无失败项。")
    v.emit(f"断言总数 {len(v.checks)}；通过 {passed}；失败 {len(failed)}")

    (RECORDS_DIR / "assertions.txt").write_text(
        "\n".join(
            f"[{'PASS' if item['passed'] else 'FAIL'}] {item['index']:02d} {item['name']} | 预期: {item['expected']} | 实际: {item['actual']}"
            for item in v.checks
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_text(RECORDS_DIR / "environment.txt", f"python={sys.version}\nexecutable={sys.executable}\nplatform={sys.platform}\ncwd={ROOT}\n")
    commands_md = ["# 验证命令与原始输出对照", "", f"运行时间（UTC）：{started.isoformat()}", "", "| 步骤 | 命令 | 退出码 | 原始输出文件 |", "|---|---|---|---|"]
    for item in v.commands:
        commands_md.append(f"| {item['step']} | `{item['command']}` | {item['exit_code']} | `{item['output']}` |")
    commands_md.extend(
        [
            "",
            "复跑顺序：",
            "",
            "```",
            "python -m record_wiring demo",
            "python tests/test_runner.py",
            "python verify/run_verification.py",
            "```",
            "",
        ]
    )
    write_text(RECORDS_DIR / "commands.md", "\n".join(commands_md))

    result = v.result()
    write_text(ROOT / "verify" / "verification_result.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    record_md = [
        "# 验证记录 · 订单 #1507 管理记录知识接线",
        "",
        f"- 生成时间（UTC）：{result['generated_at']}",
        f"- 断言总数：{result['assertions_total']}；通过：{result['assertions_passed']}；失败：{result['assertions_failed']}",
        f"- 结论：{'全部通过' if result['all_passed'] else '存在失败项'}",
        "",
        "| 序号 | 断言 | 预期 | 实际 | 结果 |",
        "|---|---|---|---|---|",
    ]
    for item in v.checks:
        record_md.append(
            f"| {item['index']} | {item['name']} | {item['expected']} | {item['actual']} | {'通过' if item['passed'] else '失败'} |"
        )
    record_md.append("")
    write_text(ROOT / "verify" / "verification_record.md", "\n".join(record_md))

    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    v.emit("")
    v.emit(f"{passed}/{len(v.checks)} assertions passed")
    write_text(RECORDS_DIR / "verification_output.txt", "\n".join(v.lines) + "\n")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
