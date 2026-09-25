"""클로드 프로젝트 인계 요약 (마크다운).

앱이 계산·검증한 수치를 전부 담은 텍스트를 만든다. 사용자가 이것을
클로드 프로젝트(지침 v3)에 붙여넣으면, 그쪽 클로드는 수치 수집·검산(Step 1)을
건너뛰고 판단이 필요한 단계(지표 선정 이유·피어 비교·프리미엄/디스카운트·
핵심 가정·촉매·리스크)에 검색 예산을 집중할 수 있다. 추가 비용 0원 구조의 연결 고리.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from .valuation import EPS, REVENUE

if TYPE_CHECKING:  # 순환 import 방지 — 실행 시에는 duck typing 으로 충분
    from .analyze import Analysis

HEADER_INSTRUCTION = (
    "> **지시**: 아래는 분석 앱이 출처(네이버 금융/야후 파이낸스)에서 받아 검증까지 마친 수치입니다. "
    "Step 1(수치 수집·검산)은 건너뛰고, **Step 3 지표 선정 이유 · Step 4 피어 선정과 비교 · "
    "Step 7 프리미엄/디스카운트 · Step 10 핵심 가정/의견 변경 조건/촉매/리스크**의 판단과 해석에 "
    "집중해 주세요. 검색은 피어 수치와 최근 1년 내 정성 사실 확인에만 쓰세요. "
    "아래 수치와 다른 숫자를 만들어내지 마세요."
)


def _fmt(value, currency: str, digits: int | None = None) -> str:
    if value is None:
        return "—"
    if currency == "USD":
        return f"${value:,.{2 if digits is None else digits}f}"
    return f"{value:,.{0 if digits is None else digits}f}원"


def build_handoff(a: "Analysis") -> str:
    snap, val, cans = a.snap, a.valuation, a.canslim
    money = snap.money
    lines: list[str] = []
    add = lines.append

    add(f"# {snap.name} ({a.ref.code} · {a.ref.market}) — 앱 분석 요약")
    add(f"생성 {dt.date.today().isoformat()} · 가격 기준일 {snap.price_date_label or '—'}"
        + (f" · 컨센서스 {snap.consensus_date}" if snap.consensus_date else ""))
    add("")
    add(HEADER_INSTRUCTION)

    # ── 데이터 신뢰도 ──
    ver = a.verification
    add("\n## 데이터 신뢰도 (앱 검증 결과)")
    add(f"- 등급 집계: {ver.tally}")
    if ver.cap_text:
        add(f"- 시총 검산: {ver.cap_text}")
    add(f"- PER 교차검증: {val.per_cross_check}")

    # ── 시세 ──
    add("\n## 시세")
    add(f"- 현재가 {money(snap.price)} · 시가총액 {snap.money_big(snap.market_cap)}"
        f" · 52주 최고 대비 {snap.price / snap.high_52w:.0%}"
        if snap.price and snap.high_52w and snap.market_cap
        else f"- 현재가 {money(snap.price)}")
    for c in ver.checks:
        if c.item.startswith(("50일선", "수익률")):
            add(f"- {c.item}: {c.value}")

    # ── CANSLIM ──
    add(f"\n## CANSLIM 판정 (앱 기준서 기준): {cans.summary} ({cans.tally})")
    for i in cans.items:
        add(f"- **{i.letter} {i.name}** {i.verdict.badge} {i.verdict.value}: "
            + i.checks_text.replace("\n", " · "))

    # ── 밸류에이션 ──
    add("\n## 밸류에이션 (자체 계산)")
    cur = val.columns[0] if val.columns else None
    if cur:
        bits = [f"PER(TTM) {cur.per.value:,.2f}배" if cur.per.is_ok else "PER(TTM) —",
                f"PSR {cur.psr.value:,.2f}배" if cur.psr.is_ok else "PSR —",
                f"PEG {cur.peg.value:,.2f}" if cur.peg.is_ok else "PEG —",
                f"ROE {cur.roe.value:,.1f}%" if cur.roe.is_ok else "ROE —",
                f"PBR {snap.pbr:,.2f}배" if snap.pbr else "PBR —"]
        add("- " + " · ".join(bits))
    if snap.cns_eps_naver and snap.price and snap.cns_eps_naver > 0:
        add(f"- Fwd PER {snap.price / snap.cns_eps_naver:,.2f}배 "
            f"(연간 컨센서스 EPS {money(snap.cns_eps_naver)})")

    # ── 밴드·목표주가·의견 ──
    band, target, opinion = a.band, a.target, a.opinion
    add(f"\n## 밸류에이션 밴드 ({band.metric}, 최근 확정 연도)")
    for y in band.years:
        add(f"- {y.year}년: 고점 {money(y.high)} / 저점 {money(y.low)} → "
            f"{band.metric} {y.lower:,.1f}~{y.upper:,.1f}배")
    if band.years:
        add(f"- 밴드 평균: 하단 {band.lower:,.1f}배 · 중간 {band.mid:,.1f}배 · 상단 {band.upper:,.1f}배")
    for n in band.notes:
        add(f"- (주의) {n}")

    add("\n## 목표주가 (앱 계산, 12개월)")
    if target.ok:
        add(f"- Bear {money(target.bear)} ({target.bear_gap:+.1f}%) · "
            f"Base {money(target.base)} ({target.base_gap:+.1f}%) · "
            f"Bull {money(target.bull)} ({target.bull_gap:+.1f}%)")
        add(f"- 산식: {target.note}")
    else:
        add(f"- 산출 불가: {target.note}")
    add(f"- 투자의견(규칙 기반): {opinion.text} — " + " / ".join(r for r in opinion.reasons if r))

    # ── 재무 건전성 ──
    add("\n## 재무 건전성 (확인된 것만)")
    a_actual = [p for p in a.annual.actual_periods() if a.annual.value(EPS, p.key) is not None]
    debt = (a.annual.value("부채비율", a_actual[-1].key) if a_actual else None) \
        if snap.currency == "KRW" else snap.debt_to_equity
    add(f"- 부채비율: {f'{debt:,.1f}%' if debt is not None else '확인 불가'}")
    dps = a.annual.value("주당배당금", a_actual[-1].key) if (a_actual and snap.currency == "KRW") else None
    if dps is not None:
        add(f"- 주당배당금 {dps:,.0f}원 · 배당수익률 {snap.dividend_yield or 0:,.2f}%")
    elif snap.dividend_yield is not None:
        add(f"- 배당수익률 {snap.dividend_yield:,.2f}%")
    if snap.fcf is not None:
        add(f"- FCF(최근 연간) ${snap.fcf / 1e9:,.1f}B")
    add("- FCF·순차입금·EV/EBITDA는 앱 출처에 없음 — 필요하면 검색으로 보완")

    # ── 매출 구성 ──
    if a.segments:
        add(f"\n## 주요 제품·서비스 매출 구성 (기준 {a.segments.period_label or '—'})")
        for rank, s in enumerate(a.segments.items, start=1):
            desc = f" — {s.description}" if s.description else ""
            add(f"{rank}. {s.name}: {s.share_pct:,.1f}%{desc}")

    # ── 재료 ──
    if a.newness.items:
        add(f"\n## 최근 재료 (최근 {a.newness.window_days}일, 제목 자동 분류)")
        for item in a.newness.items:
            add(f"- [{item.category}] {item.title} ({item.date_text} · {item.source})")

    add("\n---")
    add("이 요약은 참고 자료이며 매수·매도 신호가 아닙니다. 위 지시에 따라 해석을 이어가 주세요.")
    return "\n".join(lines)
