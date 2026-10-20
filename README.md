# 管理记录知识接线（订单 #1507）

把授权的管理记录接入知识层：来源可定位、存储只追加、访问有标签、导入幂等、脱敏可对照。
全部数据为合成数据，代码仅使用 Python 标准库。

## 快速上手（三步）

```bash
cd 1507-record-wiring

# 1. 运行演示：重置演示库，生成 out/ 全部产物
python -m record_wiring demo

# 2. 单元测试（纯 assert，无 pytest）
python tests/test_runner.py

# 3. 独立验收（逐条断言，原始输出写入 verify/records/）
python verify/run_verification.py
```

预期：第 2 步最后一行 `37/37 tests passed`；第 3 步最后一行 `82/82 assertions passed`
（与 verify/records/verification_output.txt 一致）。

## out/ 产物

| 文件 | 内容 |
|---|---|
| `out/records_imported.jsonl` | 脱敏后的导入产物，23 行，含访问标签与来源定位 |
| `out/import_report.md` | 导入统计：总行数 / 新增 / 去重 / 版本提升 / 拒绝 |
| `out/redaction_diff.md` | 脱敏前后对照表（23 条），原文来自引用切片 |
| `out/citations.jsonl` | 每条记录的可定位引用：system + uri + hash + record_id + 行号 + 字节偏移 |
| `out/access_log.jsonl` | 按角色的授权判定（含拒绝项与 decision_id） |
| `out/export_analyst.jsonl` | analyst 角色的过滤导出，每条带 `_grant` |
| `out/trace.jsonl` | 导入与导出轨迹（确定性时钟） |

## 常用命令

```bash
# 只追加导入（不清空，可重复执行）
python -m record_wiring ingest --input samples/raw_records.jsonl --store .store/records.jsonl

# 按角色检索
python -m record_wiring query --role analyst

# 按角色导出（带授权标记）
python -m record_wiring export --role analyst --out out/export_analyst.jsonl

# 单条引用
python -m record_wiring cite --record-id MR-2026-0001

# 存储哈希链校验 / 引用逐条解析
python -m record_wiring integrity
python -m record_wiring check-citations
```

## 目录

```
record_wiring/   model schema privacy ingest store access citation export trace cli
config/          records_schema.json privacy_rules.json access_policy.json
samples/         raw_records.jsonl（24 行合成原始记录）
tests/           test_runner.py 与 5 个测试模块
verify/          run_verification.py + records/ 真实原始输出
out/             交付产物
```

## 说明

- 来源指针：`system + uri + record_id + hash`；hash 对原始正文做 SHA-256。
- append-only：每行带 seq 与哈希链；重复导入不新增、不改写。
- 权限：记录标签必须全部落在角色授权集合内；导出写入 `_grant`，拒绝写日志。
- 脱敏：手机号、邮箱、身份证、银行卡、员工编号、人名；token 稳定且不可逆。

运行注意：直接用 `python`，不要用 `conda run` 包裹中文输出；若必须使用，先设
`PYTHONIOENCODING=utf-8`。
