"""클로드용 앱 분석 요약 (마크다운) — 클로드가 '완성 보고서'를 쓰도록 자료와 출력 형식을 함께 담는다.

앱이 계산·검증한 수치를 앱 화면과 같은 순서(① 1분 브리핑 → ② 상세 → ③ 목표주가 → ④ 밸류에이션
→ ⑤ CANSLIM)로 정리하고, 맨 아래에 같은 순서의 보고서 형식(REPORT_FORMAT)을 붙인다.
클로드 프로젝트(지침 v3)에 붙여넣든, 이 PC의 Claude Code(ai_local)로 보내든 결과는
화면 순서 그대로의 완성 보고서 한 편이 된다. 추가 비용 0원 구조의 연결 고리.
"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from . import brief
from .valuation import EPS, REVENUE

if TYPE_CHECKING:  # 순환 import 방지 — 실행 시에는 duck typing 으로 충분
    from .analyze import Analysis

DISCLAIMER = "이 분석은 투자 판단을 돕는 참고 자료이며, 투자 결정과 결과는 본인 책임입니다."

HEADER_INSTRUCTION = (
    "> **지시**: 아래는 분석 앱이 출처(네이버 금융/야후 파이낸스)에서 받아 검증까지 마친 수치입니다. "
    "이 자료로 **맨 아래 '출력 형식'의 순서 그대로 완성 보고서 한 편**을 작성해 주세요 "
    "(앱 화면과 같은 순서: ① 1분 브리핑 → ② 상세 → ③ 목표주가 → ④ 밸류에이션 → ⑤ CANSLIM). "
    "Step 1(수치 수집·검산)과 Step 2(CANSLIM 재판정)는 하지 말고, 검색은 피어 수치와 최근 1년 내 "
    "정성 사실 확인에만 쓰세요. 아래 수치와 다른 숫자를 만들어내지 마세요."
)

# 보고서 제목 줄 — 앱 화면의 큰 제목과 같아야 한다 (tests 에서 순서를 확인)
SECTION_TITLES = ["① 1분 브리핑", "② 상세 — 실적 · 재무", "③ 목표주가와 투자의견",
                  "④ 밸류에이션", "⑤ CANSLIM 판정", "데이터 신뢰도와 한계"]

REPORT_FORMAT = f"""## 출력 형식 — 완성 보고서 (앱 화면과 같은 순서)
서론·맺음 인사 없이 바로 아래 제목 그대로, 이 순서로 작성하십시오. 이 보고서 한 편으로 완결되어야 합니다
(앱 화면을 함께 보지 않아도 이해되게). 앱 수치는 그대로 옮기고 '[앱]'으로만 표시하며,
검색으로 새로 얻은 수치에만 [출처, 기준일]을 붙이십시오. 수치 비교는 표를 쓰십시오.

# {{종목명}} 분석 보고서 ({{가격 기준일}})
표 하나(항목 | 내용), 이 순서로: 현재가 · PER(TTM, Fwd 함께) · PEG(성장률 기준 함께) · 52주 최고 대비 · CANSLIM 판정 · 목표주가 Bear–Base–Bull · 최종 투자의견 · 데이터 신뢰도 · 시가총액(참고)

## {SECTION_TITLES[0]}
### 무슨 회사인가
2~3문장. 무엇을 만들고 누구에게 파는지, 업종 안에서의 위치.
### 무엇으로 버나
매출 구성 표(순위 | 제품·서비스 | 비중 | 설명, 1위에 ⭐)와 한 줄 해석. 앱 자료가 없으면(미국 종목 등) 반드시 검색으로 채우십시오 — 최근 연차보고서(10-K)·실적 발표의 사업부문(Segment)·제품별 매출로 표를 만들고 비중은 '부문 매출 ÷ 총매출'로 직접 계산, 표 아래에 [출처, 회계연도]. 검색 2회로도 못 찾을 때만 '확인 불가'.
### 실적과 주가
앱의 실적 성장률·주가 수익률을 옮기고 그 의미를 2~3줄로.
### 새로운 변화
최근 재료 중 의미 있는 것 2~4개와 왜 중요한지.
### 결론 한 줄
최종 투자의견과 핵심 이유를 한 문장으로.

## {SECTION_TITLES[1]}
### 실적 추이
분기·연간 실적 표와 해석(성장 동력, 일회성 여부, 컨센서스와의 관계).
### 재무 건전성과 주주환원
부채비율·FCF·배당 등 각 1~2줄 (Step 6). 앱에 없는 값은 검색하거나 '확인 불가'.

