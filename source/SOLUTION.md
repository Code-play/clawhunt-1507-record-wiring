【交付物获取方式】
本单交付物自包含，不依赖系列内其它订单，也不依赖任何外部服务或数据库。
仓库地址：
- 交付物仓库（含可浏览源码树 source/ 与打包文件）：https://github.com/Code-play/clawhunt-1507-record-wiring
打包下载：
- 打包下载（zip）：https://github.com/Code-play/clawhunt-1507-record-wiring/raw/main/1507-record-wiring.zip
若平台未展示链接，本文件正文已包含全部设计、样例、命令与验证输出，可直接按文复跑核对。

【需求理解】
订单 #1507「企业 Agent 系统 20/50｜管理记录知识接线」。
本单范围：接入授权的管理记录，保留来源、时间与访问权限。
验收标准：提供脱敏导入示例及可定位原始记录的引用。
交付要求：提交与本单相关的代码或配置、使用说明和验证记录；只能使用获授权或脱敏的资料。

把这句话拆成可验收的工程语义，本单解决五件事：
1. 来源不能是自由文本备注，必须是可解析指针 system + uri + hash（+ record_id），据此能定位原始记录；
2. 记录层 append-only（只追加不改写），保留版本与接收时间；
3. 每条记录必须带访问权限标签，检索/导出按权限过滤，并记录授权标记；
4. 导入幂等：同一 record_id + hash 重复导入不得产生重复行；
5. 脱敏要真的执行并留下前后对照，脱敏后的数据本身是交付产物。

本方案把这五件事分别落在 model.py / store.py / access.py / ingest.py / privacy.py 五个模块里，
并由 tests/test_runner.py（37 个单元测试）与 verify/run_verification.py（逐条断言，
断言数见验证记录）独立证明。全部数据均为合成数据，不包含任何真实姓名、账号或业务记录。

【交付边界】
包含：
- 可运行的标准库 Python 包 record_wiring，覆盖导入、存储、权限、脱敏、引用、导出、轨迹；
- 三份配置：记录 Schema、脱敏规则表、访问策略；
- 24 行合成原始记录（22 个记录 ID，其中 1 个双版本、1 行完全重复，用于验证幂等）；
- 单元测试、独立验收脚本、真实原始输出、四类交付产物。
不包含：
- 不接真实账号体系、不接真实数据库；权限模型是标签子集判断，可由企业 IAM 映射后替换；
- 不包含任何模型 API 调用，脱敏是规则表驱动的确定性替换，不是语义脱敏；
- 不替客户做数据授权谈判；真实数据须经平台沟通后提供，本单只使用合成数据。
可替换点：
- 换成真实记录时，只需按 config/records_schema.json 的字段生产 JSONL；
- 换脱敏规则只改 config/privacy_rules.json；
- 换角色与标签只改 config/access_policy.json；
- 代码不需要改动，验证脚本可原样复跑。

【记录 Schema 设计说明（逐字段）】
记录以 JSONL 一行一条，字段如下。

record_id：业务主键，格式 MR-YYYY-NNNN。它是引用、去重、权限判定的共同锚点。
version：整数，从 1 开始。同一 record_id 的新正文必须作为新版本追加，历史版本不覆盖。
record_type：记录类型枚举，如 meeting_minutes、policy_change、org_change、budget_approval、
  vendor_assessment、incident_review、audit_finding、contract_review、performance_review、
  procurement_request。枚举在 Schema 中登记，未登记类型直接拒绝导入。
title：标题，非空且不超过 120 字符。
body：正文。原始正文用于计算 hash；入库前必须整体脱敏，存储的是脱敏后的正文。
department：业务归属部门，用于人工检索，不参与授权判断。
occurred_at：业务发生时间，UTC ISO-8601，格式 YYYY-MM-DDTHH:MM:SSZ。
received_at：接收时间，同样格式，且不得早于 occurred_at；这是“记录何时进入平台”的证据。
source.system：来源系统标识，必须在 Schema 的 source_systems 白名单内，例如 wiki、hr-system、
  finance-erp、ops-jira、contract-system、audit-trail。
