"""访问控制：按角色授予的标签集合过滤记录，并产出可审计的授权标记。

规则：
- 记录必须带标签（Schema 已强制）。
- 角色拥有 granted_labels；仅当「记录标签集合是角色标签集合的子集」时允许读取。
- 未知角色、空标签记录一律拒绝（default_deny）。
- 每次判定都会生成 decision_id，导出记录上写入 _grant 标记，拒绝项写入访问日志。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


class AccessError(ValueError):
    """访问策略配置错误。"""


def _labels_of(record: Mapping[str, Any]) -> tuple[str, ...]:
    access = record.get("access")
    if not isinstance(access, Mapping):
        return ()
    labels = access.get("labels", ())
    return tuple(str(item) for item in labels)


@dataclass(frozen=True)
class AccessPolicy:
    policy_id: str
    labels: Mapping[str, Any]
    roles: Mapping[str, Any]
    default_deny: bool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AccessPolicy":
        if not data.get("labels"):
            raise AccessError("access_policy.labels 不能为空")
        roles = data.get("roles")
        if not isinstance(roles, Mapping) or not roles:
            raise AccessError("access_policy.roles 不能为空")
        for role, spec in roles.items():
            if not isinstance(spec, Mapping) or "granted_labels" not in spec:
                raise AccessError(f"角色 {role} 缺少 granted_labels")
            unknown = set(spec["granted_labels"]) - set(data["labels"])
            if unknown:
                raise AccessError(f"角色 {role} 授予了未登记标签: {sorted(unknown)}")
        return cls(
            policy_id=str(data.get("policy_id", "access-policy")),
            labels=data["labels"],
            roles=roles,
            default_deny=bool(data.get("default_deny", True)),
        )

    def label_names(self) -> tuple[str, ...]:
        return tuple(self.labels.keys())

    def role_names(self) -> tuple[str, ...]:
        return tuple(self.roles.keys())

    def granted_labels(self, role: str) -> frozenset[str]:
        spec = self.roles.get(role)
        if not isinstance(spec, Mapping):
            return frozenset()
        return frozenset(str(item) for item in spec.get("granted_labels", ()))

    def allows(self, role: str, labels: Iterable[str]) -> tuple[bool, tuple[str, ...]]:
        required = frozenset(str(item) for item in labels)
        if not required:
            return False, ()
        granted = self.granted_labels(role)
        if role not in self.roles:
            return False, tuple(sorted(required))
        missing = tuple(sorted(required - granted))
        return (not missing), missing


class AccessController:
    def __init__(self, policy: AccessPolicy, *, start_at: str = "2026-10-20T10:00:00Z", step_seconds: int = 1) -> None:
        self.policy = policy
        self._clock = datetime.strptime(start_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self._step = timedelta(seconds=step_seconds)
        self._seq = 0
        self.decisions: list[dict[str, Any]] = []

    def _at(self) -> str:
        value = self._clock + self._seq * self._step
        self._seq += 1
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")

    def decide(self, record: Mapping[str, Any], role: str) -> dict[str, Any]:
        labels = _labels_of(record)
        allowed, missing = self.policy.allows(role, labels)
        if not labels:
            reason = "记录缺少访问标签，按默认拒绝处理"
        elif role not in self.policy.roles:
            reason = f"未知角色 {role!r}，按默认拒绝处理"
        elif allowed:
            reason = "记录标签均在角色授权范围内"
        else:
            reason = "角色缺少标签: " + ",".join(missing)
        decision = {
            "decision_id": f"AD-{len(self.decisions) + 1:04d}",
            "policy_id": self.policy.policy_id,
            "at": self._at(),
            "role": role,
            "record_id": str(record.get("record_id", "")),
            "version": record.get("version"),
            "labels": sorted(labels),
            "missing_labels": list(missing),
            "allowed": bool(allowed),
            "reason": reason,
        }
        self.decisions.append(decision)
        return decision

    def can_read(self, record: Mapping[str, Any], role: str) -> bool:
        return bool(self.decide(record, role)["allowed"])

    def filter_rows(self, rows: Iterable[Mapping[str, Any]], role: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        allowed_rows: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        for row in rows:
            record = row.get("record", row)
            decision = self.decide(record, role)
            decisions.append(decision)
            if decision["allowed"]:
                allowed_rows.append(dict(record))
        return allowed_rows, decisions

    def grant_marker(self, decision: Mapping[str, Any], record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "decision": "allow",
            "decision_id": decision["decision_id"],
            "policy_id": self.policy.policy_id,
            "role": decision["role"],
            "labels": list(_labels_of(record)),
            "sensitivity": (record.get("access") or {}).get("sensitivity"),
        }


def load_policy(data: Mapping[str, Any]) -> AccessPolicy:
    return AccessPolicy.from_dict(data)
