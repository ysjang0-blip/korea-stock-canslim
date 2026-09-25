"""데이터 검증 표(src/verification.py) 테스트 — 시총 검산·신뢰도 등급."""

from __future__ import annotations

from src import verification
from src.fundamentals import FinancialTable, Period, Snapshot
from src.models import Source
from src.valuation import Metric, ValuationColumn, ValuationResult
from tests.conftest import make_ohlcv
from tests.test_bands import annual_table


def snap(**kw) -> Snapshot:
    base = dict(code="005930", name="테스트", market_cap=1e12, price=10_000.0,
                price_date="20260924", per_naver=10.0, eps_naver=1_000.0,
                cns_eps_naver=1_200.0, pbr=1.5, high_52w=12_000.0, low_52w=6_000.0,
                shares_outstanding=1e8)  # 1e8주 × 10,000원 = 1e12 = 시총과 정확히 일치
    base.update(kw)
    return Snapshot(**base)


def val(per: float | None = 10.0) -> ValuationResult:
    col = ValuationColumn(
        key="cur", label="현재", source=Source.ACTUAL,
        eps_ttm=Metric.ok(1_000.0),
        per=Metric.ok(per) if per is not None else Metric.no_data("없음"),
    )
    return ValuationResult(columns=[col], per_cross_check="일치")


def quarterly_table() -> FinancialTable:
    periods = [Period(key=f"2025{m:02d}", title=f"2025.{m:02d}.", is_consensus=False)
               for m in (3, 6, 9, 12)]
    return FinancialTable(periods=periods,
                          rows={"EPS": {p.key: 100.0 for p in periods}})


def build(s: Snapshot, v: ValuationResult | None = None):
    df = make_ohlcv([10_000.0] * 260)
    return verification.build(
        s, quarterly_table(), annual_table({2024: 900.0, 2025: 1_000.0}),
        v or val(), df, df, "KOSPI",
    )


class Test시총검산:
    def test_일치하면_통과하고_세_항목이_확인_등급(self):
        v = build(snap())
        assert v.cap_ok is True
        assert "오차 0.0% (O)" in v.cap_text
        by_item = {c.item: c for c in v.checks}
        assert by_item["현재가"].grade == verification.CONFIRMED
        assert by_item["발행주식수"].grade == verification.CONFIRMED
        assert by_item["시가총액"].grade == verification.CONFIRMED

    def test_오차_5퍼센트_초과면_실패(self):
        v = build(snap(market_cap=1e12 * 1.10))
        assert v.cap_ok is False
        assert "(X)" in v.cap_text
        assert {c.item: c for c in v.checks}["현재가"].grade == verification.SINGLE

    def test_주식수가_없으면_검산_불가(self):
        v = build(snap(shares_outstanding=None))
        assert v.cap_ok is None
        assert "검산을 하지 못했습니다" in v.cap_text

    def test_우선주는_별도_표기(self):
        v = build(snap(shares_pref=8e8))
        assert "우선주" in v.cap_text


class TestPER교차:
    def test_출처와_일치하면_확인(self):
        v = build(snap())
        per = next(c for c in v.checks if c.item.startswith("PER (TTM"))
        assert per.grade == verification.CONFIRMED
        assert "일치" in per.value

    def test_차이가_크면_단일로_남긴다(self):
        v = build(snap(per_naver=15.0))
        per = next(c for c in v.checks if c.item.startswith("PER (TTM"))
        assert per.grade == verification.SINGLE
        assert "차이" in per.value


class Test집계:
    def test_tally_형식(self):
        v = build(snap())
        assert "확인" in v.tally and "단일" in v.tally and "불가" in v.tally
        assert sum(v.counts.values()) == len(v.checks)

    def test_무료_출처가_없는_항목은_불가로_명시(self):
        v = build(snap())
        items = [c.item for c in v.checks if c.grade == verification.MISSING]
        assert any("FCF" in i for i in items)
        assert any("유통주식수" in i for i in items)
