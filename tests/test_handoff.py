"""클로드용 앱 분석 요약(src/handoff.py) 테스트 — 앱 화면 순서와 완성 보고서 형식."""

import re
from types import SimpleNamespace

import pytest

from src import ai_local, handoff, valuation
from src.models import CanslimItem, CanslimResult, Verdict
from src.newness import Newness
from src.tickers import StockRef
from tests.conftest import make_ohlcv


@pytest.fixture
def analysis(snapshot, quarterly, annual):
    val = valuation.compute_valuation(snapshot, quarterly, annual)
    canslim = CanslimResult(items=[
        CanslimItem("C", "최근 분기 실적", "분기 EPS 전년동기比 +25% 이상",
                    "+489.6%", Verdict.PASS, "2026.03 6,993원 vs 2025.03 1,186원"),
        CanslimItem("I", "수급", "기관/외국인 보유 증가", "—", Verdict.UNKNOWN, "데이터 부족"),
    ])
    return SimpleNamespace(
        ref=StockRef(code="005930", name="삼성전자", market="KOSPI", region="KR"),
        snap=snapshot, quarterly=quarterly, annual=annual,
        valuation=val, canslim=canslim,
        newness=Newness(), stock_df=make_ohlcv([100.0] * 300), index_df=make_ohlcv([100.0] * 300),
        index_name="KOSPI",
    )


def positions(text: str, titles: list[str]) -> list[int]:
    return [text.index(t) for t in titles]


class Test자료순서:
    def test_자료가_앱_화면_순서로_나온다(self, analysis):
        text = handoff.build_handoff(analysis)
        data = text[:text.index("## 출력 형식")]
        pos = positions(data, ["## ① 1분 브리핑", "## ② 상세", "## ③ 목표주가", "## ④ 밸류에이션",
                               "## ⑤ CANSLIM 판정", "## 데이터 신뢰도"])
        assert pos == sorted(pos)

    def test_브리핑에_회사_매출구성_실적_재료가_있다(self, analysis):
        text = handoff.build_handoff(analysis)
        for title in ("### 시세", "### 주요 제품·서비스 매출 구성", "### 실적과 주가", "### 최근 재료"):
            assert title in text

    def test_분기_실적_표에_화면과_같은_숫자(self, analysis):
        text = handoff.build_handoff(analysis)
        assert "254,000원" in text                       # 현재가
        assert re.search(r"\| 2026\.03 \| 6,993원 \|", text)  # 분기 실적 표
        assert "+489.6%" in text                         # CANSLIM C

    def test_밴드_목표가가_없어도_만들어진다(self, analysis):
        assert "앱 분석 요약" in handoff.build_handoff(analysis)


class Test출력형식:
    def test_요약_맨_아래에_완성_보고서_형식이_붙는다(self, analysis):
        text = handoff.build_handoff(analysis)
        assert text.rstrip().endswith(handoff.DISCLAIMER + '"')
        assert "출력 형식" in handoff.HEADER_INSTRUCTION

    def test_형식의_큰_제목이_화면_순서(self):
        heads = [ln[3:] for ln in handoff.REPORT_FORMAT.splitlines() if ln.startswith("## ")]
        assert heads[1:] == handoff.SECTION_TITLES   # 첫 줄은 '출력 형식' 자체

    def test_결론_한_줄은_한줄결론_추출과_맞물린다(self):
        assert "### 결론 한 줄" in handoff.REPORT_FORMAT
        report_md = "\n".join([
            "# 삼성전자 분석 보고서 (2026-10-08)", "| 항목 | 내용 |", "|---|---|", "| 투자의견 | 중립 |",
            "## ① 1분 브리핑", "### 무슨 회사인가", "반도체 회사입니다.",
            "### 결론 한 줄", "**중립** — 실적은 좋지만 시장이 조정 중입니다.", "## ② 상세 — 실적 · 재무",
        ])
        assert ai_local.one_liner(report_md) == "중립 — 실적은 좋지만 시장이 조정 중입니다."

    def test_로컬_요청도_형식을_따르라고_한다(self):
        assert "출력 형식" in ai_local.REQUEST


class Test미국매출구성:
    def test_앱에_매출구성이_없으면_클로드에게_검색으로_채우라고_한다(self, analysis):
        analysis.snap.currency = "USD"
        text = handoff.build_handoff(analysis)
        assert "클로드 작업" in text and "10-K" in text

    def test_한국도_자료를_못_받으면_보완을_지시한다(self, analysis):
        analysis.segments = None
        assert "클로드 작업" in handoff.build_handoff(analysis)
