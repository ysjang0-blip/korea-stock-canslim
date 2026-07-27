"""CANSLIM 7개 항목 판정 테스트."""

import pandas as pd
import pytest

from src.canslim import analyze, relative_strength, weighted_return
from src.fundamentals import parse_finance, parse_snapshot
from src.models import Verdict
from src.valuation import compute_growth
from tests.conftest import (
    SAMSUNG_A_EPS, SAMSUNG_A_PERIODS, SAMSUNG_Q_EPS, SAMSUNG_Q_PERIODS,
    SAMSUNG_Q_REVENUE, SAMSUNG_Q_ROE, make_finance, make_integration, make_ohlcv,
)


def item(result, letter):
    return next(i for i in result.items if i.letter == letter)


def run(snapshot, quarterly, annual, stock_df, index_df, index_name="KOSPI"):
    growth = compute_growth(quarterly, annual)
    result, _ = analyze(snapshot, quarterly, annual, growth, stock_df, index_df, index_name)
    return result


@pytest.fixture
def rising_stock():
    """12개월간 100 → 300 으로 오른 종목. 마지막 날 거래량 급증."""
    closes = [100 + i * 0.8 for i in range(300)]
    volumes = [1000.0] * 299 + [5000.0]
    foreign = [20.0 + i * 0.05 for i in range(300)]  # 외국인 지분 증가
    return make_ohlcv(closes, volumes, foreign)


@pytest.fixture
def flat_index():
    """제자리걸음 지수. 최근값이 50일선·200일선 위."""
    return make_ohlcv([100.0 + i * 0.05 for i in range(300)])


class Test상대강도:
    def test_기간별_가중평균을_구한다(self):
        closes = list(range(1, 301))
        value = weighted_return(pd.Series([float(c) for c in closes]))
        assert value is not None and value > 0

    def test_기간이_짧으면_남은_구간끼리_비중을_다시_나눈다(self):
        short = pd.Series([100.0 + i for i in range(80)])  # 3개월치만 가능
        assert weighted_return(short) is not None

    def test_데이터가_아예_모자라면_None(self):
        assert weighted_return(pd.Series([100.0, 101.0])) is None

    def test_지수보다_많이_오르면_spread가_양수(self, rising_stock, flat_index):
        rs = relative_strength(rising_stock, flat_index)
        assert rs.spread > 0


