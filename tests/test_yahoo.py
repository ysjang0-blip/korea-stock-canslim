"""야후(yfinance) 어댑터 테스트 — 네트워크를 타지 않는다.

fixture 숫자는 2026-08-09 에 실제로 받아온 애플(AAPL) 값을 그대로 썼다.
yfinance 는 손익계산서를 '최신 분기부터' 내림차순 열로 준다.
"""

import pandas as pd
import pytest

from src.models import Source, Status
from src.valuation import compute_valuation
from src.yahoo import (
    build_snapshot, normalize_annual, normalize_history, normalize_news, normalize_quarterly,
)

# 분기 손익 (열: 최신부터 — 실제 yfinance 순서)
_Q_COLS = [pd.Timestamp(d) for d in
           ("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30")]
Q_INCOME = pd.DataFrame(
    {
        _Q_COLS[0]: {"Diluted EPS": 2.02, "Total Revenue": 109_417e6, "Net Income": 30_010e6},
        _Q_COLS[1]: {"Diluted EPS": 2.01, "Total Revenue": 111_184e6, "Net Income": 29_900e6},
        _Q_COLS[2]: {"Diluted EPS": 2.84, "Total Revenue": 143_000e6, "Net Income": 42_500e6},
        _Q_COLS[3]: {"Diluted EPS": 1.85, "Total Revenue": 102_466e6, "Net Income": 27_500e6},
        _Q_COLS[4]: {"Diluted EPS": 1.57, "Total Revenue": 94_000e6, "Net Income": 23_400e6},
    }
)  # 행=항목, 열=Timestamp (yfinance 그대로)

BALANCE = pd.DataFrame(
    {
        _Q_COLS[0]: {"Stockholders Equity": 107_520e6},
        _Q_COLS[1]: {"Stockholders Equity": 106_491e6},
    }
)

EST = pd.DataFrame(
    {"avg": {"0q": 1.97549, "+1q": 2.90908, "0y": 8.79979, "+1y": 9.54902}}
)
REV_EST = pd.DataFrame(
    {"avg": {"0q": 113_256e6, "+1q": 153_896e6, "0y": 477_372e6, "+1y": 523_333e6}}
)

_A_COLS = [pd.Timestamp(d) for d in ("2025-09-30", "2024-09-30", "2023-09-30")]
A_INCOME = pd.DataFrame(
    {
        _A_COLS[0]: {"Diluted EPS": 7.46, "Total Revenue": 416_000e6},
        _A_COLS[1]: {"Diluted EPS": 6.08, "Total Revenue": 391_000e6},
        _A_COLS[2]: {"Diluted EPS": 6.13, "Total Revenue": 383_000e6},
    }
)

INFO = {
    "shortName": "Apple Inc.", "currentPrice": 313.33, "previousClose": 312.41,
    "trailingPE": 35.97, "trailingEps": 8.71, "marketCap": 4_572_794_322_944,
    "fiftyTwoWeekHigh": 344.57, "fiftyTwoWeekLow": 223.78,
    "bookValue": 7.36, "priceToBook": 42.57,
    "recommendationMean": 2.08696, "longBusinessSummary": "Apple designs smartphones.",
    "_cns_eps": 8.79979,
}
TARGETS = {"mean": 322.81854, "high": 400.0, "low": 215.0}


@pytest.fixture
def quarterly():
    return normalize_quarterly(Q_INCOME, BALANCE, EST, REV_EST)


@pytest.fixture
def annual():
    return normalize_annual(A_INCOME, EST, REV_EST)


class Test분기정규화:
    def test_기간이_오름차순이고_컨센서스가_두_개다(self, quarterly):
        keys = [p.key for p in quarterly.periods]
        assert keys == sorted(keys)
        assert [p.key for p in quarterly.actual_periods()][-1] == "202606"
        assert [p.key for p in quarterly.consensus_periods()] == ["202609", "202612"]

    def test_EPS와_매출을_라벨로_찾는다(self, quarterly):
        assert quarterly.value("EPS", "202606") == pytest.approx(2.02)
        assert quarterly.value("매출액", "202603") == pytest.approx(111_184e6)
        assert quarterly.value("EPS", "202609") == pytest.approx(1.97549)   # 0q
        assert quarterly.value("EPS", "202612") == pytest.approx(2.90908)   # +1q

    def test_달러는_단위_배수가_1이다(self, quarterly):
        assert quarterly.money_unit == 1.0

    def test_TTM_ROE를_계산해_최신_분기에_붙인다(self, quarterly):
        # (30,010+29,900+42,500+27,500)백만 ÷ 평균자기자본 107,005.5백만 × 100
        roe = quarterly.value("ROE", "202606")
        assert roe == pytest.approx((30010 + 29900 + 42500 + 27500) / 107005.5 * 100, abs=0.1)

    def test_빈_입력도_죽지_않는다(self):
        table = normalize_quarterly(pd.DataFrame())
        assert table.periods == []


