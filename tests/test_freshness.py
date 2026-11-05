"""반영 시점 점검(src/freshness.py) 테스트."""

from __future__ import annotations

from src import freshness
from src.eps_history import EPS_REPORTED
from src.fundamentals import FinancialTable, Period


def table(reported: dict[str, float]) -> FinancialTable:
    keys = ["202509", "202512", "202603"]
    periods = [Period(key=k, title=k, is_consensus=False) for k in keys]
    return FinancialTable(
        periods=periods,
        rows={"EPS": {k: 100.0 for k in keys}, "매출액": {k: 5000.0 for k in keys}, EPS_REPORTED: reported},
        money_unit=1.0)


class Test지연_안내:
    def test_발표_이력에_새_분기가_있으면_안내한다(self):
        notes = freshness.lag_notes(table({"202603": 110.0, "202606": 150.0}), c_advanced=True)
        assert "업데이트 지연" in notes[0] and "2026.03" in notes[0] and "2026.06" in notes[0]
        assert "150원" in notes[0]
        assert any("✅ 반영됨" in n and "C1~C3" in n for n in notes)
        assert any("한 분기 늦음" in n and "매출" in n and "PER" in n for n in notes)

    def test_새_분기를_판정에_못_쓰면_미반영이라_밝힌다(self):
        notes = freshness.lag_notes(table({"202606": 150.0}), c_advanced=False)
        assert any("미반영" in n and "전년 동기" in n for n in notes)

    def test_달러_표기(self):
        assert "$1.50" in freshness.lag_notes(table({"202606": 1.5}), c_advanced=True, usd=True)[0]

    def test_새_분기가_없으면_안내_없음(self):
        assert freshness.lag_notes(table({"202603": 110.0}), c_advanced=False) == []
        assert freshness.lag_notes(table({}), c_advanced=False) == []
