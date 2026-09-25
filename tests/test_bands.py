"""밸류에이션 밴드·목표주가·투자의견(src/bands.py) 테스트. 기준: 지침 v3 Step 5·9·10."""

from __future__ import annotations

import pandas as pd

from src import bands
from src.fundamentals import EOK, FinancialTable, Period, Snapshot
from src.models import CanslimItem, CanslimResult, Verdict


def price_df(spec: dict[int, tuple[float, float, int]]) -> pd.DataFrame:
    """{연도: (저점, 고점, 거래일수)} → 일봉. 저점·고점이 정확히 그 값이 되게 만든다."""
    rows = []
    for year, (low, high, n) in spec.items():
        dates = pd.date_range(f"{year}-01-02", periods=n, freq="D")
        mid = (low + high) / 2
        for i, d in enumerate(dates):
            rows.append({"date": d, "open": mid, "close": mid,
                         "high": high if i == 0 else mid,
                         "low": low if i == 1 else mid,
                         "volume": 1000.0})
    return pd.DataFrame(rows)


def annual_table(actual_eps: dict[int, float], consensus_eps: dict[int, float] | None = None,
                 revenue: dict[int, float] | None = None) -> FinancialTable:
    periods, rows_eps, rows_rev = [], {}, {}
    for year, eps in actual_eps.items():
        key = f"{year}12"
        periods.append(Period(key=key, title=f"{year}.12.", is_consensus=False))
        rows_eps[key] = eps
        if revenue:
            rows_rev[key] = revenue.get(year)
    for year, eps in (consensus_eps or {}).items():
        key = f"{year}12"
        periods.append(Period(key=key, title=f"{year}.12.", is_consensus=True))
        rows_eps[key] = eps
    periods.sort(key=lambda p: p.key)
    rows = {"EPS": rows_eps}
    if revenue:
        rows["매출액"] = rows_rev
    return FinancialTable(periods=periods, rows=rows, money_unit=EOK)


def snap(**kw) -> Snapshot:
    base = dict(code="005930", name="테스트", market_cap=1e12, price=10_000.0,
                eps_naver=1_000.0, cns_eps_naver=1_200.0)
    base.update(kw)
    return Snapshot(**base)


def cans(verdicts: dict[str, Verdict]) -> CanslimResult:
    names = {"C": "최근 분기", "A": "연간", "N": "새 변화", "S": "수급",
             "L": "주도주", "I": "기관", "M": "시장"}
    return CanslimResult(items=[
        CanslimItem(letter=L, name=names[L], criterion="", actual="", verdict=v)
        for L, v in verdicts.items()
    ])


ALL_PASS = {L: Verdict.PASS for L in "CANSLI M".replace(" ", "")}


class Test밴드:
    def test_연도별_고저를_EPS로_나눈다(self):
        df = price_df({2023: (800, 1200, 200), 2024: (900, 1500, 200), 2025: (1000, 1800, 200)})
        annual = annual_table({2023: 100.0, 2024: 100.0, 2025: 100.0})
        band = bands.yearly_band(df, annual, metric="PER")
        assert [y.year for y in band.years] == [2023, 2024, 2025]
        assert band.years[0].upper == 12.0 and band.years[0].lower == 8.0
        assert band.upper == (12.0 + 15.0 + 18.0) / 3
        assert band.lower == (8.0 + 9.0 + 10.0) / 3
        assert band.mid == (band.upper + band.lower) / 2

    def test_적자_연도는_제외하고_사유를_남긴다(self):
        df = price_df({2024: (900, 1500, 200), 2025: (1000, 1800, 200)})
        annual = annual_table({2024: -50.0, 2025: 100.0})
        band = bands.yearly_band(df, annual, metric="PER")
        assert [y.year for y in band.years] == [2025]
        assert any("적자" in n for n in band.notes)

    def test_거래일이_부족한_연도는_제외(self):
        df = price_df({2023: (800, 1200, 60), 2025: (1000, 1800, 200)})
        annual = annual_table({2023: 100.0, 2025: 100.0})
        band = bands.yearly_band(df, annual, metric="PER")
        assert [y.year for y in band.years] == [2025]
        assert any("거래일" in n for n in band.notes)

    def test_멀티플_편차가_크면_경고(self):
        df = price_df({2024: (900, 4000, 200), 2025: (1000, 1800, 200)})
        annual = annual_table({2024: 100.0, 2025: 100.0})  # 상단 40배 vs 18배
        band = bands.yearly_band(df, annual, metric="PER")
        assert any("편차" in n for n in band.notes)

    def test_PSR_밴드는_주당매출로(self):
        df = price_df({2025: (1000, 1800, 200)})
        annual = annual_table({2025: -10.0}, revenue={2025: 1_000.0})  # 1,000억원
        band = bands.yearly_band(df, annual, metric="PSR", shares=1e7)
        # 주당매출 = 1,000억 / 1천만주 = 10,000원 → 밴드 0.1~0.18배
        assert band.years[0].per_share == 10_000.0
        assert abs(band.years[0].upper - 0.18) < 1e-9

    def test_PSR인데_주식수가_없으면_불가(self):
        df = price_df({2025: (1000, 1800, 200)})
        annual = annual_table({2025: -10.0}, revenue={2025: 1_000.0})
        band = bands.yearly_band(df, annual, metric="PSR", shares=None)
        assert not band.years
        assert any("발행주식수" in n for n in band.notes)

    def test_시세가_없으면_불가(self):
        band = bands.yearly_band(pd.DataFrame(), annual_table({2025: 100.0}))
        assert not band.years


