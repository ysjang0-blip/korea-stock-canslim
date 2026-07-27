"""윌리엄 오닐의 CANSLIM 7개 항목 판정.

  C  Current quarterly earnings   최근 분기 EPS 전년동기비 +25% 이상
  A  Annual earnings growth       연간 EPS 성장 +25% 이상 & ROE 17% 이상
  N  New high / New something     주가가 52주 최고가 부근
  S  Supply and demand            거래량 급증 (수급 유입)
  L  Leader or laggard            지수 대비 초과 수익
  I  Institutional sponsorship    기관·외국인 지분 증가
  M  Market direction             지수가 50일선·200일선 위

무료 데이터로 구할 수 없는 항목은 근사치로 대체하고, 무엇을 대체했는지 근거란에 밝힌다.
판단할 수 없으면 '불합격'이 아니라 '판단불가'로 둔다. 모르는 것을 틀렸다고 하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .fundamentals import FinancialTable, Snapshot
from .models import CanslimItem, CanslimResult, Verdict
from .prices import moving_average, pct_return
from .valuation import GrowthRates

# 오닐의 기준값
QUARTER_GROWTH_MIN = 25.0   # C: 분기 EPS 성장률 %
ANNUAL_GROWTH_MIN = 25.0    # A: 연간 EPS 성장률 %
ROE_MIN = 17.0              # A: 자기자본이익률 %
NEAR_HIGH_RATIO = 0.85      # N: 52주 최고가의 85% 이상
VOLUME_SURGE = 1.4          # S: 50일 평균 거래량의 1.4배
FOREIGN_TREND_DAYS = 60     # I: 외국인 소진율 비교 기간 (거래일)

# L: 상대강도 가중치 (오닐 RS Rating 재현식에서 널리 쓰이는 배분)
RS_WEIGHTS = ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2))


@dataclass
class RelativeStrength:
    stock: float | None
    index: float | None
    spread: float | None      # 종목 - 지수 (%포인트)
    detail: list[tuple[str, float | None, float | None]]
    coverage: str = ""


def weighted_return(close: pd.Series) -> float | None:
    """3·6·9·12개월 수익률의 가중 평균. 기간이 모자라면 남은 기간끼리 비중을 다시 나눈다."""
    parts = [(w, pct_return(close, days)) for days, w in RS_WEIGHTS]
    usable = [(w, r) for w, r in parts if r is not None]
    if not usable:
        return None
    total_weight = sum(w for w, _ in usable)
    return sum(w * r for w, r in usable) / total_weight


def relative_strength(stock: pd.DataFrame, index: pd.DataFrame) -> RelativeStrength:
    s_close = stock["close"] if "close" in stock else pd.Series(dtype=float)
    i_close = index["close"] if "close" in index else pd.Series(dtype=float)

    detail = [
        (name, pct_return(s_close, days), pct_return(i_close, days))
        for days, name in ((63, "3개월"), (126, "6개월"), (189, "9개월"), (252, "12개월"))
    ]
    s_w, i_w = weighted_return(s_close), weighted_return(i_close)
    spread = None if (s_w is None or i_w is None) else s_w - i_w
    missing = [name for name, sv, _ in detail if sv is None]
    coverage = f"{', '.join(missing)} 구간은 상장 기간이 짧아 제외" if missing else ""
    return RelativeStrength(stock=s_w, index=i_w, spread=spread, detail=detail, coverage=coverage)


def _verdict(passed: bool | None) -> Verdict:
    if passed is None:
        return Verdict.UNKNOWN
    return Verdict.PASS if passed else Verdict.FAIL


# --------------------------------------------------------------- 항목별 판정

def _item_c(growth: GrowthRates) -> CanslimItem:
    metric = growth.quarter_yoy
    if not metric.is_ok:
        return CanslimItem("C", "최근 분기 실적", f"분기 EPS 전년동기비 +{QUARTER_GROWTH_MIN:.0f}% 이상",
                           "—", Verdict.UNKNOWN, metric.note or "데이터 없음")

    passed = metric.value >= QUARTER_GROWTH_MIN
    evidence = metric.note
    prev = growth.prev_quarter_yoy
    if prev.is_ok:
        trend = "가속 중" if metric.value > prev.value else "둔화 중"
        evidence += f" · 직전 분기 {prev.value:+,.1f}% → 이번 {metric.value:+,.1f}% ({trend})"
    return CanslimItem("C", "최근 분기 실적", f"분기 EPS 전년동기비 +{QUARTER_GROWTH_MIN:.0f}% 이상",
                       f"{metric.value:+,.1f}%", _verdict(passed), evidence)


def _item_a(growth: GrowthRates, roe: float | None) -> CanslimItem:
    metric = growth.annual_cagr
    years = growth.annual_cagr_years
    criterion = f"연간 EPS 성장 +{ANNUAL_GROWTH_MIN:.0f}% 이상 & ROE {ROE_MIN:.0f}% 이상"

    if not metric.is_ok:
        return CanslimItem("A", "연간 실적", criterion, "—", Verdict.UNKNOWN,
                           metric.note or "연간 데이터 없음")

    growth_ok = metric.value >= ANNUAL_GROWTH_MIN
    actual = f"EPS {years}년 CAGR {metric.value:+,.1f}%"
    evidence = f"{metric.note}. 네이버가 연간 3개년만 제공해 {years}년 기준입니다"

    if roe is None:
        evidence += " · ROE 데이터 없어 성장률만으로 판정"
        return CanslimItem("A", "연간 실적", criterion, actual, _verdict(growth_ok), evidence)

    actual += f" · ROE {roe:,.1f}%"
    evidence += f" · ROE {roe:,.1f}% ({'기준 충족' if roe >= ROE_MIN else '기준 미달'})"
    return CanslimItem("A", "연간 실적", criterion, actual,
                       _verdict(growth_ok and roe >= ROE_MIN), evidence)


def _item_n(snap: Snapshot) -> CanslimItem:
    criterion = f"현재가가 52주 최고가의 {NEAR_HIGH_RATIO:.0%} 이상"
    if not snap.price or not snap.high_52w:
        return CanslimItem("N", "신고가 근접", criterion, "—", Verdict.UNKNOWN, "가격 데이터 없음")

    ratio = snap.price / snap.high_52w
    gap = (1 - ratio) * 100
    evidence = (
        f"현재 {snap.price:,.0f}원 / 52주 최고 {snap.high_52w:,.0f}원 "
        f"(최고가 대비 -{gap:,.1f}%) · 52주 최저 {snap.low_52w:,.0f}원"
        if snap.low_52w else f"현재 {snap.price:,.0f}원 / 52주 최고 {snap.high_52w:,.0f}원"
    )
    evidence += " ※ '신제품·신경영' 같은 질적 요소는 자동 판정 대상이 아닙니다"
    return CanslimItem("N", "신고가 근접", criterion, f"최고가의 {ratio:.0%}",
                       _verdict(ratio >= NEAR_HIGH_RATIO), evidence)


def _item_s(stock: pd.DataFrame, snap: Snapshot) -> CanslimItem:
    criterion = f"당일 거래량이 50일 평균의 {VOLUME_SURGE:.1f}배 이상"
    vol = stock["volume"].dropna() if "volume" in stock else pd.Series(dtype=float)
    if len(vol) < 50:
        return CanslimItem("S", "수급", criterion, "—", Verdict.UNKNOWN, "거래량 데이터 50일 미만")

    avg50 = float(vol.iloc[-50:].mean())
    today = float(vol.iloc[-1])
    avg5 = float(vol.iloc[-5:].mean())
    if avg50 <= 0:
        return CanslimItem("S", "수급", criterion, "—", Verdict.UNKNOWN, "평균 거래량 0")

    ratio = today / avg50
    cap_text = f"시가총액 {snap.market_cap / 1e12:,.1f}조원" if snap.market_cap else "시가총액 미상"
    evidence = (
        f"당일 {today:,.0f}주 / 50일 평균 {avg50:,.0f}주 = {ratio:.2f}배 "
        f"· 최근 5일 평균은 {avg5 / avg50:.2f}배 · {cap_text} "
        f"※ 오닐이 중시하는 유통주식수(float)는 무료로 구할 수 없어 거래량으로 대체했습니다"
    )
    return CanslimItem("S", "수급", criterion, f"{ratio:.2f}배", _verdict(ratio >= VOLUME_SURGE), evidence)


def _item_l(rs: RelativeStrength, index_name: str) -> CanslimItem:
    criterion = f"가중 수익률이 {index_name} 초과"
    if rs.spread is None:
        return CanslimItem("L", "주도주 여부", criterion, "—", Verdict.UNKNOWN, "시세 데이터 부족")

    lines = [
        f"{name}: 종목 {sv:+,.1f}% vs 지수 {iv:+,.1f}%"
        for name, sv, iv in rs.detail
        if sv is not None and iv is not None
    ]
    evidence = (
        f"가중 수익률 종목 {rs.stock:+,.1f}% vs {index_name} {rs.index:+,.1f}% · "
        + " / ".join(lines)
        + " ※ 오닐 원본 RS Rating(1~99 백분위)이 아니라 지수 대비 초과 여부입니다"
    )
    if rs.coverage:
        evidence += f" ({rs.coverage})"
    return CanslimItem("L", "주도주 여부", criterion, f"{index_name} 대비 {rs.spread:+,.1f}%p",
                       _verdict(rs.spread > 0), evidence)


def _item_i(stock: pd.DataFrame, snap: Snapshot) -> CanslimItem:
    criterion = f"외국인 소진율이 {FOREIGN_TREND_DAYS}거래일 전보다 상승"
    series = stock["foreign_rate"].dropna() if "foreign_rate" in stock else pd.Series(dtype=float)
    series = series[series > 0]

    if len(series) <= FOREIGN_TREND_DAYS:
        return CanslimItem("I", "기관·외국인 수급", criterion, "—", Verdict.UNKNOWN,
                           "외국인 소진율 데이터가 60거래일 미만입니다")

    now = float(series.iloc[-1])
    past = float(series.iloc[-(FOREIGN_TREND_DAYS + 1)])
    change = now - past

    evidence = f"외국인 소진율 {past:.2f}% → {now:.2f}% ({change:+.2f}%p, 최근 {FOREIGN_TREND_DAYS}거래일)"
    trend = snap.deal_trend
    if not trend.empty and "organ_net" in trend:
        organ = trend["organ_net"].dropna()
        foreign = trend["foreigner_net"].dropna()
        if len(organ):
            evidence += (
                f" · 최근 {len(organ)}일 누적 순매수: 기관 {organ.sum():+,.0f}주, "
                f"외국인 {foreign.sum():+,.0f}주"
            )
    evidence += " ※ 기관 보유 '비중'은 무료로 구할 수 없어 외국인 소진율 추세로 대체했습니다"
    return CanslimItem("I", "기관·외국인 수급", criterion, f"{change:+.2f}%p",
                       _verdict(change > 0), evidence)


def _item_m(index: pd.DataFrame, index_name: str) -> CanslimItem:
    criterion = f"{index_name}가 50일선·200일선 위"
    close = index["close"].dropna() if "close" in index else pd.Series(dtype=float)
    ma50, ma200 = moving_average(close, 50), moving_average(close, 200)

    if len(close) == 0 or ma50 is None:
        return CanslimItem("M", "시장 방향", criterion, "—", Verdict.UNKNOWN, "지수 데이터 부족")

    now = float(close.iloc[-1])
    above50 = now > ma50
    if ma200 is None:
        evidence = f"{index_name} {now:,.2f} / 50일선 {ma50:,.2f} · 200일선은 데이터 부족"
        return CanslimItem("M", "시장 방향", criterion,
                           f"50일선 {'위' if above50 else '아래'}", _verdict(above50), evidence)

    above200 = now > ma200
    state = f"50일선 {'위' if above50 else '아래'} · 200일선 {'위' if above200 else '아래'}"
    evidence = (
        f"{index_name} {now:,.2f} / 50일선 {ma50:,.2f} / 200일선 {ma200:,.2f}. "
        "오닐은 주식의 4분의 3이 시장 방향을 따라간다고 봤습니다"
    )
    return CanslimItem("M", "시장 방향", criterion, state, _verdict(above50 and above200), evidence)


# ------------------------------------------------------------------ 종합

def analyze(
    snap: Snapshot,
    quarterly: FinancialTable,
    annual: FinancialTable,
    growth: GrowthRates,
    stock_df: pd.DataFrame,
    index_df: pd.DataFrame,
    index_name: str = "KOSPI",
) -> tuple[CanslimResult, RelativeStrength]:
    latest_roe = next(
        (quarterly.value("ROE", p.key) for p in reversed(quarterly.actual_periods())
         if quarterly.value("ROE", p.key) is not None),
        None,
    )
    rs = relative_strength(stock_df, index_df)

    result = CanslimResult(items=[
        _item_c(growth),
        _item_a(growth, latest_roe),
        _item_n(snap),
        _item_s(stock_df, snap),
        _item_l(rs, index_name),
        _item_i(stock_df, snap),
        _item_m(index_df, index_name),
    ])
    return result, rs
