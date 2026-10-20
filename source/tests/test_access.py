"""访问权限过滤与授权标记测试。"""

from __future__ import annotations

from tests.helpers import ingested, objects
from record_wiring.export import export_for_role


def test_every_stored_record_has_access_labels() -> None:
    with ingested("labels") as ctx:
        for row in ctx["rows"]:
            labels = row["record"]["access"]["labels"]
            assert labels
            assert all(isinstance(item, str) and item for item in labels)


def test_analyst_cannot_read_hr_record() -> None:
    with ingested("deny") as ctx:
        controller = ctx["controller"]
        rows = [row["record"] for row in ctx["rows"] if row["record"]["record_id"] == "MR-2026-0002"]
        decision = controller.decide(rows[0], "analyst")
        assert decision["allowed"] is False
        assert "hr" in decision["missing_labels"]
        assert decision["decision_id"].startswith("AD-")


def test_compliance_can_read_hr_record() -> None:
    with ingested("allow") as ctx:
        controller = ctx["controller"]
        rows = [row["record"] for row in ctx["rows"] if row["record"]["record_id"] == "MR-2026-0002"]
        decision = controller.decide(rows[0], "compliance_auditor")
        assert decision["allowed"] is True
        assert decision["missing_labels"] == []


def test_export_filters_rows_and_marks_grants() -> None:
    with ingested("export") as ctx:
        controller = ctx["controller"]
        exported, decisions = export_for_role(ctx["rows"], controller, "analyst")
        assert len(exported) == 3
        assert all(item["record_id"] != "MR-2026-0002" for item in exported)
        assert all(item["_grant"]["decision"] == "allow" for item in exported)
        assert all(item["_grant"]["policy_id"] == "AP-2026-01" for item in exported)
        assert len(decisions) == 23
        assert any(item["allowed"] is False for item in decisions)


def test_unknown_role_is_denied() -> None:
    with ingested("unknown") as ctx:
        controller = ctx["controller"]
        decision = controller.decide(ctx["rows"][0]["record"], "guest")
        assert decision["allowed"] is False
        assert decision["missing_labels"]


def test_intern_only_sees_plain_internal() -> None:
    with ingested("intern") as ctx:
        exported, _decisions = export_for_role(ctx["rows"], ctx["controller"], "intern")
        assert len(exported) == 1
        assert exported[0]["record_id"] == "MR-2026-0011"
        assert exported[0]["access"]["labels"] == ["internal"]


def test_analyst_role_gets_only_internal_and_analytics() -> None:
    _schema, _privacy, policy = objects()
    allowed, missing = policy.allows("analyst", ["internal", "analytics"])
    assert allowed is True and missing == ()
    allowed, missing = policy.allows("analyst", ["internal", "finance"])
    assert allowed is False and missing == ("finance",)
