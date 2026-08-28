"""CANSLIM 7개 항목 판정 테스트 — 기준서 docs/canslim_criteria.md 의 세부 조건을 하나씩 확인한다."""

import dataclasses
import datetime as dt

import pandas as pd
import pytest

from src.canslim import (
    analyze, days_since_new_high, distribution_days, relative_strength, weighted_return,
)
from src.fundamentals import parse_finance, parse_snapshot
from src.models import SubCheck, Verdict, verdict_of
from src.newness import Newness, NewsItem
from src.valuation import compute_growth
from tests.conftest import (
    SAMSUNG_A_EPS, SAMSUNG_A_PERIODS, SAMSUNG_A_REVENUE, SAMSUNG_A_ROE,
    SAMSUNG_Q_EPS, SAMSUNG_Q_PERIODS, SAMSUNG_Q_REVENUE, SAMSUNG_Q_ROE,
    make_finance, make_integration, make_ohlcv,
)

# 삼성 fixture 는 2025.03 부터라 '직전 분기(2025.12)의 전년 동기(2024.12)'가 없다.
# C2 까지 판정하려면 한 분기를 더 붙인 표가 필요하다.
EXT_Q_PERIODS = [("202412", False)] + SAMSUNG_Q_PERIODS
EXT_Q_EPS = {"202412": "1,500", **SAMSUNG_Q_EPS}            # 2025.12 2,864 vs 1,500 = +90.9%
EXT_Q_REVENUE = {"202412": "700,000", **SAMSUNG_Q_REVENUE}
EXT_Q_ROE = {"202412": "8.0", **SAMSUNG_Q_ROE}


def item(result, letter):
    return next(i for i in result.items if i.letter == letter)


def check(result, code):
    """'C1' 같은 세부 조건 하나를 꺼낸다."""
    itm = item(result, code[0])
    return next(c for c in itm.checks if c.code == code)


def make_quarterly(eps=None, revenue=None, roe=None, periods=None):
    return parse_finance(make_finance(
        periods or EXT_Q_PERIODS,
        {"EPS": eps or EXT_Q_EPS, "매출액": revenue or EXT_Q_REVENUE, "ROE": roe or EXT_Q_ROE},
    ))


def make_annual(eps=None, roe=None):
    return parse_finance(make_finance(
        SAMSUNG_A_PERIODS,
        {"EPS": eps or SAMSUNG_A_EPS, "매출액": SAMSUNG_A_REVENUE, "ROE": roe or SAMSUNG_A_ROE},
    ))


def make_newness(*categories, scanned=20):
    """새로운 재료가 있는(또는 없는) 상태를 만든다."""
    items = [
        NewsItem(category=c, title=f"{c} 관련 공시", date=dt.date(2026, 7, 1), source="공시")
        for c in categories
    ]
    return Newness(items=items, scanned=scanned, window_days=180, available=True)


TWO_MATERIALS = ("신제품·신사업", "수주·공급계약")


def bullish_snapshot(high="260,000"):
    """신고가 근처(254,000/260,000=98%)이고 기관이 순매수 중인 스냅샷."""
    deals = [
        {"bizdate": "20260727", "closePrice": "254,000", "compareToPreviousClosePrice": "4,500",
         "compareToPreviousPrice": {"name": "RISING"},
         "foreignerPureBuyQuant": "+1,000,000", "organPureBuyQuant": "+800,000",
         "individualPureBuyQuant": "-1,800,000", "foreignerHoldRatio": "46.65%"},
        {"bizdate": "20260724", "closePrice": "249,500", "compareToPreviousClosePrice": "-20,500",
         "compareToPreviousPrice": {"name": "FALLING"},
         "foreignerPureBuyQuant": "-300,000", "organPureBuyQuant": "+200,000",
         "individualPureBuyQuant": "+100,000", "foreignerHoldRatio": "46.71%"},
    ]
    return parse_snapshot(make_integration(totals={"highPriceOf52Weeks": high}, dealTrendInfos=deals))


def run(snapshot, quarterly, annual, stock_df, index_df, index_name="KOSPI", newness=None):
    growth = compute_growth(quarterly, annual)
    result, _ = analyze(snapshot, quarterly, annual, growth, stock_df, index_df, index_name,
                        newness=newness if newness is not None else make_newness(*TWO_MATERIALS))
    return result


