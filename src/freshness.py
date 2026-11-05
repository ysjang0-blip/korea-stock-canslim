"""데이터 반영 시점 점검 — 어떤 값이 최신 분기까지 반영됐고 어떤 값이 한 분기 늦은지.

네이버·야후 재무표는 실적 발표 뒤 며칠~몇 주 늦게 새 분기를 싣는다. 반면 야후 실적 발표 이력
(`EPS(발표)`)은 발표 직후 나온다. 그래서 발표 이력에만 있는 새 분기가 생기면:
  * EPS 로 판정하는 CANSLIM C1~C3 는 그 분기까지 반영하고 (canslim.c_eps_row)
  * 재무표로만 계산하는 값(매출 C4 · PER·PSR·PEG · 12개월 EPS/매출 · ROE)은 한 분기 늦다.
늦은 쪽을 화면·인계 요약·보고서에 분명히 적는다.
"""

from __future__ import annotations

from .eps_history import EPS_REPORTED
from .fundamentals import FinancialTable, Period
from .valuation import EPS, REVENUE


def _label(key: str) -> str:
    return f"{key[:4]}.{key[4:]}"


def newer_reported_quarter(quarterly: FinancialTable) -> tuple[Period, float] | None:
    """재무표의 EPS 최신 확정 분기보다 뒤에 있는 발표 이력의 가장 새 분기와 그 EPS. 없으면 None."""
    table = [p for p in quarterly.actual_periods() if quarterly.value(EPS, p.key) is not None]
    reported = {k: v for k, v in quarterly.rows.get(EPS_REPORTED, {}).items() if v is not None}
    if not table or not reported:
        return None
    newest = max(reported)
    if newest <= table[-1].key:
        return None
    return Period(key=newest, title=f"{_label(newest)}.", is_consensus=False), reported[newest]


def lag_notes(quarterly: FinancialTable, c_advanced: bool, usd: bool = False) -> list[str]:
    """반영이 늦은 항목 안내문. 첫 줄이 제목이고 나머지는 세부. 늦은 게 없으면 빈 목록."""
    hit = newer_reported_quarter(quarterly)
    if hit is None:
        return []
    new, eps = hit
    table = [p for p in quarterly.actual_periods() if quarterly.value(EPS, p.key) is not None]
    old = table[-1]
    rev = [p for p in quarterly.actual_periods() if quarterly.value(REVENUE, p.key) is not None]
    rev_label = rev[-1].label if rev else old.label
    eps_text = f"${eps:,.2f}" if usd else f"{eps:,.0f}원"

    notes = [f"업데이트 지연 — 재무표는 {old.label} 분기까지인데, 야후 실적 발표 이력에는 "
             f"{new.label} 분기 EPS({eps_text})가 이미 나왔습니다"]
    if c_advanced:
        notes.append(f"✅ 반영됨: CANSLIM C1~C3(분기 EPS)는 {new.label} 분기 기준입니다")
    else:
        notes.append(f"⏳ 미반영: {new.label} 분기의 전년 동기 자료가 모자라 CANSLIM C는 {old.label} 분기 기준입니다")
    notes.append(f"⏳ 한 분기 늦음(재무표 갱신 대기): 매출(C4, {rev_label} 기준) · PER·PSR·PEG · "
                 f"12개월 EPS·매출 · ROE는 {old.label} 분기까지만 반영돼 있습니다")
    return notes
