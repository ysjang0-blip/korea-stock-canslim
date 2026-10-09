"""1분 브리핑 — '무슨 회사이고, 무엇으로 벌고, 실적·주가가 어떻고, 무엇이 새로운가'.

화면(app.py)과 Word 리포트(report.py)가 같은 숫자를 쓰도록 계산을 여기에 모은다.
여기서는 문자열만 만든다 — 배치·색은 각 출력 쪽이 정한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from . import prices, segments as segments_mod
from .valuation import EPS, REVENUE, yoy

if TYPE_CHECKING:
    from .analyze import Analysis

RETURN_WINDOWS = (("3개월", 63), ("6개월", 126), ("12개월", 252))
NEW_ITEMS_LIMIT = 5


@dataclass(frozen=True)
class SegmentRow:
    rank: int
    name: str
    share: str          # '61.0%'
    amount: str         # '203.6조원' 또는 '—'
    description: str    # 설명, 없으면 '—'


@dataclass
class SegmentTable:
    rows: list[SegmentRow] = field(default_factory=list)
    note: str = ""      # 출처·추정 방식 설명 (표 아래 캡션)
    missing: str = ""   # 표를 못 만든 이유 (있으면 rows 는 비어 있음)


def segment_table(a: "Analysis") -> SegmentTable:
    """매출 구성 표. 추정액 = 최근 확정 연간 매출 × 비중."""
    if a.snap.currency == "USD":
        return SegmentTable(missing="미국 종목은 제품별 매출을 주는 무료 출처가 없습니다. "
                                    "회사 연차보고서(10-K)의 사업 부문(Segment) 절을 참고하세요.")
    segs = getattr(a, "segments", None)
    if segs is None:
        return SegmentTable(missing="이 종목의 제품·서비스별 매출 구성 자료를 받아오지 못했습니다 "
                                    "(출처에 자료가 없거나 일시적 오류).")

    annual_actual = a.annual.actual_periods()
    rev_won = None
    if annual_actual:
        rev = a.annual.value(REVENUE, annual_actual[-1].key)
        if rev is not None:
            rev_won = rev * a.annual.money_unit

    rows = [
        SegmentRow(
            rank=rank,
            name=s.name,
            share=f"{s.share_pct:,.1f}%",
            amount=segments_mod.amount_text(rev_won * s.share_pct / 100 if rev_won else None),
            description=s.description or "—",
        )
        for rank, s in enumerate(segs.items, start=1)
    ]
    period = f" (기준: {segs.period_label})" if segs.period_label else ""
    base = (f"최근 확정 연간 매출 {segments_mod.amount_text(rev_won)}({annual_actual[-1].label})에 "
            "비중을 곱한 추정치" if rev_won else "연간 매출 자료가 없어 금액은 표시하지 못했습니다")
    note = (f"출처: 네이버 종목분석의 주요제품 매출구성{period} · 1위 강조. "
            "회사가 부문으로 묶어 공시하면(예: 삼성전자 DS·DX) 부문 이름으로 보이고, 설명은 기업개요 "
            f"문장에서 자동으로 뽑아 없을 수 있습니다. 추정 매출액은 {base}이며, 내부거래 조정으로 "
            "'기타'가 음수이거나 합계가 100%와 다를 수 있습니다.")
    return SegmentTable(rows=rows, note=note)


@dataclass
class Performance:
    lines: list[tuple[str, str]] = field(default_factory=list)   # (항목, 값)


def _pct(value: float | None) -> str:
    return f"{value:+,.1f}%" if value is not None else "—"


def performance(a: "Analysis") -> Performance:
    """실적과 주가 성과 요약."""
    g = a.valuation.growth
    perf = Performance()

    q_label = g.latest_quarter_label or "최근 분기"
    perf.lines.append((f"분기 EPS 전년비 ({q_label})",
                       _pct(g.quarter_yoy.value) if g.quarter_yoy.is_ok else "—"))

    q_actual = [p for p in a.quarterly.actual_periods() if a.quarterly.value(REVENUE, p.key) is not None]
    rev_yoy = None
    if q_actual:
        last = q_actual[-1]
        rev_yoy = yoy(a.quarterly.value(REVENUE, last.key),
                      a.quarterly.value(REVENUE, f"{last.year - 1}{last.month:02d}"))
    perf.lines.append((f"분기 매출 전년비 ({q_actual[-1].label if q_actual else '—'})", _pct(rev_yoy)))

    perf.lines.append((f"연간 EPS 성장률 ({g.annual_cagr_years}년 연평균)",
                       _pct(g.annual_cagr.value) if g.annual_cagr.is_ok else "—"))

    close = a.stock_df["close"] if "close" in a.stock_df else pd.Series(dtype=float)
    idx = a.index_df["close"] if "close" in a.index_df else pd.Series(dtype=float)
    bits = []
    for label, days in RETURN_WINDOWS:
        s, i = prices.pct_return(close, days), prices.pct_return(idx, days)
        bits.append(f"{label} {_pct(s)} (지수 {_pct(i)})")
    perf.lines.append((f"주가 수익률 vs {a.index_name}", " · ".join(bits)))
    return perf


@dataclass(frozen=True)
class NewItem:
    date: str
    category: str
    title: str
    source: str


def new_items(a: "Analysis", limit: int = NEW_ITEMS_LIMIT) -> list[NewItem]:
    """최근 재료를 최신순으로."""
    items = sorted(a.newness.items, key=lambda i: i.date.toordinal() if i.date else 0, reverse=True)
    return [NewItem(i.date_text, i.category, i.title, i.source) for i in items[:limit]]


def high_ratio_text(a: "Analysis") -> str:
    s = a.snap
    if not (s.price and s.high_52w):
        return "—"
    return f"{s.price / s.high_52w:.0%} (52주 최고 {s.money(s.high_52w)})"


@dataclass
class Conclusion:
    canslim: str
    canslim_ok: bool
    opinion: str
    opinion_label: str
    target: str
    reliability: str
    ai_one_liner: str = ""


def conclusion(a: "Analysis", ai_one_liner: str = "") -> Conclusion:
    s = a.snap
    t = getattr(a, "target", None)
    op = getattr(a, "opinion", None)
    ver = getattr(a, "verification", None)
    target = (f"Bear {s.money(t.bear)} · Base {s.money(t.base)} ({t.base_gap:+.1f}%) · Bull {s.money(t.bull)}"
              if t and t.ok else "산출 불가")
    return Conclusion(
        canslim=f"{a.canslim.summary} ({a.canslim.tally})",
        canslim_ok=a.canslim.qualified,
        opinion=op.text if op else "—",
        opinion_label=op.label if op else "",
        target=target,
        reliability=ver.tally if ver else "—",
        ai_one_liner=ai_one_liner,
    )
