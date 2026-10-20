"""零依赖测试运行器：纯 assert + 自统计。

运行：
    python tests/test_runner.py

输出最后一行固定为 `N/N tests passed`。
"""

from __future__ import annotations

import importlib
import inspect
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULES = [
    "tests.test_model_schema",
    "tests.test_privacy",
    "tests.test_store_ingest",
    "tests.test_access",
    "tests.test_citation_export",
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    total = 0
    passed = 0
    failures: list[tuple[str, str]] = []

    for module_name in MODULES:
        module = importlib.import_module(module_name)
        tests = [
            (name, member)
            for name, member in vars(module).items()
            if name.startswith("test_") and inspect.isfunction(member)
        ]
        for name, func in tests:
            total += 1
            label = f"{module_name}.{name}"
            try:
                func()
            except Exception:  # noqa: BLE001 - 测试运行器需要捕获全部失败
                failures.append((label, traceback.format_exc()))
                print(f"[FAIL] {label}")
            else:
                passed += 1
                print(f"[PASS] {label}")

    print("")
    for label, detail in failures:
        print(f"--- {label} ---")
        print(detail)

    print(f"{passed}/{total} tests passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
