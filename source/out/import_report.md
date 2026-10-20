# 导入报告（脱敏后）

- 生成时间（UTC）：2026-10-20T09:30:00Z
- 输入文件：`samples/raw_records.jsonl`
- 总行数：24
- 新增行数：23
- 去重跳过：1
- 版本提升：0
- 校验拒绝：0
- 存储总行数：23
- 含脱敏字段的记录：24
- 脱敏命中次数：70

## 逐条结果

| 序号 | 记录 | 版本 | 类型 | 访问标签 | 敏感级 | 发生时间 | 脱敏命中 | 来源定位 |
|---|---|---|---|---|---|---|---|---|
| 1 | MR-2026-0001 | 1 | meeting_minutes | internal,finance | medium | 2026-03-02T09:00:00Z | R-NAME,R-PHONE-CN,R-EMAIL (5) | samples/raw_records.jsonl:1 |
| 2 | MR-2026-0002 | 1 | org_change | internal,hr,sensitive | high | 2026-03-03T14:00:00Z | R-NAME,R-EMPID,R-PHONE-CN (5) | samples/raw_records.jsonl:2 |
| 3 | MR-2026-0003 | 1 | budget_approval | internal,finance | medium | 2026-03-04T11:30:00Z | R-NAME,R-EMAIL (3) | samples/raw_records.jsonl:3 |
| 4 | MR-2026-0004 | 1 | incident_review | internal,ops | medium | 2026-03-11T18:00:00Z | R-NAME,R-PHONE-CN (3) | samples/raw_records.jsonl:5 |
| 5 | MR-2026-0005 | 1 | contract_review | internal,legal,finance,sensitive | high | 2026-03-05T10:00:00Z | R-NAME,R-EMAIL,R-PHONE-CN,R-BANKCARD (4) | samples/raw_records.jsonl:6 |
| 6 | MR-2026-0006 | 1 | audit_finding | internal,audit,finance,sensitive | high | 2026-03-06T09:30:00Z | R-NAME,R-EMPID,R-IDCARD (5) | samples/raw_records.jsonl:7 |
| 7 | MR-2026-0007 | 1 | policy_change | internal,legal,audit | medium | 2026-03-07T15:00:00Z | R-NAME,R-EMAIL (2) | samples/raw_records.jsonl:8 |
| 8 | MR-2026-0008 | 1 | vendor_assessment | internal,ops,legal | medium | 2026-03-08T10:20:00Z | R-NAME,R-PHONE-CN (2) | samples/raw_records.jsonl:9 |
| 9 | MR-2026-0009 | 1 | performance_review | internal,hr,sensitive | high | 2026-03-09T09:00:00Z | R-NAME,R-EMAIL (5) | samples/raw_records.jsonl:10 |
| 10 | MR-2026-0010 | 1 | meeting_minutes | internal,analytics | low | 2026-03-10T10:00:00Z | R-NAME (2) | samples/raw_records.jsonl:11 |
| 11 | MR-2026-0010 | 2 | meeting_minutes | internal,analytics | low | 2026-03-17T10:00:00Z | R-NAME (3) | samples/raw_records.jsonl:12 |
| 12 | MR-2026-0011 | 1 | procurement_request | internal | low | 2026-03-12T09:40:00Z | R-NAME,R-PHONE-CN (2) | samples/raw_records.jsonl:13 |
| 13 | MR-2026-0012 | 1 | incident_review | internal,ops | medium | 2026-03-18T16:00:00Z | R-NAME,R-PHONE-CN (2) | samples/raw_records.jsonl:14 |
| 14 | MR-2026-0013 | 1 | audit_finding | internal,audit,sensitive | high | 2026-03-19T10:00:00Z | R-NAME,R-EMPID,R-EMAIL (3) | samples/raw_records.jsonl:15 |
| 15 | MR-2026-0014 | 1 | contract_review | internal,legal,sensitive | high | 2026-03-20T11:00:00Z | R-NAME,R-PHONE-CN (2) | samples/raw_records.jsonl:16 |
| 16 | MR-2026-0015 | 1 | budget_approval | internal,finance,hr | medium | 2026-03-21T09:15:00Z | R-NAME,R-EMPID (2) | samples/raw_records.jsonl:17 |
| 17 | MR-2026-0016 | 1 | meeting_minutes | internal,ops,audit | medium | 2026-03-22T14:00:00Z | R-NAME,R-EMAIL (3) | samples/raw_records.jsonl:18 |
| 18 | MR-2026-0017 | 1 | org_change | internal,hr | medium | 2026-03-23T10:00:00Z | R-NAME,R-PHONE-CN (3) | samples/raw_records.jsonl:19 |
| 19 | MR-2026-0018 | 1 | policy_change | internal,hr | low | 2026-03-24T09:00:00Z | R-EMAIL (1) | samples/raw_records.jsonl:20 |
| 20 | MR-2026-0019 | 1 | vendor_assessment | internal,finance,legal | medium | 2026-03-25T11:00:00Z | R-NAME,R-PHONE-CN (2) | samples/raw_records.jsonl:21 |
| 21 | MR-2026-0020 | 1 | procurement_request | internal,ops,finance | medium | 2026-03-26T10:30:00Z | R-NAME,R-EMAIL (2) | samples/raw_records.jsonl:22 |
| 22 | MR-2026-0021 | 1 | performance_review | internal,hr,sensitive | high | 2026-03-27T15:00:00Z | R-NAME,R-PHONE-CN (4) | samples/raw_records.jsonl:23 |
| 23 | MR-2026-0022 | 1 | audit_finding | internal,audit,legal,sensitive | high | 2026-03-28T09:00:00Z | R-NAME,R-EMAIL (2) | samples/raw_records.jsonl:24 |
