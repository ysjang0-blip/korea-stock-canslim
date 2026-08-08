"""밸류에이션 계산 테스트.

기대값은 2026-07-27 삼성전자 실측 데이터로 손계산한 값이다.
현재가 254,000원 / BPS 71,907원 / 시가총액 1,484조 9,548억원.
"""

import pytest

from src.fundamentals import parse_finance, parse_snapshot
from src.models import Source, Status
from src.valuation import (
    cagr, compute_growth, compute_valuation, derive_quarter, next_quarter_key, yoy,
)
from tests.conftest import (
    SAMSUNG_A_EPS, SAMSUNG_A_PERIODS, SAMSUNG_A_REVENUE, SAMSUNG_Q_EPS,
    SAMSUNG_Q_PERIODS, SAMSUNG_Q_REVENUE, SAMSUNG_Q_ROE, make_finance, make_integration,
)


def column(result, key):
    return next(c for c in result.columns if c.key == key)


class Test분기키:
    @pytest.mark.parametrize("current,expected", [
        ("202603", "202606"), ("202606", "202609"),
        ("202609", "202612"), ("202612", "202703"),
    ])
    def test_다음_분기를_구한다(self, current, expected):
        assert next_quarter_key(current) == expected


class Test성장률공식:
    def test_cagr(self):
        assert cagr(2131, 6564, 2) == pytest.approx(75.51, abs=0.05)

    def test_시작값이_적자면_None(self):
        assert cagr(-100, 500, 2) is None

    def test_전년동기가_적자면_None(self):
        assert yoy(500, -100) is None

    def test_yoy(self):
        assert yoy(6993, 1186) == pytest.approx(489.63, abs=0.05)


class Test성장률:
    def test_분기_전년동기비(self, quarterly, annual):
        g = compute_growth(quarterly, annual)
        assert g.quarter_yoy.value == pytest.approx(489.63, abs=0.05)
        assert g.quarter_yoy.source is Source.ACTUAL

    def test_연간_CAGR은_확정연도만_쓴다(self, quarterly, annual):
        """컨센서스 연도(202612)가 CAGR에 섞이면 안 된다."""
        g = compute_growth(quarterly, annual)
        assert g.annual_cagr_years == 2
        assert g.annual_cagr.value == pytest.approx(75.51, abs=0.05)

    def test_선행_성장률은_컨센서스_기준(self, quarterly, annual):
        g = compute_growth(quarterly, annual)
        assert g.forward_annual.value == pytest.approx(46664 / 6564 * 100 - 100, abs=0.05)
        assert g.forward_annual.source is Source.CONSENSUS

    def test_과거_적자면_CAGR은_계산불가(self, quarterly):
        loss = dict(SAMSUNG_A_EPS, **{"202312": "-1,000"})
        annual = parse_finance(make_finance(SAMSUNG_A_PERIODS, {"EPS": loss}))
        g = compute_growth(quarterly, annual)
        assert g.annual_cagr.status is Status.NOT_APPLICABLE


class Test역산:
    def test_계절성_가중으로_다음_분기를_뽑는다(self, quarterly, annual):
        d = derive_quarter(quarterly, annual, "202606", ("EPS", "매출액"))
        assert d.key == "202609"
        assert d.method == "계절성 가중"
        # (46,664 − 6,993 − 10,625) × 1,783/(1,783+2,864)
        assert d.values["EPS"] == pytest.approx(29046 * 1783 / 4647, abs=1)

    def test_전년_분기가_적자면_균등_배분한다(self, annual):
        eps = dict(SAMSUNG_Q_EPS, **{"202509": "-100"})
        q = parse_finance(make_finance(SAMSUNG_Q_PERIODS, {"EPS": eps, "매출액": SAMSUNG_Q_REVENUE}))
        d = derive_quarter(q, annual, "202606", ("EPS",))
        assert d.method == "균등 배분"
        assert d.values["EPS"] == pytest.approx((46664 - 6993 - 10625) / 2, abs=1)

    def test_연간_컨센서스가_없으면_역산하지_않는다(self, quarterly):
        annual = parse_finance(make_finance(
            [(k, False) for k, _ in SAMSUNG_A_PERIODS], {"EPS": SAMSUNG_A_EPS}
        ))
        assert derive_quarter(quarterly, annual, "202606", ("EPS",)) is None