class Test이익기준:
    def annual(self):
        return annual_table({2024: 900.0, 2025: 1_000.0},
                            consensus_eps={2026: 1_200.0, 2027: 1_500.0})

    def test_보수는_TTM과_컨센서스_중_작은_값(self):
        from src.valuation import ValuationResult
        b = bands.earnings_basis("PER", snap(), ValuationResult(), self.annual())
        assert b.conservative == 1_000.0      # TTM(eps_naver) < 컨센서스 1,200
        assert b.base == 1_200.0              # 기준 = 연간 컨센서스
        assert b.optimistic == 1_500.0        # 낙관 = 차년도 컨센서스
        assert "2027" in b.optimistic_label

    def test_차년도_컨센서스가_없으면_낙관은_기준과_같다(self):
        from src.valuation import ValuationResult
        annual = annual_table({2025: 1_000.0}, consensus_eps={2026: 1_200.0})
        b = bands.earnings_basis("PER", snap(), ValuationResult(), annual)
        assert b.optimistic == b.base == 1_200.0

    def test_컨센서스가_없으면_기준은_TTM(self):
        from src.valuation import ValuationResult
        b = bands.earnings_basis("PER", snap(cns_eps_naver=None), ValuationResult(),
                                 annual_table({2025: 1_000.0}))
        assert b.base == 1_000.0
        assert "TTM" in b.base_label


class Test목표주가:
    def make_target(self):
        df = price_df({2023: (800, 1200, 200), 2024: (900, 1500, 200), 2025: (1000, 1800, 200)})
        annual = annual_table({2023: 100.0, 2024: 100.0, 2025: 100.0},
                              consensus_eps={2026: 120.0, 2027: 150.0})
        band = bands.yearly_band(df, annual, metric="PER")
        basis = bands.EarningsBasis(conservative=100.0, base=120.0, optimistic=150.0,
                                    conservative_label="TTM", base_label="컨센서스",
                                    optimistic_label="차년")
        return bands.target_price(band, basis, price=1_000.0)

    def test_시나리오와_괴리율(self):
        t = self.make_target()
        assert t.bear == t.band.lower * 100.0
        assert t.base == t.band.mid * 120.0
        assert t.bull == t.band.upper * 150.0
        assert abs(t.base_gap - (t.base / 1_000.0 - 1) * 100) < 1e-9
        assert "Bear" in t.note and "Base" in t.note

    def test_민감도는_3x3(self):
        t = self.make_target()
        assert len(t.sensitivity) == 3 and all(len(r) == 3 for r in t.sensitivity)
        assert t.sensitivity[0][0] == t.bear and t.sensitivity[1][1] == t.base
        assert t.sensitivity[2][2] == t.bull

    def test_밴드가_없으면_산출_불가(self):
        t = bands.target_price(bands.Band(notes=["자료 없음"]),
                               bands.EarningsBasis(base=100.0), price=1_000.0)
        assert not t.ok and t.base_gap is None
        assert "자료 없음" in t.note


def target_with_gap(gap_pct: float | None) -> bands.TargetPrice:
    t = bands.TargetPrice(band=bands.Band(), basis=bands.EarningsBasis(), price=100.0)
    if gap_pct is not None:
        t.base = 100.0 * (1 + gap_pct / 100.0)
    return t


class Test투자의견:
    def test_충족이고_괴리율_양수면_매수(self):
        op = bands.investment_opinion(cans(ALL_PASS), target_with_gap(+10))
        assert op.label == "매수"

    def test_판단불가만_있고_괴리율_양수면_조건부(self):
        v = dict(ALL_PASS); v["S"] = Verdict.UNKNOWN
        op = bands.investment_opinion(cans(v), target_with_gap(+10))
        assert op.label == "조건부 매수 후보"
        assert any("확인 필요" in r for r in op.reasons)

    def test_불합격_한두개면_중립(self):
        v = dict(ALL_PASS); v["N"] = Verdict.FAIL
        op = bands.investment_opinion(cans(v), target_with_gap(+10))
        assert op.label == "중립"

    def test_충족이어도_괴리율_0이하면_중립(self):
        op = bands.investment_opinion(cans(ALL_PASS), target_with_gap(-5))
        assert op.label == "중립"

    def test_불합격_3개면_매도(self):
        v = dict(ALL_PASS)
        for L in "NSL":
            v[L] = Verdict.FAIL
        op = bands.investment_opinion(cans(v), target_with_gap(+10))
        assert op.label == "매도/비중 축소"

    def test_M_불합격이면_매도(self):
        v = dict(ALL_PASS); v["M"] = Verdict.FAIL
        op = bands.investment_opinion(cans(v), target_with_gap(+10))
        assert op.label == "매도/비중 축소"
        assert any("시장" in r for r in op.reasons)

    def test_C와_L_동시_불합격이면_매도(self):
        v = dict(ALL_PASS); v["C"] = Verdict.FAIL; v["L"] = Verdict.FAIL
        op = bands.investment_opinion(cans(v), target_with_gap(+10))
        assert op.label == "매도/비중 축소"

    def test_괴리율이_마이너스20_이하면_매도(self):
        op = bands.investment_opinion(cans(ALL_PASS), target_with_gap(-25))
        assert op.label == "매도/비중 축소"

    def test_목표가가_없으면_판단_보류(self):
        op = bands.investment_opinion(cans(ALL_PASS), target_with_gap(None))
        assert op.label == "판단 보류"
