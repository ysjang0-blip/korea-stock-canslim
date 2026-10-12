"""1분 브리핑(src/brief.py) 테스트 — 삼성전자 실측 fixture 로 계산."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from src import brief, valuation
from src.models import CanslimResult
from src.newness import Newness, NewsItem
from src.segments import SegmentBreakdown, SegmentShare
from tests.conftest import make_ohlcv


@pytest.fixture
def analysis(snapshot, quarterly, annual):
    val = valuation.compute_valuation(snapshot, quarterly, annual)
    news = Newness(items=[
        NewsItem("수주", "옛 수주", dt.date(2026, 3, 1), "공시"),
        NewsItem("신제품", "새 제품 공개", dt.date(2026, 8, 1), "뉴스"),
        NewsItem("증설", "날짜 없는 기사", None, "뉴스"),
    ])
    return SimpleNamespace(
        snap=snapshot, quarterly=quarterly, annual=annual, valuation=val,
        canslim=CanslimResult(), newness=news, segments=None,
        stock_df=make_ohlcv([100.0] * 200 + [150.0] * 100),
        index_df=make_ohlcv([100.0] * 300), index_name="KOSPI",
    )


class Test매출구성:
    def test_자료가_없으면_이유를_말한다(self, analysis):
        t = brief.segment_table(analysis)
        assert not t.rows and "받아오지 못했습니다" in t.missing

    def test_추정액은_연간매출_곱하기_비중(self, analysis):
        analysis.segments = SegmentBreakdown("2026/03", (
            SegmentShare("DS", 60.0, "메모리"), SegmentShare("기타", -5.0),
        ))
        t = brief.segment_table(analysis)
        assert [r.rank for r in t.rows] == [1, 2]
        assert t.rows[0].share == "60.0%" and t.rows[0].description == "메모리"
        assert t.rows[1].description == "—"
        assert t.rows[0].amount.endswith("조원")
        assert "추정치" in t.note

    def test_미국은_안내만(self, analysis):
        analysis.snap.currency = "USD"
        assert "10-K" in brief.segment_table(analysis).missing


class Test실적:
    def test_항목과_지수_비교(self, analysis):
        lines = dict(brief.performance(analysis).lines)
        assert any(k.startswith("분기 EPS 전년비") for k in lines)
        assert any(k.startswith("분기 매출 전년비") for k in lines)
        returns = lines["주가 수익률 vs KOSPI"]
        assert "3개월 +0.0% (지수 +0.0%)" in returns    # 마지막 100일은 모두 150
        assert "6개월 +50.0% (지수 +0.0%)" in returns   # 126일 전은 100

    def test_시세가_짧으면_대시(self, analysis):
        analysis.stock_df = make_ohlcv([100.0] * 10)
        returns = dict(brief.performance(analysis).lines)["주가 수익률 vs KOSPI"]
        assert "12개월 —" in returns


class Test새재료:
    def test_최신순_날짜없는_것은_뒤로(self, analysis):
        items = brief.new_items(analysis)
        assert [i.title for i in items] == ["새 제품 공개", "옛 수주", "날짜 없는 기사"]

    def test_개수_제한(self, analysis):
        assert len(brief.new_items(analysis, limit=1)) == 1


class Test결론:
    def test_목표가가_없으면_산출_불가(self, analysis):
        c = brief.conclusion(analysis)
        assert c.target == "산출 불가" and c.opinion == "—"

    def test_AI_한_줄을_싣는다(self, analysis):
        assert brief.conclusion(analysis, ai_one_liner="동의").ai_one_liner == "동의"


class TestPER_PEG요약:
    def test_삼성_fixture_PER과_Fwd(self, snapshot, quarterly, annual):
        from src import valuation
        a = SimpleNamespace(snap=snapshot, valuation=valuation.compute_valuation(snapshot, quarterly, annual))
        m = brief.multiples(a)
        cur = a.valuation.columns[0]
        assert m.per == f"{cur.per.value:,.1f}배"
        assert m.per_sub.startswith("Fwd ") or m.per_sub == "TTM 기준"
        if cur.peg.is_ok:
            assert m.peg == f"{cur.peg.value:,.2f}" and "연평균" in m.peg_sub
        else:
            assert m.peg == "—" and m.peg_sub

    def test_PER_없으면_이유를_보여준다(self, snapshot, quarterly, annual):
        from src import valuation
        from src.models import Metric
        val = valuation.compute_valuation(snapshot, quarterly, annual)
        val.columns[0].per = Metric.na("TTM 적자")
        val.columns[0].peg = Metric.na("PER이 성립하지 않아 PEG도 성립하지 않음")
        m = brief.multiples(SimpleNamespace(snap=snapshot, valuation=val))
        assert m.per == "—" and "적자" in m.per_sub
        assert m.peg == "—" and "PEG" in m.peg_sub