@pytest.fixture
def ext_quarterly():
    return make_quarterly()


@pytest.fixture
def rising_stock():
    """12개월간 100 → 340 으로 오른 종목. 마지막 날 거래량 급증, 외국인 지분 꾸준히 증가."""
    closes = [100 + i * 0.8 for i in range(300)]
    volumes = [1000.0] * 299 + [5000.0]
    foreign = [20.0 + i * 0.05 for i in range(300)]
    return make_ohlcv(closes, volumes, foreign)


@pytest.fixture
def flat_index():
    """제자리걸음 지수. 최근값이 50일선·200일선 위, 거래량 일정(분산일 0)."""
    return make_ohlcv([100.0 + i * 0.05 for i in range(300)])


class Test세부조건판정:
    def test_확실한_불합격이_판단불가보다_우선한다(self):
        checks = [SubCheck("X1", "a", "", None), SubCheck("X2", "b", "", False)]
        assert verdict_of(checks) is Verdict.FAIL

    def test_어긋난_것은_없는데_모르는_것이_있으면_판단불가(self):
        checks = [SubCheck("X1", "a", "", True), SubCheck("X2", "b", "", None)]
        assert verdict_of(checks) is Verdict.UNKNOWN

    def test_전부_만족해야_합격(self):
        assert verdict_of([SubCheck("X1", "a", "", True)]) is Verdict.PASS
        assert verdict_of([]) is Verdict.UNKNOWN


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


class TestC최근분기:
    def test_두_분기_연속_성장과_직전분기_증가_매출_성장이_모두_되면_합격(
            self, snapshot, ext_quarterly, annual, rising_stock, flat_index):
        result = run(snapshot, ext_quarterly, annual, rising_stock, flat_index)
        c = item(result, "C")
        assert c.verdict is Verdict.PASS
        assert "489" in c.actual
        assert [x.code for x in c.checks] == ["C1", "C2", "C3", "C4"]
        assert all(x.passed for x in c.checks)

    def test_직전_분기의_전년_자료가_없으면_판단불가(self, snapshot, quarterly, annual,
                                          rising_stock, flat_index):
        """삼성 기본 fixture 는 2024.12 가 없어 C2 를 판정할 수 없다."""
        result = run(snapshot, quarterly, annual, rising_stock, flat_index)
        assert item(result, "C").verdict is Verdict.UNKNOWN
        assert check(result, "C2").passed is None

    def test_전년比_미달이면_불합격이지만_수익증가_종목은_EPS를_보여준다(
            self, snapshot, annual, rising_stock, flat_index):
        # 2026.03 6,993 vs 2025.03 6,500 = +7.6% (C1 ✗) · 직전 2,864 → 6,993 (C3 ✓) · 매출 +69% (C4 ✓)
        q = make_quarterly(eps={**EXT_Q_EPS, "202503": "6,500"})
        result = run(snapshot, q, annual, rising_stock, flat_index)
        c = item(result, "C")
        assert c.verdict is Verdict.FAIL
        assert check(result, "C1").passed is False
        assert "수익증가" in c.actual
        assert "2,864원" in c.actual and "6,993원" in c.actual
        assert "수익 증가 중" in c.evidence

    def test_직전_분기보다_EPS가_줄면_불합격(self, snapshot, annual, rising_stock, flat_index):
        # 2025.12 를 8,000 으로 올리면 2026.03 6,993 은 직전 분기보다 작다
        q = make_quarterly(eps={**EXT_Q_EPS, "202512": "8,000"})
        result = run(snapshot, q, annual, rising_stock, flat_index)
        assert check(result, "C3").passed is False
        assert item(result, "C").verdict is Verdict.FAIL

    def test_매출이_기준_미달이면_불합격(self, snapshot, annual, rising_stock, flat_index):
        rev = {**EXT_Q_REVENUE, "202603": "900,000"}   # vs 791,405 = +13.7%
        result = run(snapshot, make_quarterly(revenue=rev), annual, rising_stock, flat_index)
        c4 = check(result, "C4")
        assert c4.passed is False and "+13.7%" in c4.actual
        assert item(result, "C").verdict is Verdict.FAIL

    def test_전년_동기가_적자면_흑자_전환_여부로_본다(self, snapshot, annual, rising_stock, flat_index):
        turned = make_quarterly(eps={**EXT_Q_EPS, "202503": "-100"})
        result = run(snapshot, turned, annual, rising_stock, flat_index)
        assert check(result, "C1").passed is True
        assert "흑자 전환" in check(result, "C1").actual
        assert item(result, "C").verdict is Verdict.PASS

        still_loss = make_quarterly(eps={**EXT_Q_EPS, "202503": "-100", "202603": "-50"})
        result = run(snapshot, still_loss, annual, rising_stock, flat_index)
        assert check(result, "C1").passed is False

    def test_기저효과는_경고만_하고_합격시킨다(self, snapshot, ext_quarterly, annual,
                                     rising_stock, flat_index):
        c = item(run(snapshot, ext_quarterly, annual, rising_stock, flat_index), "C")
        assert c.verdict is Verdict.PASS          # +489.6%
        assert "기저 효과" in c.evidence