class Test밸류에이션:
    @pytest.fixture
    def result(self, snapshot, quarterly, annual):
        return compute_valuation(snapshot, quarterly, annual)

    def test_현재_PER은_네이버_값과_일치한다(self, result):
        cur = column(result, "current")
        assert cur.eps_ttm.value == pytest.approx(12373.0)
        assert cur.per.value == pytest.approx(20.53, abs=0.01)
        assert "일치" in result.per_cross_check

    def test_현재_PSR(self, result):
        cap = 1_484_9548 * 10**8
        revenue = (745663 + 860617 + 938374 + 1338734) * 10**8
        assert column(result, "current").psr.value == pytest.approx(cap / revenue, abs=0.01)

    def test_현재_ROE는_네이버_제공값을_쓴다(self, result):
        assert column(result, "current").roe.value == pytest.approx(19.16)

    def test_현재_PEG는_연간CAGR로_나눈다(self, result):
        cur = column(result, "current")
        assert cur.peg.value == pytest.approx(cur.per.value / 75.51, abs=0.01)

    def test_Q1은_확정3개_더하기_컨센서스1개(self, result):
        q1 = column(result, "202606")
        assert q1.eps_ttm.value == pytest.approx(1783 + 2864 + 6993 + 10625)
        assert q1.per.value == pytest.approx(254000 / 22265, abs=0.01)
        assert q1.source is Source.CONSENSUS

    def test_Q2는_역산이라고_표시된다(self, result):
        q2 = column(result, "202609")
        expected_eps = 2864 + 6993 + 10625 + 29046 * 1783 / 4647
        assert q2.eps_ttm.value == pytest.approx(expected_eps, abs=1)
        assert q2.per.value == pytest.approx(254000 / expected_eps, abs=0.01)
        assert q2.source is Source.DERIVED
        assert "역산" in q2.note

    def test_선행_PER은_네이버_추정PER과_일치한다(self, result, snapshot):
        fy = column(result, "202612")
        assert fy.per.value == pytest.approx(254000 / 46664, abs=0.01)
        assert fy.per.value == pytest.approx(snapshot.cns_per_naver, abs=0.02)

    def test_예상_ROE는_근사값으로_표시된다(self, result):
        q1 = column(result, "202606")
        assert q1.roe.source is Source.DERIVED
        assert "근사" in q1.roe.note

    def test_PER이_점점_낮아진다(self, result):
        """실적이 좋아진다는 컨센서스이므로 선행 PER이 현재보다 낮아야 한다."""
        pers = [c.per.value for c in result.columns if c.per.is_ok]
        assert pers == sorted(pers, reverse=True)


class Test예외상황:
    def test_적자기업은_PER이_계산불가(self, annual):
        loss = {k: "-500" for k in SAMSUNG_Q_EPS}
        q = parse_finance(make_finance(
            SAMSUNG_Q_PERIODS, {"EPS": loss, "매출액": SAMSUNG_Q_REVENUE, "ROE": SAMSUNG_Q_ROE}
        ))
        result = compute_valuation(parse_snapshot(make_integration()), q, annual)
        cur = column(result, "current")
        assert cur.per.status is Status.NOT_APPLICABLE
        assert "적자" in cur.per.note
        assert cur.per.text() == "—"
        # PER이 없으면 PEG도 성립하지 않는다
        assert cur.peg.status is Status.NOT_APPLICABLE
        # 매출은 살아 있으므로 PSR은 나온다
        assert cur.psr.is_ok

    def test_컨센서스가_없는_소형주(self, annual):
        q = parse_finance(make_finance(
            [(k, False) for k, _ in SAMSUNG_Q_PERIODS],
            {"EPS": SAMSUNG_Q_EPS, "매출액": SAMSUNG_Q_REVENUE, "ROE": SAMSUNG_Q_ROE},
        ))
        a = parse_finance(make_finance(
            [(k, False) for k, _ in SAMSUNG_A_PERIODS],
            {"EPS": SAMSUNG_A_EPS, "매출액": SAMSUNG_A_REVENUE},
        ))
        result = compute_valuation(parse_snapshot(make_integration()), q, a)
        assert column(result, "current").per.is_ok       # 현재 값은 나오고
        assert not column(result, "q1").per.is_ok        # 미래 값만 비어야 한다
        assert "미커버" in column(result, "q1").note
        assert not column(result, "q2").per.is_ok
        assert not column(result, "fy").per.is_ok

    def test_컨센서스_칸은_있지만_값이_비어있는_경우(self):
        """미커버 종목은 isConsensus='Y' 칸이 있어도 값이 '-' 로 온다 (에코프로 실측).
        칸이 있다는 이유로 '컨센서스 있음'처럼 적으면 안 된다."""
        q_eps = dict(SAMSUNG_Q_EPS, **{"202606": "-"})
        q_rev = dict(SAMSUNG_Q_REVENUE, **{"202606": "-"})
        a_eps = dict(SAMSUNG_A_EPS, **{"202612": "-"})
        a_rev = dict(SAMSUNG_A_REVENUE, **{"202612": "-"})
        q = parse_finance(make_finance(
            SAMSUNG_Q_PERIODS, {"EPS": q_eps, "매출액": q_rev, "ROE": SAMSUNG_Q_ROE}))
        a = parse_finance(make_finance(SAMSUNG_A_PERIODS, {"EPS": a_eps, "매출액": a_rev}))

        result = compute_valuation(parse_snapshot(make_integration()), q, a)
        assert column(result, "current").per.is_ok          # 현재 값은 정상
        q1 = column(result, "202606")
        assert not q1.per.is_ok
        assert "미커버" in q1.note                           # 있는 척하지 않는다
        assert "미커버" in column(result, "202612").note
        assert not column(result, "q2").per.is_ok            # 역산도 불가

    def test_시가총액이_없으면_PSR만_빠진다(self, quarterly, annual):
        payload = make_integration()
        payload["totalInfos"] = [t for t in payload["totalInfos"] if t["code"] != "marketValue"]
        result = compute_valuation(parse_snapshot(payload), quarterly, annual)
        cur = column(result, "current")
        assert cur.psr.status is Status.NO_DATA
        assert cur.per.is_ok

    def test_재무데이터가_아예_없어도_죽지_않는다(self):
        empty = parse_finance({})
        result = compute_valuation(parse_snapshot(make_integration()), empty, empty)
        assert len(result.columns) == 4
        assert all(not c.per.is_ok for c in result.columns)