class Test연간정규화:
    def test_당해_회계연도_컨센서스가_붙는다(self, annual):
        assert [p.key for p in annual.actual_periods()] == ["202309", "202409", "202509"]
        cons = annual.consensus_periods()
        assert [p.key for p in cons] == ["202609"]
        assert annual.value("EPS", "202609") == pytest.approx(8.79979)


class Test시세정규화:
    def test_시간대와_열_이름을_정리한다(self):
        idx = pd.DatetimeIndex(
            ["2026-08-06 00:00:00-04:00", "2026-08-07 00:00:00-04:00"], name="Date")
        h = pd.DataFrame({"Open": [310.0, 312.0], "High": [313.0, 314.0],
                          "Low": [309.0, 311.0], "Close": [312.41, 313.33],
                          "Volume": [46_139_900, 34_407_100]}, index=idx)
        df = normalize_history(h)
        assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
        assert df["date"].iloc[-1] == pd.Timestamp("2026-08-07")
        assert df["close"].iloc[-1] == pytest.approx(313.33)


class Test뉴스정규화:
    def test_새_형식(self):
        raw = [{"id": "x", "content": {"title": "Apple unveils new AI chip",
                                       "pubDate": "2026-08-08T12:00:00Z"}}]
        items = normalize_news(raw)
        assert items == [{"title": "Apple unveils new AI chip", "datetime": "20260808"}]

    def test_옛_형식(self):
        raw = [{"title": "Old style", "providerPublishTime": 1_775_000_000}]
        items = normalize_news(raw)
        assert items[0]["title"] == "Old style"
        assert len(items[0]["datetime"]) == 8

    def test_제목_없는_항목은_버린다(self):
        assert normalize_news([{"content": {}}]) == []


class Test스냅샷:
    def _price_df(self):
        return pd.DataFrame({
            "date": pd.to_datetime(["2026-08-06", "2026-08-07"]),
            "close": [312.41, 313.33],
        })

    def test_통화와_출처(self):
        snap = build_snapshot("AAPL", INFO, TARGETS, self._price_df(), inst_pct=0.66289)
        assert snap.currency == "USD"
        assert snap.source_name == "야후"
        assert snap.inst_holding_pct == pytest.approx(66.289)
        assert snap.price == pytest.approx(313.33)
        assert snap.price_date == "20260807"
        assert snap.change == pytest.approx(0.92, abs=0.001)

    def test_투자의견은_네이버_방향으로_뒤집는다(self):
        """야후 2.09 (1=강력매수) → 5점 만점 매수 방향으로 3.91."""
        snap = build_snapshot("AAPL", INFO, TARGETS, self._price_df())
        assert snap.recomm_mean == pytest.approx(6 - 2.08696, abs=0.001)

    def test_달러_금액_표기(self):
        snap = build_snapshot("AAPL", INFO, TARGETS, self._price_df())
        assert snap.money(313.33) == "$313.33"
        assert "조 달러" in snap.money_big(4_572_794_322_944)


class Test미국_밸류에이션_통합:
    def _result(self, quarterly, annual):
        snap = build_snapshot("AAPL", INFO, TARGETS, pd.DataFrame({
            "date": pd.to_datetime(["2026-08-07"]), "close": [313.33]}))
        return compute_valuation(snap, quarterly, annual)

    def test_Q2까지_전부_컨센서스_원본이다(self, quarterly, annual):
        result = self._result(quarterly, annual)
        q1 = next(c for c in result.columns if c.label.startswith("Q+1"))
        q2 = next(c for c in result.columns if c.label.startswith("Q+2"))
        assert q1.source is Source.CONSENSUS
        assert q2.source is Source.CONSENSUS   # 역산이 아니다
        assert result.derived is None
        # Q+1 TTM = 확정 최근 3개 (2.84 + 2.01 + 2.02) + 0q 추정 1.97549
        assert q1.eps_ttm.value == pytest.approx(2.84 + 2.01 + 2.02 + 1.97549)

    def test_연간선행은_0y_컨센서스(self, quarterly, annual):
        result = self._result(quarterly, annual)
        annual_col = next(c for c in result.columns if c.label.startswith("연간 선행"))
        assert annual_col.per.value == pytest.approx(313.33 / 8.79979, abs=0.01)