source.uri：原始记录的规范 URI，必须包含 scheme，例如 wiki://records/MR-2026-0001。
source.record_id：来源系统中的记录 ID，必须与 record_id 完全一致，防止串号。
source.hash：原始正文的 SHA-256（64 位小写十六进制）。校验器会重新计算并比对，不一致直接拒绝。
source.captured_at：采集时间，UTC ISO-8601。
source.source_file：源文件相对路径，由导入器回填，不手工填写。
source.line_no：源文件中的 1 起行号，由导入器回填。
source.byte_offset / source.byte_length：整行在源文件中的字节区间，由导入器回填。
source.body_offset / source.body_length：正文在源文件中的字节区间，由导入器回填；
  引用解析时按这个区间切片，重新计算 SHA-256 必须等于 source.hash。
access.labels：访问标签数组，不能为空。取值来自 access_policy.json 的 labels。
access.owner_role：业务归属角色，只用于审计，不直接授予读取权。
access.sensitivity：敏感级别 low / medium / high。
body_sha256：脱敏后正文的哈希，用于存储链完整性，与 source.hash 明确区分，避免混淆原始与脱敏产物。
raw_body_sha256：显式保存的原始正文哈希副本，便于审计时快速核对 source.hash。
ingested_at：导入时间。演示与验证使用固定确定性时钟，真实接入可由 --now 传入当前时间。
redaction：脱敏元数据，含引擎 ID、引擎版本、命中规则列表、命中次数、前后长度；
  只记录规则与计数，不记录原文，避免在存储层二次泄漏。

校验顺序：解析 JSON -> 构造 Record -> 校验必填/类型/时间/来源/权限 -> 重算 hash ->
定位正文字节 -> 脱敏 -> 去重与版本判定 -> 追加写入。任何一步失败都记录拒绝原因，不写入存储。

【整体架构（分层）】
配置层：config/records_schema.json、privacy_rules.json、access_policy.json。业务枚举、规则、
  角色全部外置，代码不硬编码。
模型层：model.py 定义 Record、SourcePointer、AccessTag；sha256_text 统一哈希口径。
校验层：schema.py 按配置校验字段、时间、来源白名单、hash、访问标签与角色。
脱敏层：privacy.py 先收集所有命中，再按“起点优先、长度优先、规则优先级”解决重叠，
  最后单遍重建字符串，保证 findings 的 start/end 能在原文上精确切片。
导入层：ingest.py 读取源文件字节，逐行计算整行与正文的字节区间，执行校验、脱敏、去重、
  版本提升，并写导入轨迹。
存储层：store.py 只以追加模式写入，每行带 seq、chain_prev、chain_hash；
  chain_hash 覆盖 seq、前一行哈希、record_id、version、原始 hash、脱敏后 hash。
  任意历史行被改写、删除或调序都会导致链校验失败。
权限层：access.py 用“记录标签集合是角色授权集合的子集”判定；未知角色与空标签默认拒绝。
  每次判定生成 AD-NNNN 决策号，导出记录写入 _grant 标记，拒绝项进入访问日志。
引用层：citation.py 把来源指针编码成 clawhunt:// URI，并提供 resolve 反向切片校验。
导出层：export.py 生成脱敏记录快照、导入报告、脱敏前后对照、按角色的导出。
轨迹层：trace.py 使用确定性时钟输出 JSONL，便于复跑比对。
入口层：cli.py 提供 demo / ingest / query / export / cite / integrity / check-citations。

【目录树】
1507-record-wiring/
  SOLUTION.md
  README.md
  DELIVERY.md
  .gitignore
  record_wiring/
    __init__.py  __main__.py  cli.py
    model.py  config.py  schema.py  privacy.py
    ingest.py  store.py  access.py  citation.py
    export.py  trace.py
  config/
    records_schema.json  privacy_rules.json  access_policy.json
  samples/
    raw_records.jsonl
  tests/
    __init__.py  helpers.py  test_runner.py
    test_model_schema.py  test_privacy.py  test_store_ingest.py
    test_access.py  test_citation_export.py
  verify/
    run_verification.py  verification_record.md  verification_result.json
    records/
      verification_output.txt  assertions.txt  tests_output.txt
      ingest_run1.txt  ingest_run2.txt  demo_run.txt
      environment.txt  commands.md
  out/
    records_imported.jsonl  import_report.md  redaction_diff.md
    citations.jsonl  access_log.jsonl  export_analyst.jsonl  trace.jsonl

