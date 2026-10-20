"""脱敏引擎：规则表驱动，确定性替换，保留脱敏前后对照所需的信息。

规则来自 config/privacy_rules.json：
- kind=regex  按正则匹配（手机号/邮箱/身份证/银行卡/员工编号）
- kind=terms  按词表匹配（人名，合成数据里的虚构姓名）
替换 token 形如 [PHONE:3f9a01]，由 sha256(rule_id|value) 前 6 位决定：
同一原文每次得到同一 token，可跨记录对齐，也不可逆推原文。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


class PrivacyError(ValueError):
    """脱敏规则配置或执行错误。"""


@dataclass(frozen=True)
class RedactionFinding:
    rule_id: str
    category: str
    start: int
    end: int
    value: str
    token: str

    def as_dict(self, *, include_value: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "rule_id": self.rule_id,
            "category": self.category,
            "start": self.start,
            "end": self.end,
            "token": self.token,
        }
        if include_value:
            data["value"] = self.value
        return data


@dataclass(frozen=True)
class _CompiledRule:
    rule_id: str
    category: str
    kind: str
    priority: int
    pattern: re.Pattern[str] | None = None


class PrivacyEngine:
    def __init__(self, config: Mapping[str, Any]) -> None:
        self.rules_id = str(config.get("rules_id", "privacy-rules"))
        self.version = int(config.get("version", 1))
        self.replacement_template = str(config.get("replacement_template", "[{category}:{token}]"))
        self.name_terms = tuple(str(x) for x in config.get("name_terms", []))
        compiled: list[_CompiledRule] = []
        for index, rule in enumerate(config.get("rules", [])):
            kind = rule.get("kind")
            priority = int(rule.get("priority", index + 1))
            if kind == "regex":
                try:
                    pattern = re.compile(str(rule["pattern"]))
                except re.error as exc:
                    raise PrivacyError(f"规则 {rule.get('id')} 正则非法: {exc}") from exc
                compiled.append(_CompiledRule(str(rule["id"]), str(rule["category"]), kind, priority, pattern))
            elif kind == "terms":
                terms = rule.get("terms", self.name_terms)
                if not terms:
                    raise PrivacyError(f"词表规则 {rule.get('id')} 没有词条")
                alternation = "|".join(re.escape(str(term)) for term in sorted(terms, key=len, reverse=True))
                compiled.append(
                    _CompiledRule(str(rule["id"]), str(rule["category"]), kind, priority, re.compile(alternation))
                )
            else:
                raise PrivacyError(f"未知规则类型: {kind!r}")
        self._rules = tuple(compiled)
        self._by_id = {rule.rule_id: rule for rule in self._rules}

    @property
    def rule_ids(self) -> tuple[str, ...]:
        return tuple(rule.rule_id for rule in self._rules)

    def _token(self, rule: _CompiledRule, value: str) -> str:
        digest = hashlib.sha256(f"{rule.rule_id}|{value}".encode("utf-8")).hexdigest()[:6]
        return self.replacement_template.format(category=rule.category, token=digest)

    def find(self, text: str) -> list[RedactionFinding]:
        candidates: list[tuple[int, int, int, RedactionFinding]] = []
        for rule in self._rules:
            assert rule.pattern is not None
            for match in rule.pattern.finditer(text):
                if match.start() == match.end():
                    continue
                value = match.group(0)
                finding = RedactionFinding(
                    rule_id=rule.rule_id,
                    category=rule.category,
                    start=match.start(),
                    end=match.end(),
                    value=value,
                    token=self._token(rule, value),
                )
                candidates.append((match.start(), -(match.end() - match.start()), rule.priority, finding))
        # 并列时保留优先级高的规则；再按出现位置推进，保证不重叠。
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        accepted: list[RedactionFinding] = []
        cursor = -1
        for _start, _neg_len, _priority, finding in candidates:
            if finding.start < cursor:
                continue
            accepted.append(finding)
            cursor = finding.end
        return accepted

    def redact(self, text: str) -> tuple[str, list[RedactionFinding]]:
        findings = self.find(text)
        if not findings:
            return text, []
        parts: list[str] = []
        cursor = 0
        for finding in findings:
            parts.append(text[cursor : finding.start])
            parts.append(finding.token)
            cursor = finding.end
        parts.append(text[cursor:])
        return "".join(parts), findings

    def residue(self, text: str) -> list[RedactionFinding]:
        """脱敏后自检：再次扫描，理论上必须为空。"""
        return self.find(text)

    def rule_summary(self, findings: Iterable[RedactionFinding]) -> list[str]:
        seen: list[str] = []
        for finding in findings:
            if finding.rule_id not in seen:
                seen.append(finding.rule_id)
        return seen


def load_engine(config: Mapping[str, Any]) -> PrivacyEngine:
    return PrivacyEngine(config)