class Test각항목:
    def test_C_분기실적이_기준을_넘으면_합격(self, snapshot, quarterly, annual,
                                       rising_stock, flat_index):
        result = run(snapshot, quarterly, annual, rising_stock, flat_index)
        c = item(result, "C")
        assert c.verdict is Verdict.PASS
        assert "489" in c.actual

    def test_C_전년동기가_적자면_판단불가(self, snapshot, annual, rising_stock, flat_index):
        eps = dict(SAMSUNG_Q_EPS, **{"202503": "-100"})
        q = parse_finance(make_finance(
            SAMSUNG_Q_PERIODS, {"EPS": eps, "매출액": SAMSUNG_Q_REVENUE, "ROE": SAMSUNG_Q_ROE}))
        result = run(snapshot, q, annual, rising_stock, flat_index)
        assert item(result, "C").verdict is Verdict.UNKNOWN

    def test_A_성장률은_충분해도_ROE가_낮으면_불합격(self, snapshot, annual,
                                              rising_stock, flat_index):
        roe = dict(SAMSUNG_Q_ROE, **{"202603": "5.0"})
        q = parse_finance(make_finance(
            SAMSUNG_Q_PERIODS, {"EPS": SAMSUNG_Q_EPS, "매출액": SAMSUNG_Q_REVENUE, "ROE": roe}))
        result = run(snapshot, q, annual, rising_stock, flat_index)
        a = item(result, "A")
        assert a.verdict is Verdict.FAIL
        assert "기준 미달" in a.evidence

    def test_N_52주_최고가_대비_위치로_판정한다(self, snapshot, quarterly, annual,
                                        rising_stock, flat_index):
        result = run(snapshot, quarterly, annual, rising_stock, flat_index)
        n = item(result, "N")
        # 254,000 / 380,000 = 67% → 85% 기준 미달
        assert n.verdict is Verdict.FAIL
        assert "67%" in n.actual

    def test_N_신고가_부근이면_합격(self, quarterly, annual, rising_stock, flat_index):
        payload = make_integration(totals={"highPriceOf52Weeks": "260,000"})
        snap = parse_snapshot(payload)
        result = run(snap, quarterly, annual, rising_stock, flat_index)
        assert item(result, "N").verdict is Verdict.PASS

    def test_S_거래량이_급증하면_합격(self, snapshot, quarterly, annual,
                                rising_stock, flat_index):
        result = run(snapshot, quarterly, annual, rising_stock, flat_index)
        s = item(result, "S")
        assert s.verdict is Verdict.PASS      # 마지막 날 5000주 vs 평균 1000주
        assert "유통주식수" in s.evidence      # 대체 지표임을 밝혀야 한다

    def test_S_거래량이_평범하면_불합격(self, snapshot, quarterly, annual, flat_index):
        quiet = make_ohlcv([100.0] * 300, [1000.0] * 300)
        result = run(snapshot, quarterly, annual, quiet, flat_index)
        assert item(result, "S").verdict is Verdict.FAIL

    def test_S_데이터가_50일_미만이면_판단불가(self, snapshot, quarterly, annual, flat_index):
        short = make_ohlcv([100.0] * 20, [1000.0] * 20)
        result = run(snapshot, quarterly, annual, short, flat_index)
        assert item(result, "S").verdict is Verdict.UNKNOWN

    def test_L_지수를_이기면_합격이고_백분위가_아님을_밝힌다(self, snapshot, quarterly, annual,
                                                rising_stock, flat_index):
        result = run(snapshot, quarterly, annual, rising_stock, flat_index)
        l = item(result, "L")
        assert l.verdict is Verdict.PASS
        assert "RS Rating" in l.evidence

    def test_L_지수에_지면_불합격(self, snapshot, quarterly, annual, flat_index):
        falling = make_ohlcv([300 - i * 0.5 for i in range(300)])
        result = run(snapshot, quarterly, annual, falling, flat_index)
        assert item(result, "L").verdict is Verdict.FAIL

    def test_I_외국인_지분이_늘면_합격(self, snapshot, quarterly, annual,
                                rising_stock, flat_index):
        result = run(snapshot, quarterly, annual, rising_stock, flat_index)
        i = item(result, "I")
        assert i.verdict is Verdict.PASS
        assert "외국인 소진율" in i.evidence

    def test_I_외국인_지분이_줄면_불합격(self, snapshot, quarterly, annual, flat_index):
        outflow = make_ohlcv([100.0] * 300, foreign=[50.0 - i * 0.05 for i in range(300)])
        result = run(snapshot, quarterly, annual, outflow, flat_index)
        assert item(result, "I").verdict is Verdict.FAIL

    def test_I_60거래일치가_없으면_판단불가(self, snapshot, quarterly, annual, flat_index):
        short = make_ohlcv([100.0] * 30, foreign=[30.0] * 30)
        result = run(snapshot, quarterly, annual, short, flat_index)
        assert item(result, "I").verdict is Verdict.UNKNOWN

    def test_M_지수가_두_이동평균선_위면_합격(self, snapshot, quarterly, annual,
                                     rising_stock, flat_index):
        result = run(snapshot, quarterly, annual, rising_stock, flat_index)
        assert item(result, "M").verdict is Verdict.PASS

    def test_M_50일선_아래면_불합격(self, snapshot, quarterly, annual, rising_stock):
        # 오르다가 마지막에 급락한 지수
        closes = [100.0 + i for i in range(290)] + [200.0] * 10
        result = run(snapshot, quarterly, annual, rising_stock, make_ohlcv(closes))
        m = item(result, "M")
        assert m.verdict is Verdict.FAIL
        assert "50일선 아래" in m.actual


class Test종합:
    def test_일곱_항목이_모두_나온다(self, snapshot, quarterly, annual,
                              rising_stock, flat_index):
        result = run(snapshot, quarterly, annual, rising_stock, flat_index)
        assert [i.letter for i in result.items] == list("CANSLIM")

    def test_판단불가는_분모에서_제외한다(self, snapshot, annual, rising_stock, flat_index):
        """모르는 항목을 '불합격'으로 깎아내리지 않는다."""
        eps = dict(SAMSUNG_Q_EPS, **{"202503": "-100"})   # C를 판단불가로 만든다
        q = parse_finance(make_finance(
            SAMSUNG_Q_PERIODS, {"EPS": eps, "매출액": SAMSUNG_Q_REVENUE, "ROE": SAMSUNG_Q_ROE}))
        result = run(snapshot, q, annual, rising_stock, flat_index)
        assert item(result, "C").verdict is Verdict.UNKNOWN
        assert result.judged == 6          # 7이 아니라 6
        assert "/ 6" in result.summary

    def test_데이터가_전혀_없어도_죽지_않는다(self, snapshot):
        empty_table = parse_finance({})
        empty_df = make_ohlcv([100.0])
        result = run(snapshot, empty_table, empty_table, empty_df, empty_df)
        assert len(result.items) == 7
        assert result.summary  # 문자열이 나오기만 하면 된다

    def test_코스닥_종목은_KOSDAQ와_비교한다(self, snapshot, quarterly, annual,
                                    rising_stock, flat_index):
        result = run(snapshot, quarterly, annual, rising_stock, flat_index, index_name="KOSDAQ")
        assert "KOSDAQ" in item(result, "L").criterion
        assert "KOSDAQ" in item(result, "M").criterion
