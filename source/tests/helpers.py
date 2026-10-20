"""测试公共夹具：读取真实 samples，导入到 tests/.tmp 下的临时库。"""

from __future__ import annotations

import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from record_wiring.access import AccessController, load_policy  # noqa: E402
from record_wiring.config import SAMPLES_FILE, load_access_policy, load_privacy_rules, load_records_schema  # noqa: E402
from record_wiring.ingest import Ingestor  # noqa: E402
from record_wiring.model import Record  # noqa: E402
from record_wiring.privacy import load_engine  # noqa: E402
from record_wiring.schema import load_schema  # noqa: E402
from record_wiring.store import AppendOnlyStore  # noqa: E402

TMP_ROOT = ROOT / "tests" / ".tmp"


def objects() -> tuple[Any, Any, Any]:
    return (
        load_schema(load_records_schema()),
        load_engine(load_privacy_rules()),
        load_policy(load_access_policy()),
    )


def raw_lines() -> list[dict[str, Any]]:
    return [json.loads(line) for line in SAMPLES_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]


def raw_record(index: int = 0) -> Record:
    return Record.from_dict(raw_lines()[index])


@contextmanager
def ingested(name: str = "case") -> Iterator[dict[str, Any]]:
    base = TMP_ROOT / name
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True, exist_ok=True)
    schema, privacy, policy = objects()
    store = AppendOnlyStore(base / "records.jsonl")
    ingestor = Ingestor(store, schema, privacy, policy)
    report = ingestor.ingest_file(SAMPLES_FILE)
    rows = store.rows()
    try:
        yield {
            "base": base,
            "store": store,
            "report": report,
            "rows": rows,
            "schema": schema,
            "privacy": privacy,
            "policy": policy,
            "controller": AccessController(policy),
        }
    finally:
        shutil.rmtree(base, ignore_errors=True)


def record_of(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return row["record"]