## {SECTION_TITLES[2]}
### 목표주가
앱의 Bear / Base / Bull 표를 옮기고 전제를 검토하십시오 (Step 9 — 특히 이익 급감 연도가 밴드를 부풀리지 않았는지).
조정이 필요하면 조정 목표가를 같은 표 형식으로 함께 제시하고, 아니면 '조정 없음'과 이유.
### 투자의견과 논리
최종 투자의견(앱 규칙 의견과 다르면 이유), 결론이 의존하는 핵심 가정 3개, 각 가정이 틀렸을 때 의견 변경 조건,
6~12개월 촉매와 일정, 가장 큰 리스크 2개 (Step 10).

## {SECTION_TITLES[3]}
### 지표 선정과 이익 기준
앱이 고른 지표·이익 기준이 맞는지와 이유 (Step 3). PER·PSR·PEG 등 현재 멀티플 표.
### 피어 비교
피어 2~3개 선정 근거와 비교 표 필수 (Step 4).
### 밸류에이션 밴드
앱 밴드 표를 옮기고 해석 (Step 5).
### 프리미엄·디스카운트
할증(+)/할인(-) 근거 각 2~3개와 멀티플 조정 폭 (Step 7).

## {SECTION_TITLES[4]}
표: 항목 | 판정 🟢/🔴/⚪ | 핵심 근거 — 앱 판정을 그대로 옮기십시오(다시 판정하지 않음).
이어서 종합 해석 2~3줄: 가장 약한 항목, 충족까지 무엇이 바뀌어야 하는지.

## {SECTION_TITLES[5]}
앱 검증 결과 요약, 판단불가 사유, 검색으로 확인하지 못한 것.