class Test극단값처리:
    def test_성장률_100퍼센트_초과면_PEG_계산불가(self, quarterly, annual):
        """삼성 fixture의 선행 성장률은 +610% — PEG 0.01 은 정보가 아니라 소음이다."""
        snap = parse_snapshot(make_integration())
        result = compute_valuation(snap, quarterly, annual)
        q1 = column(result, "202606")
        assert q1.peg.status is Status.NOT_APPLICABLE
        assert "극단" in q1.peg.note

    def test_성장률이_보통이면_PEG_정상(self, quarterly, annual):
        """현재 열은 2년 CAGR 75.5% (<100%) → PEG 가 계산된다."""
        snap = parse_snapshot(make_integration())
        result = compute_valuation(snap, quarterly, annual)
        cur = column(result, "current")
        assert cur.peg.is_ok

    def test_다음_분기_컨센서스_YoY(self, quarterly, annual):
        g = compute_growth(quarterly, annual)
        # 2026.06 컨센서스 10,625 vs 2025.06 실적 733
        assert g.next_quarter_yoy.value == pytest.approx(10625 / 733 * 100 - 100, abs=0.05)
        assert g.next_quarter_label == "2026.06"
        assert g.latest_quarter_label == "2026.03"


class TestQ2원본컨센서스:
    """미국(야후)처럼 분기 컨센서스가 두 개면 역산 없이 원본을 쓴다."""

    def _tables(self):
        periods = SAMSUNG_Q_PERIODS + [("202609", True)]
        eps = dict(SAMSUNG_Q_EPS, **{"202609": "11,000"})
        rev = dict(SAMSUNG_Q_REVENUE, **{"202609": "1,800,000"})
        quarterly = parse_finance(make_finance(periods, {"EPS": eps, "매출액": rev}))
        annual = parse_finance(make_finance(
            SAMSUNG_A_PERIODS, {"EPS": SAMSUNG_A_EPS, "매출액": SAMSUNG_A_REVENUE}))
        return quarterly, annual

    def test_Q2가_역산이_아니라_컨센서스로_표시된다(self):
        quarterly, annual = self._tables()
        snap = parse_snapshot(make_integration())
        result = compute_valuation(snap, quarterly, annual)
        q2 = column(result, "202609")
        assert q2.source is Source.CONSENSUS
        assert result.derived is None
        # TTM EPS = 2,864 + 6,993 + 10,625 + 11,000
        assert q2.eps_ttm.value == pytest.approx(2864 + 6993 + 10625 + 11000)

    def test_현재_열_산출근거에_분기_범위가_붙는다(self):
        quarterly, annual = self._tables()
        snap = parse_snapshot(make_integration())
        result = compute_valuation(snap, quarterly, annual)
        assert "2025.06~2026.03" in column(result, "current").note
