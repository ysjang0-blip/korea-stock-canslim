"""분석 결과를 Word(.docx) 리포트로 만든다.

차트는 넣지 않는다 — 글과 표만. 화면(app.py)이 보여주는 것과 같은 숫자를
같은 서식으로 담아, 화면과 리포트가 다른 말을 하지 않게 한다.
"""

from __future__ import annotations

import datetime as dt
from io import BytesIO

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from . import segments as segments_mod
from .models import Source, Verdict

MALGUN = "맑은 고딕"
MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_SOURCE_MARK = {
    Source.ACTUAL: "실적확정",
    Source.CONSENSUS: "컨센서스",
    Source.DERIVED: "역산추정",
}


def _korean_style(style, size: float | None = None) -> None:
    """스타일 글꼴을 맑은 고딕으로. 라틴(w:ascii)만 바꾸면 한글은 기본 글꼴로 남는다."""
    style.font.name = MALGUN
    rpr = style.element.get_or_add_rPr()
    rpr.get_or_add_rFonts().set(qn("w:eastAsia"), MALGUN)
    if size is not None:
        style.font.size = Pt(size)


def _new_document() -> Document:
    doc = Document()
    _korean_style(doc.styles["Normal"], 10)
    for name in ("Title", "Heading 1", "Heading 2", "List Bullet"):
        if name in doc.styles:
            _korean_style(doc.styles[name])
    return doc


