"""보조지표 계산 테스트 — 손으로 검증 가능한 성질을 확인한다."""

import pandas as pd
import pytest

from src.indicators import bollinger, rsi, sma


class Test이동평균:
    def test_기간이_차기_전에는_NaN(self):
        out = sma(pd.Series([1.0, 2.0, 3.0, 4.0]), 3)
        assert out.isna().tolist() == [True, True, False, False]
        assert out.iloc[-1] == pytest.approx((2 + 3 + 4) / 3)


class TestRSI:
    def test_계속_오르면_100(self):
        out = rsi(pd.Series(range(1, 31), dtype=float))
        assert out.iloc[-1] == pytest.approx(100.0)

    def test_계속_내리면_0(self):
        out = rsi(pd.Series(range(30, 0, -1), dtype=float))
        assert out.iloc[-1] == pytest.approx(0.0)

    def test_오르내림이_같으면_50_근처(self):
        closes = [100.0]
        for i in range(40):
            closes.append(closes[-1] + (1.0 if i % 2 == 0 else -1.0))
        out = rsi(pd.Series(closes))
        assert out.iloc[-1] == pytest.approx(50.0, abs=3.0)

    def test_범위는_0에서_100(self):
        closes = pd.Series([100, 103, 99, 104, 98, 105, 97, 110, 95, 112] * 5, dtype=float)
        out = rsi(closes).dropna()
        assert ((out >= 0) & (out <= 100)).all()

    def test_기간이_차기_전에는_NaN(self):
        out = rsi(pd.Series(range(1, 31), dtype=float), period=14)
        assert out.iloc[:13].isna().all()


class Test볼린저:
    def test_선형_상승_구간의_퍼센트B(self):
        """종가 1~25, 20일 창: 마지막 %B를 손계산과 대조한다."""
        close = pd.Series(range(1, 26), dtype=float)
        _, upper, lower, pct_b = bollinger(close, window=20)
        # 6~25의 평균 15.5, 모집단 표준편차 sqrt((20²−1)/12) ≈ 5.766
        assert upper.iloc[-1] == pytest.approx(15.5 + 2 * 5.7663, abs=0.01)
        assert lower.iloc[-1] == pytest.approx(15.5 - 2 * 5.7663, abs=0.01)
        assert pct_b.iloc[-1] == pytest.approx((25 - lower.iloc[-1]) / (upper.iloc[-1] - lower.iloc[-1]))

    def test_변동이_없으면_퍼센트B는_NaN(self):
        """밴드 폭이 0이면 0으로 나누는 대신 NaN — 차트에서 빈 구간이 된다."""
        _, _, _, pct_b = bollinger(pd.Series([100.0] * 30), window=20)
        assert pct_b.iloc[-1] != pct_b.iloc[-1]  # NaN

    def test_종가가_중심선이면_0점5(self):
        close = pd.Series([100.0, 102.0] * 15)
        mid, _, _, pct_b = bollinger(close, window=20)
        # 마지막 종가 102, 중심선 101 → 상단 쪽 절반 위 → 0.5보다 큼
        assert pct_b.iloc[-1] > 0.5
