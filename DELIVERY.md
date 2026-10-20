# 交付清单与验收对照 · 订单 #1507

**订单**：企业 Agent 系统 20/50｜管理记录知识接线
**本单范围**：接入授权的管理记录，保留来源、时间与访问权限。
**验收标准**：提供脱敏导入示例及可定位原始记录的引用。

## 交付清单

| 类别 | 文件 | 作用 |
|---|---|---|
| 交付说明 | `SOLUTION.md` | 需求理解、Schema 逐字段、架构、目录、运行、验收对照、真实输出、引用示例、限制 |
| 使用说明 | `README.md` | 安装 / 运行 / 测试三步与 CLI 示例 |
| 本文件 | `DELIVERY.md` | 交付清单 + 文件到验收点的映射 |
| 包 | `record_wiring/model.py` | Record / SourcePointer / AccessTag |
| 包 | `record_wiring/config.py` | 三份配置加载与路径 |
| 包 | `record_wiring/schema.py` | 字段、时间、来源、hash、权限标签校验 |
| 包 | `record_wiring/privacy.py` | 规则表脱敏、token、前后对照所需 findings |
| 包 | `record_wiring/ingest.py` | 校验、定位、脱敏、去重、版本提升、幂等导入 |
| 包 | `record_wiring/store.py` | append-only 存储、哈希链、版本索引 |
| 包 | `record_wiring/access.py` | 标签子集授权、决策号、授权标记 |
| 包 | `record_wiring/citation.py` | 引用 URI 生成与切片解析 |
| 包 | `record_wiring/export.py` | 导入报告、对照表、角色导出 |
| 包 | `record_wiring/trace.py` | 确定性轨迹 |
| 包 | `record_wiring/cli.py` | demo / ingest / query / export / cite / integrity |
| 配置 | `config/records_schema.json` | 记录类型、字段约束、来源系统白名单 |
| 配置 | `config/privacy_rules.json` | 手机号、邮箱、身份证、银行卡、员工编号、人名规则 |
| 配置 | `config/access_policy.json` | 标签定义与 7 个角色授权集合 |
| 样例 | `samples/raw_records.jsonl` | 24 行合成原始管理记录（含双版本与重复行） |
| 测试 | `tests/test_runner.py` + 5 个模块 | 37 个单元测试，纯 assert 自统计 |
| 验收 | `verify/run_verification.py` | 逐条断言，原始输出落盘 |
| 输出 | `out/records_imported.jsonl` | 脱敏导入产物 23 行 |
| 输出 | `out/import_report.md` | 导入统计 |
| 输出 | `out/redaction_diff.md` | 脱敏前后对照 23 条 |
| 输出 | `out/citations.jsonl` | 23 条可定位引用 |
| 输出 | `out/access_log.jsonl` | 授权判定日志 |
| 输出 | `out/export_analyst.jsonl` | analyst 过滤导出（3 条） |

## 验收点对照

| 验收点 | 证明文件 | 验证方式 |
|---|---|---|
| 脱敏导入示例 | `samples/raw_records.jsonl`、`out/records_imported.jsonl`、`out/redaction_diff.md` | 23 行产物全部含 `redaction` 元数据；对照表 23 条，前后不同；无残留 PII |
| 可定位原始记录的引用 | `out/citations.jsonl`、`record_wiring/citation.py` | 每条引用按 `body_offset/body_length` 切片，`sha256(slice)` 等于引用 hash；行号与源记录一致 |
| 来源是可解析指针 | Schema + `model.py` + 存储 | `system/uri/record_id/hash` 必填；hash 重算不一致直接拒绝 |
| append-only 保留版本与接收时间 | `store.py`、存储文件 | 重复导入字节不变且为原文件前缀；MR-2026-0010 保留 v1/v2；每行含 `received_at` 与 `ingested_at` |
| 访问标签与权限过滤 | `access.py`、`access_policy.json`、`access_log.jsonl` | 23/23 有标签；analyst 拒绝 HR，合规审计员可见 23；导出带 `_grant` |
| 幂等导入 | `ingest.py` | 第一次 24 行新增 23、跳过 1；第二次新增 0、跳过 24；行数 23 |
| 脱敏真实执行 | `privacy.py`、`redaction_diff.md` | 24 行输入命中 70 次（入库 23 行去重后 67 次）；同值同 token；脱敏后自检无残留 |
| 使用说明 | `README.md` | 三步命令与产物说明 |
| 验证记录 | `verify/records/` | tests_output、ingest_run1/2、demo_run、verification_output、assertions、commands |

## 复跑

```bash
python -m record_wiring demo
python tests/test_runner.py
python verify/run_verification.py
```

实测结果：`37/37 tests passed`，`82/82 assertions passed`，demo 两次产物逐字节一致。
验收脚本同时检查文件齐全、UTF-8 无 BOM、文件名全 ASCII、无 emoji、仅标准库导入，
以及 `SOLUTION.md` 中的两个链接占位。