class TestA연간실적:
    def test_성장률_매년증가_ROE_모두_충족하면_합격(self, snapshot, ext_quarterly, annual,
                                          rising_stock, flat_index):
        a = item(run(snapshot, ext_quarterly, annual, rising_stock, flat_index), "A")
        assert a.verdict is Verdict.PASS
        assert "2023" in check(run(snapshot, ext_quarterly, annual, rising_stock, flat_index), "A2").actual

    def test_성장률은_충분해도_ROE가_낮으면_불합격(self, snapshot, annual, rising_stock, flat_index):
        q = make_quarterly(roe={**EXT_Q_ROE, "202603": "5.0"})
        a = item(run(snapshot, q, annual, rising_stock, flat_index), "A")
        assert a.verdict is Verdict.FAIL
        assert "기준 미달" in a.evidence

    def test_ROE가_없으면_성장률만으로_합격시키지_않는다(self, snapshot, annual,
                                              rising_stock, flat_index):
        q = make_quarterly(roe={k: "-" for k in EXT_Q_ROE})
        a = item(run(snapshot, q, annual, rising_stock, flat_index), "A")
        assert a.verdict is Verdict.UNKNOWN
        assert "성장률만으로 합격시키지 않습니다" in a.evidence

    def test_중간에_줄어든_해가_있으면_불합격(self, snapshot, ext_quarterly, rising_stock, flat_index):
        # 2023 2,131 → 2024 1,000 → 2025 6,564: 양끝 CAGR 은 +75% 지만 2024 가 감소
        dipped = make_annual(eps={**SAMSUNG_A_EPS, "202412": "1,000"})
        result = run(snapshot, ext_quarterly, dipped, rising_stock, flat_index)
        assert check(result, "A1").passed is True
        assert check(result, "A2").passed is False
        assert "감소: 2024" in check(result, "A2").actual
        assert item(result, "A").verdict is Verdict.FAIL


