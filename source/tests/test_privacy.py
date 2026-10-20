"""脱敏规则测试。"""

from __future__ import annotations

from tests.helpers import objects


def _engine():
    _schema, privacy, _policy = objects()
    return privacy


def test_redacts_phone() -> None:
    text, findings = _engine().redact("联系电话13800001111，请回拨")
    assert "13800001111" not in text
    assert "[PHONE:" in text
    assert any(item.category == "PHONE" for item in findings)


def test_redacts_email() -> None:
    text, findings = _engine().redact("邮箱 wang.qiang@huaxin-data.example.com 可用")
    assert "wang.qiang@huaxin-data.example.com" not in text
    assert "[EMAIL:" in text
    assert findings[0].category == "EMAIL"


def test_redacts_id_card_and_bank_card() -> None:
    engine = _engine()
    text, findings = engine.redact("身份证110101199003071234，账户6222020200112233445")
    categories = {item.category for item in findings}
    assert "IDCARD" in categories
    assert "BANKCARD" in categories
    assert "110101199003071234" not in text
    assert "6222020200112233445" not in text


def test_redacts_names() -> None:
    text, findings = _engine().redact("由张伟主持，李娜记录")
    assert "张伟" not in text and "李娜" not in text
    assert text.count("[NAME:") == 2


def test_employee_id_redacted() -> None:
    text, _findings = _engine().redact("员工编号EMP-10231")
    assert "EMP-10231" not in text
    assert "[EMPID:" in text


def test_tokens_are_deterministic() -> None:
    engine = _engine()
    first, _ = engine.redact("张伟 13800001111")
    second, _ = engine.redact("张伟 13800001111")
    assert first == second
    other, _ = engine.redact("李娜 13900002222")
    assert other != first


def test_findings_offsets_point_to_original_value() -> None:
    engine = _engine()
    text = "联系人张伟，电话13800001111，邮箱zhang.wei@example-corp.com"
    _redacted, findings = engine.redact(text)
    assert findings
    for finding in findings:
        assert text[finding.start : finding.end] == finding.value


def test_no_residue_after_redaction() -> None:
    engine = _engine()
    raw = "张伟 13800001111 110101199003071234 6222020200112233445 wang@example-corp.com EMP-10001"
    redacted, findings = engine.redact(raw)
    assert len(findings) == 6
    assert engine.residue(redacted) == []


def test_rule_ids_are_from_config() -> None:
    engine = _engine()
    assert "R-PHONE-CN" in engine.rule_ids
    assert "R-NAME" in engine.rule_ids
    assert engine.rules_id == "PR-2026-01"
