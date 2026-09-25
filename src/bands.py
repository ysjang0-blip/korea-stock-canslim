"""밸류에이션 밴드(Step 5) · 목표주가 Bear/Base/Bull(Step 9) · 투자의견 결합 규칙(Step 10).

기준서: docs/claude_project_instructions.md (사용자 지침 v3). 규칙 요약:
  * 밴드: 최근 3개 확정 연도 각각의 주가 고점·저점 ÷ 그 해 EPS → 멀티플 상단·하단.
    TTM 적자면 PER이 성립하지 않으므로 주당매출(PSR) 밴드로 대체한다.
  * 이익 3단계: 보수 = min(TTM, 연간 컨센서스) / 기준 = 연간 컨센서스(없으면 TTM) /
    낙관 = 차년도 연간 컨센서스(없으면 기준과 동일).
  * 멀티플 3단계: 하단 = 3개년 저점 평균 / 상단 = 고점 평균 / 중간 = (상단+하단)/2.
  * Bear = 하단×보수, Base = 중간×기준, Bull = 상단×낙관. 민감도 = 멀티플 3 × 이익 3.
  * 투자의견: CANSLIM이 1차, Base 괴리율이 2차 (규칙은 investment_opinion 참고).

모든 산출물은 산식과 제외 사유를 문구로 남긴다 — 숫자만 던지지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .fundamentals import FinancialTable, Snapshot
from .models import CanslimResult, Verdict
from .valuation import EPS, REVENUE, ValuationResult

BAND_YEARS = 3          # 밴드에 쓰는 확정 연도 수
MIN_SESSIONS = 150      # 이보다 거래일이 적은 연도는 고점·저점이 반쪽이라 제외
SELL_GAP = -20.0        # Base 괴리율이 이보다 낮으면 매도/비중 축소
SELL_FAILED = 3         # 불합격 항목이 이 수 이상이면 매도/비중 축소


@dataclass(frozen=True)
class YearBand:
    year: int
    high: float          # 그 해 주가 고점
    low: float           # 그 해 주가 저점
    per_share: float     # 그 해 EPS (PSR 밴드면 주당매출)
    upper: float         # high ÷ per_share
    lower: float         # low ÷ per_share
    sessions: int


@dataclass
class Band:
    metric: str = "PER"                      # 'PER' 또는 'PSR'
    years: list[YearBand] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # 제외 연도·근사 사유

    @property
    def upper(self) -> float | None:
        return sum(y.upper for y in self.years) / len(self.years) if self.years else None

    @property
    def lower(self) -> float | None:
        return sum(y.lower for y in self.years) / len(self.years) if self.years else None

    @property
    def mid(self) -> float | None:
        return (self.upper + self.lower) / 2 if self.years else None


@dataclass
class EarningsBasis:
    """목표주가에 곱할 주당 이익(또는 주당매출) 3단계. 각 값의 출처를 라벨로 남긴다."""

    metric: str = "PER"
    conservative: float | None = None
    base: float | None = None
    optimistic: float | None = None
    conservative_label: str = ""
    base_label: str = ""
    optimistic_label: str = ""


@dataclass
class TargetPrice:
    band: Band
    basis: EarningsBasis
    price: float | None = None
    bear: float | None = None
    base: float | None = None
    bull: float | None = None
    # 민감도: 행 = 멀티플(하단·중간·상단), 열 = 이익(보수·기준·낙관)
    sensitivity: list[list[float | None]] = field(default_factory=list)
    note: str = ""

    def _gap(self, target: float | None) -> float | None:
        if target is None or not self.price:
            return None
        return (target / self.price - 1.0) * 100.0

    @property
    def bear_gap(self) -> float | None:
        return self._gap(self.bear)

    @property
    def base_gap(self) -> float | None:
        return self._gap(self.base)

    @property
    def bull_gap(self) -> float | None:
        return self._gap(self.bull)

    @property
    def ok(self) -> bool:
        return self.base is not None


@dataclass
class Opinion:
    label: str                       # 매수 / 조건부 매수 후보 / 중립 / 매도·비중 축소 / 판단 보류
    emoji: str
    reasons: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return f"{self.emoji} {self.label}"


# ---------------------------------------------------------------- 밴드

def yearly_band(
    stock_df: pd.DataFrame,
    annual: FinancialTable,
    metric: str = "PER",
    shares: float | None = None,
) -> Band:
    """최근 확정 연도 최대 3개의 (고점·저점 ÷ 그 해 EPS) 밴드.

    metric='PSR' 이면 EPS 대신 주당매출(그 해 매출 × money_unit ÷ 현재 발행주식수)을 쓴다.
    주식수는 현재값이라 과거 연도에는 근사치다 — note 로 남긴다.
    """
    band = Band(metric=metric)
    if stock_df.empty or "date" not in stock_df:
        band.notes.append("시세 자료가 없어 밴드를 계산하지 못했습니다")
        return band
    if metric == "PSR" and not shares:
        band.notes.append("발행주식수가 없어 주당매출(PSR) 밴드를 계산하지 못했습니다")
        return band

    years_in_df = pd.to_datetime(stock_df["date"]).dt.year

    candidates = annual.actual_periods()[-BAND_YEARS:]
    for p in candidates:
        if metric == "PER":
            per_share = annual.value(EPS, p.key)
            if per_share is None:
                band.notes.append(f"{p.year}년: EPS 자료 없음 — 제외")
                continue
            if per_share <= 0:
                band.notes.append(f"{p.year}년: 적자라 PER이 성립하지 않음 — 제외")
                continue
        else:
            revenue = annual.value(REVENUE, p.key)
            if revenue is None or revenue <= 0:
                band.notes.append(f"{p.year}년: 매출 자료 없음 — 제외")
                continue
            per_share = revenue * annual.money_unit / shares

        mask = years_in_df == p.year
        sessions = int(mask.sum())
        if sessions < MIN_SESSIONS:
            band.notes.append(f"{p.year}년: 시세가 {sessions}거래일뿐이라 고점·저점이 불완전 — 제외")
            continue

        high = float(stock_df.loc[mask, "high"].max())
        low = float(stock_df.loc[mask, "low"].min())
        if not high or not low or low <= 0:
            band.notes.append(f"{p.year}년: 시세 값 이상 — 제외")
            continue

        band.years.append(YearBand(
            year=p.year, high=high, low=low, per_share=per_share,
            upper=high / per_share, lower=low / per_share, sessions=sessions,
        ))

        if p.month != 12:
            band.notes.append(f"회계연도 말이 {p.month}월이라 역년(1~12월) 시세로 근사했습니다")
    if metric == "PSR" and band.years:
        band.notes.append("주당매출은 현재 발행주식수로 나눈 근사치입니다")
    if not band.years:
        band.notes.append("밴드에 쓸 수 있는 연도가 없습니다")
    elif len(band.years) == 1:
        band.notes.append(
            f"밴드에 쓸 수 있는 연도가 {band.years[0].year}년 하나뿐입니다 — "
            "단일 연도 밴드는 그 해 사정에 좌우되므로 목표주가 신뢰도가 낮습니다"
        )
    elif len(band.years) >= 2:
        uppers = [y.upper for y in band.years]
        if min(uppers) > 0 and max(uppers) / min(uppers) > 2:
            band.notes.append(
                "연도 간 멀티플 편차가 큽니다 — 이익이 급감했던 해가 밴드(그리고 목표주가)를 "
                "부풀렸을 수 있으니, 해석 시 해당 연도 제외 여부를 검토하세요"
            )
    # 중복 사유 제거 (회계연도 근사 등이 연도마다 반복되지 않게)
    band.notes = list(dict.fromkeys(band.notes))
    return band


# ---------------------------------------------------------------- 이익 기준

def _fmt(value: float | None, currency: str) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}" if currency == "USD" else f"{value:,.0f}원"


def earnings_basis(
    metric: str,
    snap: Snapshot,
    val: ValuationResult,
    annual: FinancialTable,
) -> EarningsBasis:
    """이익 3단계 (보수·기준·낙관)와 각 값의 출처 라벨."""
    basis = EarningsBasis(metric=metric)
    cur = val.columns[0] if val.columns else None

    if metric == "PER":
        ttm = cur.eps_ttm.value if (cur and cur.eps_ttm.is_ok) else snap.eps_naver
        fwd = snap.cns_eps_naver
        cons = [
            (p, annual.value(EPS, p.key))
            for p in annual.consensus_periods()
            if annual.value(EPS, p.key) is not None
        ]
        next_year = cons[-1] if len(cons) >= 2 else None  # 마지막이 차년도 컨센서스

        ttm_label = f"TTM EPS {_fmt(ttm, snap.currency)}"
        fwd_label = f"연간 컨센서스 EPS {_fmt(fwd, snap.currency)}"

        basis.base = fwd if fwd is not None else ttm
        basis.base_label = fwd_label if fwd is not None else ttm_label

        pool = [(v, lb) for v, lb in ((ttm, ttm_label), (fwd, fwd_label)) if v is not None]
        if pool:
            basis.conservative, basis.conservative_label = min(pool, key=lambda t: t[0])

        if next_year is not None:
            basis.optimistic = next_year[1]
            basis.optimistic_label = f"{next_year[0].year}년 연간 컨센서스 EPS {_fmt(next_year[1], snap.currency)}"
        else:
            basis.optimistic, basis.optimistic_label = basis.base, basis.base_label
    else:  # PSR — 주당매출
        shares = snap.shares_outstanding
        rev_ttm = cur.revenue_ttm.value if (cur and cur.revenue_ttm.is_ok) else None
        ttm_ps = rev_ttm / shares if (rev_ttm and shares) else None
        cons_rev = [
            (p, annual.value(REVENUE, p.key))
            for p in annual.consensus_periods()
            if annual.value(REVENUE, p.key) is not None
        ]
        fwd_ps = (cons_rev[0][1] * annual.money_unit / shares) if (cons_rev and shares) else None
        next_ps = (cons_rev[-1][1] * annual.money_unit / shares) if (len(cons_rev) >= 2 and shares) else None

        basis.base = fwd_ps if fwd_ps is not None else ttm_ps
        basis.base_label = ("연간 컨센서스 주당매출" if fwd_ps is not None else "TTM 주당매출") \
            + f" {_fmt(basis.base, snap.currency)}"
        pool = [v for v in (ttm_ps, fwd_ps) if v is not None]
        if pool:
            basis.conservative = min(pool)
            basis.conservative_label = f"보수 주당매출 {_fmt(basis.conservative, snap.currency)}"
        basis.optimistic = next_ps if next_ps is not None else basis.base
        basis.optimistic_label = (
            f"{cons_rev[-1][0].year}년 컨센서스 주당매출 {_fmt(next_ps, snap.currency)}"
            if next_ps is not None else basis.base_label
        )
    return basis


# ---------------------------------------------------------------- 목표주가

def target_price(band: Band, basis: EarningsBasis, price: float | None) -> TargetPrice:
    t = TargetPrice(band=band, basis=basis, price=price)
    lower, mid, upper = band.lower, band.mid, band.upper
    if lower is None:
        t.note = "밴드가 없어 목표주가를 계산하지 못했습니다 (" + " · ".join(band.notes) + ")"
        return t

    def mul(m: float | None, e: float | None) -> float | None:
        return m * e if (m is not None and e is not None and e > 0) else None

    t.bear = mul(lower, basis.conservative)
    t.base = mul(mid, basis.base)
    t.bull = mul(upper, basis.optimistic)
    t.sensitivity = [
        [mul(m, e) for e in (basis.conservative, basis.base, basis.optimistic)]
        for m in (lower, mid, upper)
    ]
    t.note = (
        f"Bear = 밴드 하단 {lower:.1f}배 × {basis.conservative_label or '—'} · "
        f"Base = 중간 {mid:.1f}배 × {basis.base_label or '—'} · "
        f"Bull = 상단 {upper:.1f}배 × {basis.optimistic_label or '—'}"
    )
    return t


# ---------------------------------------------------------------- 투자의견

def investment_opinion(cans: CanslimResult, target: TargetPrice) -> Opinion:
    """지침 v3 Step 10 결합 규칙. CANSLIM이 1차 관문, Base 괴리율이 2차."""
    verdicts = {i.letter: i.verdict for i in cans.items}
    failed = {L for L, v in verdicts.items() if v == Verdict.FAIL}
    gap = target.base_gap

    # 매도/비중 축소 사유는 다른 어떤 결론보다 먼저 본다
    sell: list[str] = []
    if cans.failed >= SELL_FAILED:
        sell.append(f"불합격 항목이 {cans.failed}개")
    if "M" in failed:
        sell.append("M(시장 방향) 불합격 — 시장이 조정 국면")
    if "C" in failed and "L" in failed:
        sell.append("C·L 동시 불합격 — 실적 둔화 + 주도력 상실")
    if gap is not None and gap <= SELL_GAP:
        sell.append(f"Base 목표가 괴리율 {gap:+.1f}% ≤ {SELL_GAP:.0f}%")
    if sell:
        return Opinion("매도/비중 축소", "🔻", sell)

    if gap is None:
        return Opinion("판단 보류", "⏸", ["목표주가를 계산하지 못해 결합 규칙을 적용할 수 없습니다",
                                          target.note or ""])

    if cans.qualified and gap > 0:
        return Opinion("매수", "🟢", [f"CANSLIM 충족 + Base 괴리율 {gap:+.1f}% > 0"])

    if cans.failed == 0 and cans.unknown > 0 and gap > 0:
        return Opinion("조건부 매수 후보", "🟡", [
            f"불합격 0개(판단불가 {cans.unknown}개) + Base 괴리율 {gap:+.1f}% > 0",
            "S·I·M 등 판단불가 항목의 자료 확인 필요",
        ])

    reasons = []
    if cans.failed:
        reasons.append(f"불합격 {cans.failed}개 ({'·'.join(sorted(failed))})")
    if gap <= 0:
        reasons.append(f"Base 목표가 괴리율 {gap:+.1f}% ≤ 0")
    return Opinion("중립", "⚪", reasons or ["결합 규칙상 매수·매도 어느 쪽도 아님"])