class TestN새로운변화:
    def test_신고가_90퍼센트_이상이고_재료_2건이면_합격(self, ext_quarterly, annual,
                                            rising_stock, flat_index):
        result = run(bullish_snapshot(), ext_quarterly, annual, rising_stock, flat_index)
        n = item(result, "N")
        assert n.verdict is Verdict.PASS
        assert "새로운" in n.name
        assert "신제품·신사업" in n.evidence

    def test_재료가_1건뿐이면_불합격(self, ext_quarterly, annual, rising_stock, flat_index):
        result = run(bullish_snapshot(), ext_quarterly, annual, rising_stock, flat_index,
                     newness=make_newness("신제품·신사업"))
        n = item(result, "N")
        assert n.verdict is Verdict.FAIL
        assert "재료 1건 ✗" in n.actual

    def test_신고가여도_재료가_없으면_불합격(self, ext_quarterly, annual, rising_stock, flat_index):
        result = run(bullish_snapshot(), ext_quarterly, annual, rising_stock, flat_index,
                     newness=Newness(items=[], scanned=30, available=True))
        n = item(result, "N")
        assert n.verdict is Verdict.FAIL
        assert "재료 없음" in n.actual

    def test_예전_기준_85퍼센트는_이제_불합격(self, ext_quarterly, annual, rising_stock, flat_index):
        # 254,000 / 288,000 = 88% → 90% 기준 미달
        result = run(bullish_snapshot(high="288,000"), ext_quarterly, annual, rising_stock, flat_index)
        n = item(result, "N")
        assert n.verdict is Verdict.FAIL
        assert "88%" in n.actual

    def test_재료를_확인할_수_없으면_판단불가(self, ext_quarterly, annual, rising_stock, flat_index):
        """공시·뉴스를 못 받아왔을 때 '재료 없음'으로 단정하지 않는다."""
        result = run(bullish_snapshot(), ext_quarterly, annual, rising_stock, flat_index,
                     newness=Newness(items=[], scanned=0, available=False))
        assert item(result, "N").verdict is Verdict.UNKNOWN

    def test_신고가_갱신_시점을_알려준다(self, ext_quarterly, annual, flat_index):
        rising = make_ohlcv([100.0 + i for i in range(300)])  # 마지막 날이 최고가
        result = run(bullish_snapshot(), ext_quarterly, annual, rising, flat_index)
        assert "신고가를 방금 갱신" in item(result, "N").evidence


class TestS수급:
    def test_상승일에_거래가_몰리고_최근_거래량이_늘면_합격(self, snapshot, ext_quarterly, annual,
                                               rising_stock, flat_index):
        s = item(run(snapshot, ext_quarterly, annual, rising_stock, flat_index), "S")
        assert s.verdict is Verdict.PASS
        assert "유통주식수" in s.evidence      # 대체 지표임을 밝혀야 한다

    def test_하락일_거래량이_더_많으면_불합격(self, snapshot, ext_quarterly, annual, flat_index):
        closes = [100.0 + (i % 2) for i in range(300)]              # 오르락내리락
        volumes = [1000.0 if i % 2 else 3000.0 for i in range(300)]  # 내리는 날(짝수 index)에 3배
        result = run(snapshot, ext_quarterly, annual, make_ohlcv(closes, volumes), flat_index)
        assert check(result, "S1").passed is False
        assert item(result, "S").verdict is Verdict.FAIL

    def test_최근_거래량이_평범하면_불합격(self, snapshot, ext_quarterly, annual, flat_index):
        steady = make_ohlcv([100.0 + i for i in range(300)], [1000.0] * 300)
        result = run(snapshot, ext_quarterly, annual, steady, flat_index)
        assert check(result, "S1").passed is True   # 하락일이 없다
        assert check(result, "S2").passed is False  # 1.00배
        assert item(result, "S").verdict is Verdict.FAIL

    def test_데이터가_50일_미만이면_판단불가(self, snapshot, ext_quarterly, annual, flat_index):
        short = make_ohlcv([100.0] * 20, [1000.0] * 20)
        assert item(run(snapshot, ext_quarterly, annual, short, flat_index), "S").verdict is Verdict.UNKNOWN


class TestL주도주:
    def test_지수를_크게_이기고_추세가_정배열이면_합격(self, snapshot, ext_quarterly, annual,
                                            rising_stock, flat_index):
        l = item(run(snapshot, ext_quarterly, annual, rising_stock, flat_index), "L")
        assert l.verdict is Verdict.PASS
        assert "RS Rating" in l.evidence

    def test_지수를_조금만_이기면_불합격(self, snapshot, ext_quarterly, annual, flat_index):
        mild = make_ohlcv([100.0 + i * 0.1 for i in range(300)])   # 지수(0.05/일)보다 살짝 강함
        result = run(snapshot, ext_quarterly, annual, mild, flat_index)
        l1 = check(result, "L1")
        assert l1.passed is False
        assert check(result, "L2").passed is True
        assert item(result, "L").verdict is Verdict.FAIL

    def test_지수에_지면_불합격(self, snapshot, ext_quarterly, annual, flat_index):
        falling = make_ohlcv([300 - i * 0.5 for i in range(300)])
        assert item(run(snapshot, ext_quarterly, annual, falling, flat_index), "L").verdict is Verdict.FAIL

    def test_200일치가_없으면_추세_조건은_판단불가(self, snapshot, ext_quarterly, annual):
        young = make_ohlcv([100 + i * 0.8 for i in range(150)])
        index = make_ohlcv([100.0 + i * 0.05 for i in range(150)])
        result = run(snapshot, ext_quarterly, annual, young, index)
        assert check(result, "L1").passed is True
        assert check(result, "L3").passed is None
        assert item(result, "L").verdict is Verdict.UNKNOWN