【运行方式】
环境：Python 3.13（实测 3.13.9），仅标准库，零第三方依赖，不联网。
三步复跑：
  cd 1507-record-wiring
  python -m record_wiring demo
  python tests/test_runner.py
  python verify/run_verification.py
demo 的实测输出：
  订单 #1507 管理记录知识接线 - demo
  输入: samples/raw_records.jsonl
  总行数=24 新增=23 去重跳过=1 版本提升=0 拒绝=0
  存储行数=23 脱敏记录=24 脱敏命中=70
  引用=23 可定位=23 链校验=通过
  角色可见: hr_admin=6 finance_controller=3 ops_lead=3 legal_counsel=2 compliance_auditor=23 analyst=3 intern=1
其他常用命令：
  python -m record_wiring ingest --input samples/raw_records.jsonl --store .store/records.jsonl
  python -m record_wiring query --role analyst
  python -m record_wiring export --role analyst --out out/export_analyst.jsonl
  python -m record_wiring cite --record-id MR-2026-0001
  python -m record_wiring integrity
  python -m record_wiring check-citations
注意：直接使用 python 运行，不要用 conda run 包裹中文输出；若必须使用，先设
PYTHONIOENCODING=utf-8。demo 会重置 .store 下的演示库（演示库是可丢弃的），
ingest 子命令则严格只追加、不清空。

【逐条验收对照表】
验收标准：提供脱敏导入示例及可定位原始记录的引用。
| 验收点 | 交付物 / 代码 | 可验证证据 |
|---|---|---|
| 脱敏导入示例 | samples/raw_records.jsonl（24 行合成原始记录）、privacy.py、ingest.py | out/records_imported.jsonl 23 行全部为脱敏正文；out/redaction_diff.md 给出 23 条前后对照；验证脚本断言无残留手机号/邮箱/身份证/银行卡/员工编号/人名 |
| 可定位原始记录的引用 | citation.py、out/citations.jsonl | 23 条引用全部可按 body_offset/length 切片，sha256(slice) 等于引用中的 hash；同时校验 line_no 与源文件中该行 record_id |
| 买家关注点 1：来源是可解析指针 | model.py 的 SourcePointer、Schema 校验 | 四要素 system/uri/record_id/hash 必填；hash 重算不一致拒绝；store 与 citations 均保留四要素 |
| 买家关注点 2：append-only 与版本 | store.py 的哈希链、ingest.py 的版本提升 | 重复导入文件字节不变且前缀一致；MR-2026-0010 同时保留 v1/v2；历史行 chain_hash 校验通过 |
| 买家关注点 3：访问标签与过滤 | access.py、config/access_policy.json | 23 条记录均有标签；analyst 看不到 HR 记录，compliance_auditor 可看全部；导出记录带 _grant，拒绝项进 access_log.jsonl |
| 买家关注点 4：幂等导入 | ingest.py 的 (record_id, hash) 键 | 第一次 24 行新增 23、文件内重复跳过 1；第二次新增 0、整份跳过 24、行数仍 23 |
| 买家关注点 5：脱敏真实执行 | privacy.py、config/privacy_rules.json | 24 行输入命中 70 次，23 行入库去重后 67 次；token 由 sha256(规则+原值) 前 6 位生成，同值同 token；对照表逐条显示前后差异 |
| 使用说明 | README.md | 安装/运行/测试三步，含 CLI 示例 |
| 验证记录 | verify/run_verification.py、verify/records/ | 真实原始输出落盘，最终输出 82/82 assertions passed |
| 只用授权/脱敏资料 | samples 全合成、无真实账号 | 文档与数据均声明合成；测试与验收只读本地文件 |

【验证结果（真实原始输出）】
单元测试：python tests/test_runner.py
  37/37 tests passed
验收脚本：python verify/run_verification.py
  82/82 assertions passed
  末行原文见 verify/records/verification_output.txt；该文件同时保存每条断言的预期、实际与 PASS/FAIL。
