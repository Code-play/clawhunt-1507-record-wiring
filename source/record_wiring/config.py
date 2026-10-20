"""配置加载：记录 Schema、脱敏规则、访问策略。

所有配置都是 JSON，零第三方依赖。路径默认相对于项目根目录。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
SAMPLES_FILE = PROJECT_ROOT / "samples" / "raw_records.jsonl"
STORE_FILE = PROJECT_ROOT / ".store" / "records.jsonl"
OUT_DIR = PROJECT_ROOT / "out"
VERIFY_RECORDS_DIR = PROJECT_ROOT / "verify" / "records"

SCHEMA_FILE = CONFIG_DIR / "records_schema.json"
PRIVACY_FILE = CONFIG_DIR / "privacy_rules.json"
ACCESS_FILE = CONFIG_DIR / "access_policy.json"

# 确定性导入时钟：用于可复现验证；真实接入时由调用方传入当前时间。
DEFAULT_INGEST_AT = "2026-10-20T09:00:00Z"


class ConfigError(ValueError):
    """配置文件缺失或结构不合法。"""


def load_json(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ConfigError(f"配置文件不是 UTF-8: {path}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"配置文件 JSON 解析失败: {path}: {exc}") from exc


def load_records_schema(path: Path | None = None) -> dict[str, Any]:
    data = load_json(path or SCHEMA_FILE)
    for key in ("schema_id", "record_types", "sensitivity_levels", "source_systems"):
        if key not in data:
            raise ConfigError(f"records_schema.json 缺少 {key}")
    return data


def load_privacy_rules(path: Path | None = None) -> dict[str, Any]:
    data = load_json(path or PRIVACY_FILE)
    if not data.get("rules"):
        raise ConfigError("privacy_rules.json 缺少 rules")
    for rule in data["rules"]:
        if "id" not in rule or "category" not in rule or "kind" not in rule:
            raise ConfigError("privacy_rules.json 的规则必须包含 id/category/kind")
        if rule["kind"] == "regex" and "pattern" not in rule:
            raise ConfigError(f"正则规则 {rule['id']} 缺少 pattern")
    return data


def load_access_policy(path: Path | None = None) -> dict[str, Any]:
    data = load_json(path or ACCESS_FILE)
    if not data.get("roles"):
        raise ConfigError("access_policy.json 缺少 roles")
    if not data.get("labels"):
        raise ConfigError("access_policy.json 缺少 labels")
    return data


def default_paths() -> dict[str, Path]:
    return {
        "project_root": PROJECT_ROOT,
        "config_dir": CONFIG_DIR,
        "samples": SAMPLES_FILE,
        "store": STORE_FILE,
        "out": OUT_DIR,
    }
