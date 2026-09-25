"""데이터 검증 테이블 (지침 v3 Step 1).

쓰는 수치를 항목별로 나열하고, 출처와 신뢰도 등급을 붙인다.
  [확인] 검산·교차검증을 통과 (시총 검산, 자체 PER vs 출처 PER)
  [단일] 한 출처에서만 확인 (이 앱은 시장당 출처가 하나라 대부분 여기)
  [추정] 역산·근사값
  [불가] 자료 없음
검산: 주가 × 발행주식수(보통주) = 시가총액이 출처 시총과 5% 이내면 통과.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import prices
from .fundamentals import FinancialTable, Snapshot
from .valuation import EPS, REVENUE, ValuationResult

CAP_TOLERANCE_PCT = 5.0    # 시총 검산 허용 오차
PER_TOLERANCE_PCT = 3.0    # 자체 PER vs 출처 PER 교차검증 허용 오차

CONFIRMED, SINGLE, DERIVED, MISSING = "확인", "단일", "추정", "불가"
GRADE_MARK = {CONFIRMED: "🟢", SINGLE: "🟡", DERIVED: "🟠", MISSING: "⚫"}


@dataclass(frozen=True)
class DataCheck:
    item: str
    value: str
    source: str
    grade: str

    @property
    def grade_text(self) -> str:
        return f"{GRADE_MARK.get(self.grade, '')} {self.grade}"


@dataclass
class Verification:
    checks: list[DataCheck] = field(default_factory=list)
    cap_ok: bool | None = None      # 시총 검산 결과 (자료 없으면 None)
    cap_text: str = ""              # 검산 산식·오차 설명

    @property
    def counts(self) -> dict[str, int]:
        out = {CONFIRMED: 0, SINGLE: 0, DERIVED: 0, MISSING: 0}
        for c in self.checks:
            out[c.grade] = out.get(c.grade, 0) + 1
        return out

    @property
    def tally(self) -> str:
        c = self.counts
        return (f"확인 {c[CONFIRMED]} · 단일 {c[SINGLE]} · "
                f"추정 {c[DERIVED]} · 불가 {c[MISSING]}")


def _fmt_big_shares(n: float | None) -> str:
    if n is None:
        return "—"
    if n >= 1e8:
        return f"{n / 1e8:,.1f}억주"
    return f"{n:,.0f}주"


def build(
    snap: Snapshot,
    quarterly: FinancialTable,
    annual: FinancialTable,
    val: ValuationResult,
    stock_done: pd.DataFrame,
    index_done: pd.DataFrame,
    index_name: str,
    eps_supplemented: bool = False,
) -> Verification:
    v = Verification()
    src_price = f"{snap.source_name} 시세"
    src_fin = f"{snap.source_name} 재무"
    usd = snap.currency == "USD"
    money = snap.money

    # ── 시총 검산 (주가·발행주식수·시총 세 값의 등급을 함께 정한다) ──
    cap_grade = SINGLE
    if snap.price and snap.shares_outstanding and snap.market_cap:
        calc = snap.price * snap.shares_outstanding
        err = abs(calc - snap.market_cap) / snap.market_cap * 100.0
        v.cap_ok = err <= CAP_TOLERANCE_PCT
        mark = "O" if v.cap_ok else "X"
        v.cap_text = (f"주가 × 발행주식수(보통) = {snap.money_big(calc)} vs "
                      f"출처 시총 {snap.money_big(snap.market_cap)} → 오차 {err:.1f}% ({mark})")
        if snap.shares_pref:
            v.cap_text += f" · 우선주 {_fmt_big_shares(snap.shares_pref)}는 별도(주가 미조회)"
        cap_grade = CONFIRMED if v.cap_ok else SINGLE
    else:
        v.cap_text = "발행주식수 자료가 없어 시총 검산을 하지 못했습니다"

    date_tag = f" ({snap.price_date_label})" if snap.price_date_label else ""
    v.checks.append(DataCheck("현재가", money(snap.price) + date_tag if snap.price else "—",
                              src_price, cap_grade if snap.price else MISSING))
    v.checks.append(DataCheck(
        "발행주식수", _fmt_big_shares(snap.shares_outstanding)
        + (f" / 우선주 {_fmt_big_shares(snap.shares_pref)}" if snap.shares_pref else ""),
        f"{snap.source_name} 기업개요" if not usd else "야후 info",
        cap_grade if snap.shares_outstanding else MISSING))
    v.checks.append(DataCheck(
        "시가총액", (snap.money_big(snap.market_cap) if snap.market_cap else "—")
        + (f" — {v.cap_text}" if v.cap_text else ""),
        src_price, cap_grade if snap.market_cap else MISSING))

    v.checks.append(DataCheck(
        "52주 최고/최저",
        f"{money(snap.high_52w)} / {money(snap.low_52w)}" if snap.high_52w and snap.low_52w else "—",
        src_price, SINGLE if snap.high_52w else MISSING))

    close = stock_done["close"] if "close" in stock_done else pd.Series(dtype=float)
    ma50 = prices.moving_average(close, 50)
    ma200 = prices.moving_average(close, 200)
    v.checks.append(DataCheck(
        "50일선 / 200일선",
        f"{money(ma50)} / {money(ma200)}" if ma50 and ma200 else "—",
        "시세로 자체 계산", SINGLE if ma50 and ma200 else MISSING))

    # ── 재무 ──
    q_actual = [p for p in quarterly.actual_periods() if quarterly.value(EPS, p.key) is not None]
    q_text = f"확정 {len(q_actual)}개 분기"
    if eps_supplemented:
        q_text += " (+야후 발표 EPS 이력 보강)"
    v.checks.append(DataCheck("분기 EPS·매출", q_text, src_fin, SINGLE if q_actual else MISSING))

    a_actual = [p for p in annual.actual_periods() if annual.value(EPS, p.key) is not None]
    v.checks.append(DataCheck("연간 EPS", f"확정 {len(a_actual)}개년",
                              src_fin, SINGLE if a_actual else MISSING))

    roe = annual.value("ROE", a_actual[-1].key) if a_actual else None
    v.checks.append(DataCheck("ROE (최근 확정연도)", f"{roe:.1f}%" if roe is not None else "—",
                              src_fin, SINGLE if roe is not None else MISSING))

    cur = val.columns[0] if val.columns else None
    if cur and cur.eps_ttm.is_ok:
        v.checks.append(DataCheck("TTM EPS", f"{money(cur.eps_ttm.value)} (확정 4개 분기 합)",
                                  "재무로 자체 계산", SINGLE))
    else:
        v.checks.append(DataCheck("TTM EPS", "—", "재무로 자체 계산", MISSING))

    v.checks.append(DataCheck(
        "연간 컨센서스 EPS", money(snap.cns_eps_naver) if snap.cns_eps_naver else "—",
        f"{snap.source_name} 컨센서스", SINGLE if snap.cns_eps_naver else MISSING))

    # ── 수익률 (종목 vs 지수) ──
    idx_close = index_done["close"] if "close" in index_done else pd.Series(dtype=float)
    ret_bits = []
    for label, days in (("3개월", 63), ("6개월", 126), ("9개월", 189), ("12개월", 252)):
        s = prices.pct_return(close, days)
        i = prices.pct_return(idx_close, days)
        ret_bits.append(f"{label} {s:+.1f}%/{i:+.1f}%" if s is not None and i is not None
                        else f"{label} —")
    v.checks.append(DataCheck(f"수익률 (종목/{index_name})", " · ".join(ret_bits),
                              "시세로 자체 계산",
                              SINGLE if any("—" not in b for b in ret_bits) else MISSING))

    # ── 직접 계산 멀티플 ──
    per_grade = SINGLE
    per_text = "—"
    if cur and cur.per.is_ok:
        per_text = f"{cur.per.value:,.2f}배"
        if snap.per_naver:
            err = abs(cur.per.value - snap.per_naver) / snap.per_naver * 100.0
            match = err <= PER_TOLERANCE_PCT
            per_grade = CONFIRMED if match else SINGLE
            per_text += (f" (출처 {snap.per_naver:,.2f}배와 "
                         + ("일치" if match else f"{err:.1f}% 차이"))
            per_text += ")"
    v.checks.append(DataCheck("PER (TTM, 자체 계산)", per_text, "자체 계산 + 출처 교차확인",
                              per_grade if per_text != "—" else MISSING))

    fwd_per = (snap.price / snap.cns_eps_naver
               if snap.price and snap.cns_eps_naver and snap.cns_eps_naver > 0 else None)
    v.checks.append(DataCheck("PER (Fwd)", f"{fwd_per:,.2f}배" if fwd_per else "—",
                              "자체 계산 (주가 ÷ 컨센서스 EPS)",
                              SINGLE if fwd_per else MISSING))
    v.checks.append(DataCheck("PBR", f"{snap.pbr:,.2f}배" if snap.pbr else "—",
                              src_price, SINGLE if snap.pbr else MISSING))
    if cur and cur.psr.is_ok:
        v.checks.append(DataCheck("PSR (TTM)", f"{cur.psr.value:,.2f}배", "자체 계산", SINGLE))
    if cur and cur.peg.is_ok:
        v.checks.append(DataCheck("PEG", f"{cur.peg.value:,.2f}", "자체 계산", SINGLE))

    # ── 확인 불가로 알려두는 것 (지침 v3가 요구하지만 무료 출처가 없는 항목) ──
    if not usd:
        v.checks.append(DataCheck("FCF·순차입금·EV/EBITDA", "무료 출처 없음",
                                  "—", MISSING))
    else:
        fcf_text = f"${snap.fcf / 1e9:,.1f}B" if snap.fcf else "—"
        v.checks.append(DataCheck("FCF (최근 연간)", fcf_text, "야후 info",
                                  SINGLE if snap.fcf else MISSING))
    v.checks.append(DataCheck("유통주식수(float)", "무료 출처 없음", "—", MISSING))

    return v