class TestI기관외국인:
    def test_외국인_지분이_늘고_기관이_사면_합격(self, ext_quarterly, annual, rising_stock, flat_index):
        i = item(run(bullish_snapshot(), ext_quarterly, annual, rising_stock, flat_index), "I")
        assert i.verdict is Verdict.PASS
        assert "외국인 소진율" in i.evidence

    def test_외국인은_늘어도_기관이_팔면_불합격(self, snapshot, ext_quarterly, annual,
                                       rising_stock, flat_index):
        # 삼성 기본 fixture 의 기관 순매수는 +487,617 -3,378,638 < 0
        result = run(snapshot, ext_quarterly, annual, rising_stock, flat_index)
        assert check(result, "I1").passed is True
        assert check(result, "I2").passed is False
        assert item(result, "I").verdict is Verdict.FAIL

    def test_외국인_지분이_찔끔_늘면_불합격(self, ext_quarterly, annual, flat_index):
        tiny = make_ohlcv([100.0] * 300, foreign=[20.0 + i * 0.005 for i in range(300)])  # 60일 +0.3%p
        result = run(bullish_snapshot(), ext_quarterly, annual, tiny, flat_index)
        assert check(result, "I1").passed is False

    def test_60거래일치가_없으면_판단불가(self, ext_quarterly, annual, flat_index):
        short = make_ohlcv([100.0] * 30, foreign=[30.0] * 30)
        assert item(run(bullish_snapshot(), ext_quarterly, annual, short, flat_index), "I").verdict \
            is Verdict.UNKNOWN

    def test_미국_종목은_보유비중만_보여주고_판단불가(self, snapshot, ext_quarterly, annual,
                                          rising_stock, flat_index):
        us_snap = dataclasses.replace(snapshot, inst_holding_pct=61.2, currency="USD",
                                      deal_trend=pd.DataFrame())
        us_stock = rising_stock.drop(columns=["foreign_rate"])
        i = item(run(us_snap, ext_quarterly, annual, us_stock, flat_index), "I")
        assert i.verdict is Verdict.UNKNOWN
        assert "61.2%" in i.actual


class TestM시장방향:
    def test_지수가_정배열이고_분산일이_적으면_합격(self, snapshot, ext_quarterly, annual,
                                          rising_stock, flat_index):
        m = item(run(snapshot, ext_quarterly, annual, rising_stock, flat_index), "M")
        assert m.verdict is Verdict.PASS
        assert "분산일 0일" in m.actual

    def test_50일선_아래면_불합격(self, snapshot, ext_quarterly, annual, rising_stock):
        closes = [100.0 + i for i in range(290)] + [200.0] * 10   # 오르다가 급락
        m = item(run(snapshot, ext_quarterly, annual, rising_stock, make_ohlcv(closes)), "M")
        assert m.verdict is Verdict.FAIL
        assert "50일선 아래" in m.actual

    def test_분산일이_5일_이상이면_불합격(self, snapshot, ext_quarterly, annual, rising_stock):
        closes = [100.0 + i * 0.05 for i in range(275)]
        volumes = [1000.0] * 275
        for k in range(25):                       # 마지막 25일 중 6일이 '거래량 늘며 하락'
            drop = k in {0, 3, 6, 9, 12, 15}
            closes.append(closes[-1] * (0.995 if drop else 1.003))
            volumes.append(3000.0 if drop else 1000.0)
        result = run(snapshot, ext_quarterly, annual, rising_stock, make_ohlcv(closes, volumes))
        assert check(result, "M1").passed is True
        assert check(result, "M3").passed is False
        assert "분산일 6일" in item(result, "M").actual
        assert item(result, "M").verdict is Verdict.FAIL

    def test_지수_거래량이_없으면_분산일은_판단불가(self, snapshot, ext_quarterly, annual,
                                          rising_stock, flat_index):
        no_volume = flat_index.drop(columns=["volume"])
        result = run(snapshot, ext_quarterly, annual, rising_stock, no_volume)
        assert check(result, "M3").passed is None
        assert item(result, "M").verdict is Verdict.UNKNOWN