原始输出文件：
  verify/records/tests_output.txt     测试运行器完整输出
  verify/records/ingest_run1.txt      第一次导入 CLI 输出（新增 23、去重 1）
  verify/records/ingest_run2.txt      第二次导入 CLI 输出（新增 0、整份去重 24）
  verify/records/demo_run.txt         复跑 demo 输出（逐字节一致）
  verify/records/verification_output.txt  验收脚本完整输出
  verify/records/assertions.txt       每条断言一行
  verify/records/environment.txt      Python 版本与平台
  verify/records/commands.md          命令、退出码、原始输出对照
关键断言（摘自脚本，非人工转述）：
  [PASS] 第一次导入：新增 23 | 预期: 23 | 实际: 23
  [PASS] 第一次导入：去重 1（文件内重复行） | 预期: 1 | 实际: 1
  [PASS] 重复导入后文件字节不变 | 预期: sha256 相同 | 实际: True
  [PASS] analyst 无法读取 HR 记录 | 预期: allowed=False | 实际: allowed=False missing=['hr', 'sensitive']
  [PASS] 导入产物无残留敏感信息 | 预期: 0 处 | 实际: 0
  [PASS] 每条引用都能切片定位并哈希一致 | 预期: 23/23 | 实际: 全部通过
  [PASS] demo 两次产物逐字节一致 | 预期: 全部相同 | 实际: 全部相同
验收脚本还会扫描全部文件，断言 UTF-8 无 BOM、文件名全 ASCII、正文无 emoji、
Python 导入全部来自标准库，以及 SOLUTION 含两个链接占位。

【原始记录定位引用示例】
下面是 out/citations.jsonl 的第一条（原文照抄）：
  record_id : MR-2026-0001
  version   : 1
  system    : wiki
  source_uri: wiki://records/MR-2026-0001
  hash      : 68913b3efb4a59b1d51496bde130699c9b9f01252d1aa2fceb6889e54bceeef3
  line_no   : 1
  byte_offset: 0
  byte_length: 743
  body_offset: 118
  body_length: 185
  citation  : clawhunt://wiki/samples/raw_records.jsonl?record_id=MR-2026-0001&version=1
              &hash=68913b3efb4a59b1d51496bde130699c9b9f01252d1aa2fceb6889e54bceeef3
              &line=1&byte_offset=0&byte_length=743&body_offset=118&body_length=185
  human     : samples/raw_records.jsonl 第 1 行；正文字节区间 118-303；sha256=68913b...
定位验证方式（citation.resolve_citation 的真实行为）：
  1. 解析 URI 得到 relative=samples/raw_records.jsonl、line=1、body_offset=118、body_length=185；
  2. 读取源文件字节，取 raw[118:303]，解码为原始正文；
  3. 计算 sha256(raw[118:303])，必须等于 hash；
  4. 读取整行区间 raw[0:743]，JSON 解析后 record_id 必须是 MR-2026-0001；
  5. 三个条件任一不满足，resolve 抛 CitationError，验收断言失败。
切片原文以“会议由张伟主持”开头，长 185 字节；入库正文以“会议由[NAME:3514db]主持”开头，
差异见 out/redaction_diff.md 第 1 行。原始正文不写入任何产物，只存在于 samples 源文件。

【已知限制与使用前提】
1. 人名脱敏是词表匹配，词表来自合成数据。真实接入时需要把真实人名清单替换进
   privacy_rules.json 的 name_terms，或接企业主数据接口；词表外的人名不会被识别。
2. 规则脱敏只覆盖配置中的手机号、邮箱、身份证、银行卡、员工编号与人名；
   地址、自由文本中的职务等未覆盖，需要按合规要求扩充规则。
3. 访问控制是标签子集模型，不含时间、用途、审批流等上下文；真实场景可在外层接 IAM，
   把角色映射为标签集合后再调用本模块。
4. 演示库重置只发生在 demo 子命令；生产导入请使用 ingest，它不会删除或重写任何历史行。
5. 时间使用固定演示时钟以保证验证可复现；真实接入应通过 --now 传入采集时刻。
6. 脱敏 token 不可逆且稳定，适合做关联分析；若需要可逆映射，应由客户侧密钥托管系统实现，
   本单不保存映射表。
7. 本单不联网、不调用模型 API、不使用真实账号；所有姓名、电话、证件号、卡号、邮箱均为合成样例。
