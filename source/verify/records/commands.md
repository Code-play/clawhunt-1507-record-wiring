# 验证命令与原始输出对照

运行时间（UTC）：2026-10-20T04:18:45.342053+00:00

| 步骤 | 命令 | 退出码 | 原始输出文件 |
|---|---|---|---|
| 第一次导入 | `C:\Users\18777\anaconda3\python.exe -m record_wiring ingest --store D:\works\clawhunt-agent\deliverables\1507-record-wiring\verify\_tmp_verify\records.jsonl --trace D:\works\clawhunt-agent\deliverables\1507-record-wiring\verify\_tmp_verify\ingest_trace.jsonl` | 0 | `verify/records/ingest_run1.txt` |
| 第二次导入（幂等） | `C:\Users\18777\anaconda3\python.exe -m record_wiring ingest --store D:\works\clawhunt-agent\deliverables\1507-record-wiring\verify\_tmp_verify\records.jsonl` | 0 | `verify/records/ingest_run2.txt` |
| 单元测试 | `C:\Users\18777\anaconda3\python.exe tests/test_runner.py` | 0 | `verify/records/tests_output.txt` |
| 复跑 demo | `C:\Users\18777\anaconda3\python.exe -m record_wiring demo` | 0 | `verify/records/demo_run.txt` |

复跑顺序：

```
python -m record_wiring demo
python tests/test_runner.py
python verify/run_verification.py
```
