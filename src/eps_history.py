"""분기 EPS 이력 보강.

네이버(한국)·야후 재무표(미국)는 확정 분기를 **5개**만 준다. CANSLIM C2("직전 분기도 전년 동기比
+17%")를 판정하려면 직전 분기의 1년 전, 즉 **6개**가 필요하다.

야후의 실적 발표 이력(earnings dates 의 Reported EPS)은 한국·미국 종목 모두 16분기 안팎을 주므로,
그것을 받아 `EPS(발표)` 행으로 재무표에 덧붙인다. 다만 출처가 다르면 EPS 정의(기본/희석, 조정 여부)가
조금 다를 수 있으므로:

  1. 발표 이력과 재무표가 **겹치는 분기**에서 값을 비교해, 20% 넘게 다르거나 부호가 다르면 버린다.
  2. 받아들여도 재무표의 `EPS` 행은 건드리지 않고 별도 행(`EPS(발표)`)으로 둔다.
     C1·C2 는 같은 행끼리만 비교하므로(발표 vs 발표) 정의 차이가 증가율에 섞이지 않는다.

발표일 → 분기 매핑: 발표는 분기 말 이후 약 한 달 뒤이므로 (발표일 − 45일)에 가장 가까운
회계 분기 말을 그 발표의 분기로 본다. 회계 분기 말 월은 재무표의 확정 분기에서 얻는다
(한국은 모두 3·6·9·12월, 미국은 회사마다 다르다 — 예: 엔비디아 1·4·7·10월).
"""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass

import pandas as pd

from .fundamentals import FinancialTable
from .valuation import EPS

EPS_REPORTED = "EPS(발표)"
CALENDAR_QUARTER_MONTHS = (3, 6, 9, 12)
LAG_DAYS = 45              # 발표일에서 분기 말까지 되짚어 가는 일수
MATCH_TOLERANCE = 0.20     # 겹치는 분기에서 허용하는 상대 오차
DEFAULT_LIMIT = 16         # 받아올 발표 건수 (분기)


def quarter_key_for(announced: dt.date, quarter_months=CALENDAR_QUARTER_MONTHS) -> str:
    """발표일이 어느 분기 실적인지. (발표일 − 45일)에 가장 가까운 회계 분기 말의 'YYYYMM'."""
    target = announced - dt.timedelta(days=LAG_DAYS)
    best_key, best_gap = "", None
    for year in (target.year - 1, target.year, target.year + 1):
        for month in quarter_months:
            end = dt.date(year, month, calendar.monthrange(year, month)[1])
            gap = abs((end - target).days)
            if best_gap is None or gap < best_gap:
                best_key, best_gap = f"{year}{month:02d}", gap
    return best_key


def map_earnings_to_quarters(
    rows: list[tuple[dt.date, float | None]], quarter_months=CALENDAR_QUARTER_MONTHS,
) -> dict[str, float]:
    """(발표일, 발표 EPS) 목록 → {분기 키: EPS}. 값이 없는 행은 건너뛰고,
    같은 분기로 잡힌 발표가 둘이면(정정 공시 등) 더 늦은 발표를 쓴다."""
    out: dict[str, float] = {}
    for announced, eps in sorted(rows, key=lambda r: r[0], reverse=True):
        if eps is None or pd.isna(eps):
            continue
        key = quarter_key_for(announced, quarter_months)
        out.setdefault(key, float(eps))
    return out


def fetch_reported_eps(symbol: str, quarter_months=CALENDAR_QUARTER_MONTHS,
                       limit: int = DEFAULT_LIMIT) -> dict[str, float]:
    """야후 실적 발표 이력에서 분기별 발표 EPS. 실패하면 빈 dict (보조 자료라 예외를 내지 않는다)."""
    try:
        import yfinance as yf

        frame = yf.Ticker(symbol).get_earnings_dates(limit=limit)
    except Exception:
        return {}
    if frame is None or frame.empty or "Reported EPS" not in frame.columns:
        return {}
    rows = []
    for ts, eps in frame["Reported EPS"].items():
        try:
            announced = pd.Timestamp(ts).date()
        except (TypeError, ValueError):
            continue
        rows.append((announced, eps))
    return map_earnings_to_quarters(rows, quarter_months)


@dataclass
class ExtendResult:
    accepted: bool
    added: int = 0           # 재무표에 없던 옛 분기 수
    note: str = ""


def extend_quarterly(quarterly: FinancialTable, reported: dict[str, float]) -> ExtendResult:
    """발표 EPS 를 교차검증한 뒤 `EPS(발표)` 행으로 덧붙인다. 재무표의 EPS 행은 그대로 둔다."""
    if not reported:
        return ExtendResult(False, note="야후 실적 발표 이력이 없어 옛 분기 EPS 를 보강하지 못했습니다")

    table_eps = {p.key: quarterly.value(EPS, p.key) for p in quarterly.actual_periods()}
    table_eps = {k: v for k, v in table_eps.items() if v is not None}
    overlap = sorted(k for k in reported if k in table_eps)
    if not overlap:
        return ExtendResult(False, note="야후 발표 EPS 와 재무표가 겹치는 분기가 없어 보강하지 않았습니다")

    worst = 0.0
    for key in overlap:
        mine, theirs = table_eps[key], reported[key]
        if (mine > 0) != (theirs > 0):
            return ExtendResult(False, note=(
                f"야후 발표 EPS 가 재무표와 부호부터 다릅니다 ({key[:4]}.{key[4:]}: "
                f"표 {mine:,.2f} vs 발표 {theirs:,.2f}) — 보강하지 않았습니다"))
        diff = abs(theirs - mine) / max(abs(mine), 1e-9)
        worst = max(worst, diff)
        if diff > MATCH_TOLERANCE:
            return ExtendResult(False, note=(
                f"야후 발표 EPS 가 재무표와 {diff:.0%} 차이 나서 보강하지 않았습니다 "
                f"({key[:4]}.{key[4:]}: 표 {mine:,.2f} vs 발표 {theirs:,.2f})"))

    quarterly.rows[EPS_REPORTED] = dict(reported)
    added = sum(1 for k in reported if k not in table_eps and k < min(table_eps))
    return ExtendResult(True, added=added, note=(
        f"옛 분기 EPS 는 야후 실적 발표 이력 {len(reported)}분기로 보강했습니다 "
        f"(겹치는 {len(overlap)}개 분기에서 재무표와 최대 {worst:.1%} 차이)"))