마지막 줄: "{DISCLAIMER}"
"""


def _quarter_rows(a: "Analysis") -> list[str]:
    usd = a.snap.currency == "USD"
    rows = ["| 분기 | EPS | 매출액 | 구분 |", "|---|---|---|---|"]
    for p in a.quarterly.periods:
        eps, rev = a.quarterly.value(EPS, p.key), a.quarterly.value(REVENUE, p.key)
        if eps is None and rev is None:
            continue
        eps_t = "—" if eps is None else (f"${eps:,.2f}" if usd else f"{eps:,.0f}원")
        rev_t = "—" if rev is None else (f"{rev / 1e8:,.1f}억$" if usd else f"{rev:,.0f}억원")
        rows.append(f"| {p.label} | {eps_t} | {rev_t} | {'컨센서스' if p.is_consensus else '확정'} |")
    return rows if len(rows) > 2 else []


def _annual_rows(a: "Analysis") -> list[str]:
    usd = a.snap.currency == "USD"
    rows = ["| 연도 | EPS | 매출액 | 구분 |", "|---|---|---|---|"]
    for p in a.annual.periods:
        eps, rev = a.annual.value(EPS, p.key), a.annual.value(REVENUE, p.key)
        if eps is None and rev is None:
            continue
        eps_t = "—" if eps is None else (f"${eps:,.2f}" if usd else f"{eps:,.0f}원")
        rev_t = "—" if rev is None else (f"{rev / 1e8:,.0f}억$" if usd else f"{rev:,.0f}억원")
        rows.append(f"| {p.label} | {eps_t} | {rev_t} | {'컨센서스' if p.is_consensus else '확정'} |")
    return rows if len(rows) > 2 else []


def build_handoff(a: "Analysis") -> str:
    snap, val, cans = a.snap, a.valuation, a.canslim
    money = snap.money
    ver = getattr(a, "verification", None)
    band, target, opinion = getattr(a, "band", None), getattr(a, "target", None), getattr(a, "opinion", None)
    lines: list[str] = []
    add = lines.append

    add(f"# {snap.name} ({a.ref.code} · {a.ref.market}) — 앱 분석 요약")
    add(f"생성 {dt.date.today().isoformat()} · 가격 기준일 {snap.price_date_label or '—'}"
        + (f" · 컨센서스 {snap.consensus_date}" if snap.consensus_date else ""))
    add("")
    add(HEADER_INSTRUCTION)

    # ── ① 1분 브리핑 자료 ──
    add(f"\n## {SECTION_TITLES[0]} 자료")
    add("### 시세")
    mult = brief.multiples(a)
    add(f"- 현재가 {money(snap.price)} · PER {mult.per} ({mult.per_sub}) · PEG {mult.peg} ({mult.peg_sub})")
    add(f"- 52주 최고 대비 {brief.high_ratio_text(a)}")
    if snap.market_cap:
        add(f"- 시가총액(참고) {snap.money_big(snap.market_cap)}")
    for c in (ver.checks if ver else []):
        if c.item.startswith(("50일선", "수익률")):
            add(f"- {c.item}: {c.value}")

    if snap.summary:
        add("\n### 회사 개요 (출처 기업개요)")
        add(snap.summary)

    seg = brief.segment_table(a)
    add("\n### 주요 제품·서비스 매출 구성")
    if seg.rows:
        add("| 순위 | 제품·서비스 | 비중 | 추정 매출액 | 설명 |")
        add("|---|---|---|---|---|")
        for r in seg.rows:
            add(f"| {r.rank} | {r.name} | {r.share} | {r.amount} | {r.description} |")
        add(f"- {seg.note}")
    else:
        add(f"- {seg.missing}")
        add("- **클로드 작업**: 이 표는 앱에 없으므로 보고서의 '무엇으로 버나'를 검색으로 채우세요 "
            "(최근 10-K·실적 발표의 사업부문/제품별 매출 → 비중 직접 계산, 출처와 회계연도 표기).")

    add("\n### 실적과 주가")
    for label, value in brief.performance(a).lines:
        add(f"- {label}: {value}")

    add(f"\n### 최근 재료 (최근 {a.newness.window_days}일, 제목 자동 분류 · 최신순)")
    news = brief.new_items(a, limit=10)
    for n in news:
        add(f"- [{n.category}] {n.title} ({n.date} · {n.source})")
    if not news:
        add("- 재료로 분류된 공시·뉴스 없음")

    # ── ② 상세 자료 ──
    add(f"\n## {SECTION_TITLES[1]} 자료")
    q_rows = _quarter_rows(a)
    if q_rows:
        add("### 분기 실적")
        lines.extend(q_rows)
    y_rows = _annual_rows(a)
    if y_rows:
        add("\n### 연간 실적")
        lines.extend(y_rows)

    add("\n### 재무 건전성 (확인된 것만)")
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
    add("- FCF·순차입금·EV/EBITDA·총주주환원율은 앱 출처에 없음 — 필요하면 검색으로 보완")

    # ── ③ 목표주가·의견 ──
    add(f"\n## {SECTION_TITLES[2]} (앱 계산, 12개월)")
    if target and target.ok:
        add("| 시나리오 | 목표가 | 괴리율 |")
        add("|---|---|---|")
        add(f"| Bear | {money(target.bear)} | {target.bear_gap:+.1f}% |")
        add(f"| Base | {money(target.base)} | {target.base_gap:+.1f}% |")
        add(f"| Bull | {money(target.bull)} | {target.bull_gap:+.1f}% |")
        add(f"- 산식: {target.note}")
    elif target:
        add(f"- 산출 불가: {target.note}")
    if opinion:
        add(f"- 투자의견(규칙 기반): {opinion.text} — " + " / ".join(r for r in opinion.reasons if r))

    # ── ④ 밸류에이션 ──
    add(f"\n## {SECTION_TITLES[3]} 자료 (자체 계산)")
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
    if val.per_cross_check:
        add(f"- PER 교차검증: {val.per_cross_check}")
    if band:
        add(f"\n### 밸류에이션 밴드 ({band.metric}, 최근 확정 연도)")
        if band.years:
            add(f"| 연도 | 고점 | 저점 | {band.metric} 밴드 |")
            add("|---|---|---|---|")
            for y in band.years:
                add(f"| {y.year}년 | {money(y.high)} | {money(y.low)} | {y.lower:,.1f}~{y.upper:,.1f}배 |")
            add(f"- 밴드 평균: 하단 {band.lower:,.1f}배 · 중간 {band.mid:,.1f}배 · 상단 {band.upper:,.1f}배")
        for n in band.notes:
            add(f"- (주의) {n}")

    # ── ⑤ CANSLIM ──
    add(f"\n## {SECTION_TITLES[4]} (앱 기준서 기준): {cans.summary} ({cans.tally})")
    for i in cans.items:
        add(f"- **{i.letter} {i.name}** {i.verdict.badge} {i.verdict.value}: "
            + i.checks_text.replace("\n", " · "))

    # ── 데이터 신뢰도 ──
    add("\n## 데이터 신뢰도 (앱 검증 결과)")
    if ver:
        add(f"- 등급 집계: {ver.tally}")
        if ver.cap_text:
            add(f"- 시총 검산: {ver.cap_text}")
    add("- S·I·M3 등 일별 수급·지수 거래량이 필요한 항목은 앱 판정을 그대로 쓰세요.")

    add("\n---\n")
    add(REPORT_FORMAT)
    return "\n".join(lines)