def _add_table(doc: Document, headers: list[str], rows: list[list[str]],
               widths_cm: list[float] | None = None, font_pt: int | None = None):
    """표 하나. widths_cm 를 주면 열 너비를 고정한다 (긴 근거 칸이 있는 표용)."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = text
        for p in cell.paragraphs:
            for run in p.runs:
                run.bold = True
    for row in rows:
        for cell, text in zip(table.add_row().cells, row):
            cell.text = text
    if widths_cm:
        table.autofit = False
        for row in table.rows:
            for cell, width in zip(row.cells, widths_cm):
                cell.width = Cm(width)
    if font_pt:
        for row in table.rows:
            for cell in row.cells:
                for p in cell.paragraphs:
                    for run in p.runs:
                        run.font.size = Pt(font_pt)
    return table


def build_report(a) -> bytes:
    """Analysis 객체 하나를 받아 완성된 .docx 바이트를 돌려준다."""
    snap, val = a.snap, a.valuation
    usd = snap.currency == "USD"
    doc = _new_document()

    # ── 표지 ──────────────────────────────────────────────────────────
    doc.add_heading(f"{snap.name} 분석 리포트", level=0)
    doc.add_paragraph(f"{a.ref.code} · {a.ref.market} · CANSLIM + 밸류에이션")

    latest_actual = a.quarterly.actual_periods()
    bits = [f"가격 기준일 {snap.price_date_label or '—'}"]
    if latest_actual:
        bits.append(f"재무 {latest_actual[-1].label} 분기까지 확정")
    if snap.consensus_date:
        bits.append(f"컨센서스 {snap.consensus_date}")
    bits.append(f"리포트 생성 {dt.date.today().isoformat()}")
    doc.add_paragraph(" · ".join(bits))

    # ── 현재 시세 ─────────────────────────────────────────────────────
    doc.add_heading("현재 시세", level=1)
    change_txt = ""
    if snap.change is not None and snap.change_pct is not None:
        change_txt = (f" (전일 대비 {snap.change:+,.2f}달러, {snap.change_pct:+.2f}%)" if usd
                      else f" (전일 대비 {snap.change:+,.0f}원, {snap.change_pct:+.2f}%)")
    upside = (f" (상승여력 {snap.upside_pct:+.1f}%)" if snap.upside_pct is not None else "")
    ratio_52w = (f"{snap.price / snap.high_52w:.0%}"
                 if snap.price and snap.high_52w else "—")
    _add_table(doc, ["항목", "값"], [
        ["현재가", (snap.money(snap.price) if snap.price else "—") + change_txt],
        ["시가총액", snap.money_big(snap.market_cap) if snap.market_cap else "—"],
        ["목표주가 평균", (snap.money(snap.target_price) if snap.target_price else "—") + upside],
        ["투자의견", f"{snap.recomm_mean:.2f} / 5 (5에 가까울수록 매수 우세)"
         if snap.recomm_mean else "—"],
        ["52주 최고 / 최저", f"{snap.money(snap.high_52w)} / {snap.money(snap.low_52w)}"
         if snap.high_52w and snap.low_52w else "—"],
        ["52주 최고 대비", ratio_52w],
    ])

    # ── CANSLIM ──────────────────────────────────────────────────────
    doc.add_heading("CANSLIM 판정", level=1)
    doc.add_paragraph(
        f"{a.canslim.summary} ({a.canslim.tally}) — 7개 항목을 모두 합격해야 충족입니다. "
        "판단불가는 자료가 없어 못 본 것이라 불합격과 구별하지만 충족으로 치지 않습니다."
    )
    _add_table(
        doc,
        ["항목", "기준", "실제값", "판정", "세부 조건 · 근거"],
        [[f"{i.letter} {i.name}", i.criterion, i.actual, i.verdict.value, i.detail]
         for i in a.canslim.items],
        widths_cm=[2.0, 3.2, 2.5, 1.9, 6.4],   # A4 본문 폭 ≈ 16cm — 근거 칸을 가장 넓게
        font_pt=9,
    )

    # ── 밸류에이션 ────────────────────────────────────────────────────
    doc.add_heading("밸류에이션", level=1)
    if usd:
        eps_unit, eps_digits = "$", 2
        rev_unit, rev_digits, rev_scale = "억$", 0, 1e8
    else:
        eps_unit, eps_digits = "원", 0
        rev_unit, rev_digits, rev_scale = "조원", 1, 1e12

    def metric_cells(attr: str, unit: str, digits: int = 2, scale: float = 1.0) -> list[str]:
        cells = []
        for c in val.columns:
            m = getattr(c, attr)
            cells.append("—" if not m.is_ok else f"{m.value / scale:,.{digits}f}{unit}")
        return cells

    headers = ["지표"] + [f"{c.label} ({_SOURCE_MARK.get(c.source, c.source.value)})"
                          for c in val.columns]
    _add_table(doc, headers, [
        ["PER"] + metric_cells("per", "배"),
        ["PSR"] + metric_cells("psr", "배"),
        ["PEG"] + metric_cells("peg", ""),
        ["ROE"] + metric_cells("roe", "%"),
        ["EPS (12개월)"] + metric_cells("eps_ttm", eps_unit, eps_digits),
        ["매출 (12개월)"] + metric_cells("revenue_ttm", rev_unit, rev_digits, rev_scale),
        ["산출 근거"] + [c.note for c in val.columns],
    ])

    g = val.growth
    notes = doc.add_paragraph()
    notes.add_run(
        f"교차검증 — {val.per_cross_check}\n"
        f"PEG에 쓴 성장률 — 현재 열은 연간 EPS {g.annual_cagr_years}년 CAGR "
        f"{g.annual_cagr.text('%')}, 예상 열은 연간 컨센서스 성장률 {g.forward_annual.text('%')}.\n"
        f"최근 분기 EPS — 전년 동기 대비 {g.quarter_yoy.text('%')}"
    ).font.size = Pt(9)

    # ── 분기 실적 ─────────────────────────────────────────────────────
    doc.add_heading("분기 실적", level=1)
    rev_q_unit, rev_q_digits, rev_q_scale = (("억$", 1, 1e8) if usd else ("억원", 0, 1.0))

    def fmt(value: float | None, unit: str, digits: int, scale: float = 1.0) -> str:
        return "—" if value is None else f"{value / scale:,.{digits}f}{unit}"

    q_rows = []
    for p in a.quarterly.periods:
        eps, rev = a.quarterly.value("EPS", p.key), a.quarterly.value("매출액", p.key)
        if eps is None and rev is None:
            continue
        source = Source.CONSENSUS if p.is_consensus else Source.ACTUAL
        q_rows.append([p.label, fmt(eps, eps_unit, eps_digits),
                       fmt(rev, rev_q_unit, rev_q_digits, rev_q_scale), _SOURCE_MARK[source]])
    if val.derived:
        d = val.derived
        q_rows.append([f"{d.key[:4]}.{d.key[4:]}",
                       fmt(d.values.get("EPS"), eps_unit, eps_digits),
                       fmt(d.values.get("매출액"), rev_q_unit, rev_q_digits, rev_q_scale),
                       f"{_SOURCE_MARK[Source.DERIVED]} ({d.method})"])
    _add_table(doc, ["분기", "EPS", "매출액", "구분"], q_rows)

    # ── 주요 제품·서비스 매출 구성 (한국 종목만 — 출처가 자료를 줄 때) ──
    segs = getattr(a, "segments", None)
    if segs is not None:
        doc.add_heading("주요 제품·서비스 매출 구성", level=1)

        annual_actual = a.annual.actual_periods()
        rev_won = None
        if annual_actual:
            rev_value = a.annual.value("매출액", annual_actual[-1].key)
            if rev_value is not None:
                rev_won = rev_value * a.annual.money_unit

        seg_rows = []
        for rank, s in enumerate(segs.items, start=1):
            est = segments_mod.amount_text(rev_won * s.share_pct / 100 if rev_won else None)
            name = f"{s.name} ★" if rank == 1 else s.name
            seg_rows.append([str(rank), name, f"{s.share_pct:,.1f}%", est, s.description or "—"])
        _add_table(doc, ["순위", "제품·서비스", "매출 비중", "추정 매출액", "설명"], seg_rows,
                   widths_cm=[1.2, 3.4, 2.0, 2.7, 6.7], font_pt=9)

        period = f" (기준: {segs.period_label})" if segs.period_label else ""
        rev_base = (f"최근 확정 연간 매출 {segments_mod.amount_text(rev_won)}"
                    f"({annual_actual[-1].label})에 비중을 곱한 추정치" if rev_won
                    else "연간 매출 자료가 없어 금액은 표시하지 못했습니다")
        note = doc.add_paragraph()
        note.add_run(
            f"출처: 네이버 종목분석의 주요제품 매출구성{period} · ★ 매출 비중 1위. "
            "회사가 제품을 부문으로 묶어 공시하면 부문 이름으로 보이며, 설명은 네이버 기업개요 "
            f"문장에서 자동으로 뽑은 것이라 없을 수 있습니다. 추정 매출액은 {rev_base}이고, "
            "내부거래 조정 때문에 '기타'가 음수이거나 비중 합계가 100%와 다를 수 있습니다. "
            "제품별 이익률과 출시일은 회사가 공개하지 않아 제공하지 못합니다."
        ).font.size = Pt(9)

    # ── 한계와 면책 ───────────────────────────────────────────────────
    doc.add_heading("이 분석의 한계", level=1)
    limits = [
        "오닐 원본 RS Rating(1~99점)이 아니라 시장 지수 대비 +20%p 이상 초과수익과 종목 추세로 L을 판정합니다.",
        "N(New)의 재료는 뉴스 제목을 키워드로 자동 분류한 것이라 사람의 판단을 대신할 수 없습니다.",
        "S는 유통주식수(float)를 반영하지 못해 상승일/하락일 거래량 비율과 최근 거래량 증가로 대체했습니다.",
        "M의 분산일은 지수 거래량으로 셉니다. 지수 거래량이 없으면 판단불가입니다.",
    ]
    if usd:
        limits += [
            "I는 기관 보유 비중의 현재 값만 있어 '증가 추세'는 판정할 수 없습니다 (판단불가).",
            "야후 파이낸스 비공식 라이브러리(yfinance)에 의존해, 형식이 바뀌면 값이 달라질 수 있습니다.",
        ]
    else:
        limits += [
            "I는 기관 보유 비중 대신 외국인 소진율 추세와 네이버가 주는 최근 며칠의 기관 순매수로 판정합니다.",
            "Q+2는 연간 컨센서스에서 역산한 추정치라 신뢰도가 한 단계 낮습니다.",
            "네이버 비공식 API에 의존해, 형식이 바뀌면 값이 달라질 수 있습니다.",
        ]
    if getattr(a, "eps_history_note", ""):
        limits.append(a.eps_history_note + ".")
    for line in limits:
        doc.add_paragraph(line, style="List Bullet")

    disclaimer = doc.add_paragraph()
    run = disclaimer.add_run(
        f"데이터: {snap.source_name} · 이 리포트는 투자 판단을 돕는 참고 자료이며 "
        "매수·매도 신호가 아닙니다. 투자 결정과 그 결과는 전적으로 본인의 책임입니다."
    )
    run.bold = True
    run.font.size = Pt(9)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