class Test분산일:
    def test_하락하며_거래량_늘어난_날만_센다(self):
        df = pd.DataFrame({
            "close": [100, 99, 98.9, 100, 99.5, 99.4],      # -1.0%, -0.1%, +1.1%, -0.5%, -0.1%
            "volume": [100, 200, 300, 100, 150, 200],       # 늘, 늘, 줄, 늘, 늘
        })
        assert distribution_days(df, window=5) == 2         # -1.0%(늘), -0.5%(늘)

    def test_거래량이_없으면_None(self):
        assert distribution_days(pd.DataFrame({"close": [1.0, 2.0]})) is None


class Test신고가갱신:
    def test_마지막_날이_최고가면_0(self):
        assert days_since_new_high(pd.Series([1.0, 2.0, 3.0])) == 0

    def test_며칠_전에_갱신했는지_센다(self):
        assert days_since_new_high(pd.Series([1.0, 9.0, 3.0, 2.0])) == 2

    def test_데이터가_모자라면_None(self):
        assert days_since_new_high(pd.Series([1.0])) is None


class Test종합:
    def test_일곱_항목이_모두_나온다(self, snapshot, ext_quarterly, annual, rising_stock, flat_index):
        result = run(snapshot, ext_quarterly, annual, rising_stock, flat_index)
        assert [i.letter for i in result.items] == list("CANSLIM")

    def test_전부_합격해야_충족(self, ext_quarterly, annual, rising_stock, flat_index):
        result = run(bullish_snapshot(), ext_quarterly, annual, rising_stock, flat_index)
        assert [i.verdict for i in result.items] == [Verdict.PASS] * 7, result.tally
        assert result.qualified
        assert result.summary == "CANSLIM 충족"
        assert result.tally == "합격 7 · 불합격 0 · 판단불가 0"

    def test_판단불가가_하나라도_있으면_충족이_아니다(self, quarterly, annual, rising_stock, flat_index):
        """모르는 항목을 불합격으로 깎지는 않지만, 모르는 채로 통과시키지도 않는다."""
        result = run(bullish_snapshot(), quarterly, annual, rising_stock, flat_index)  # C 판단불가
        assert item(result, "C").verdict is Verdict.UNKNOWN
        assert result.failed == 0 and result.unknown == 1
        assert not result.qualified
        assert result.summary == "미충족 (자료 부족)"

    def test_불합격이_있으면_미충족(self, snapshot, ext_quarterly, annual, rising_stock, flat_index):
        result = run(snapshot, ext_quarterly, annual, rising_stock, flat_index)  # N·I 불합격
        assert result.failed >= 1
        assert result.summary == "미충족"

    def test_근거에는_세부_조건이_줄마다_나온다(self, snapshot, ext_quarterly, annual,
                                      rising_stock, flat_index):
        c = item(run(snapshot, ext_quarterly, annual, rising_stock, flat_index), "C")
        lines = c.checks_text.split("\n")
        assert len(lines) == 4 and lines[0].startswith("C1 ") and lines[0].endswith("✓")
        assert c.detail.startswith(c.checks_text)

    def test_데이터가_전혀_없어도_죽지_않는다(self, snapshot):
        empty_table = parse_finance({})
        empty_df = make_ohlcv([100.0])
        result = run(snapshot, empty_table, empty_table, empty_df, empty_df)
        assert len(result.items) == 7
        assert result.summary  # 문자열이 나오기만 하면 된다

    def test_코스닥_종목은_KOSDAQ와_비교한다(self, snapshot, ext_quarterly, annual,
                                    rising_stock, flat_index):
        result = run(snapshot, ext_quarterly, annual, rising_stock, flat_index, index_name="KOSDAQ")
        assert "KOSDAQ" in item(result, "L").criterion
        assert "KOSDAQ" in item(result, "M").criterion
