"""한국·미국 주식 CANSLIM + 밸류에이션 분석 — 웹 화면.

실행:  streamlit run app.py   (또는 run.bat 더블클릭)
"""

from __future__ import annotations

import streamlit as st

from src import analyze, charts, tickers
from src.charts import C
from src.models import Source, Verdict

st.set_page_config(page_title="종목 분석 · CANSLIM + 밸류에이션",
                   page_icon="📈", layout="wide")

st.markdown(
    f"""
    <style>
      .stApp {{ background: #f9f9f7; }}
      html, body, [class*="css"] {{
        font-family: system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif;
      }}
      .panel {{ background:{C['surface']}; border:1px solid rgba(11,11,11,0.10);
               border-radius:10px; padding:14px 16px; margin-bottom:14px; }}
      table.grid {{ border-collapse:collapse; width:100%; font-size:13.5px; }}
      table.grid th {{ text-align:left; color:{C['muted']}; font-weight:600;
                       border-bottom:1px solid {C['axis']}; padding:7px 10px; white-space:nowrap; }}
      table.grid td {{ border-bottom:1px solid {C['grid']}; padding:7px 10px;
                       color:{C['ink']}; vertical-align:top; }}
      table.grid td.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
      table.grid td.dim {{ color:{C['ink2']}; font-size:12.5px; }}
      .tag {{ display:inline-block; font-size:11px; padding:1px 7px; border-radius:9px;
              border:1px solid; white-space:nowrap; }}
      .cans {{ background:{C['surface']}; border:1px solid rgba(11,11,11,0.10);
               border-radius:10px; padding:10px 8px; text-align:center; }}
      .cans .l {{ font-size:22px; font-weight:700; color:{C['ink']}; line-height:1.1; }}
      .cans .n {{ font-size:11px; color:{C['muted']}; margin-bottom:2px; }}
      .cans .v {{ font-size:12px; font-weight:600; margin-top:3px; }}
      .note {{ color:{C['muted']}; font-size:12px; line-height:1.7; }}
    </style>
    """,
    unsafe_allow_html=True,
)

SOURCE_STYLE = {
    Source.ACTUAL: (C["s1"], "🟢"),
    Source.CONSENSUS: (C["s2"], "🟡"),
    Source.DERIVED: (C["s3"], "🟠"),
}
VERDICT_COLOR = {
    Verdict.PASS: C["good"], Verdict.FAIL: C["critical"], Verdict.UNKNOWN: C["muted"],
}


def tag(text: str, color: str) -> str:
    return f'<span class="tag" style="color:{color};border-color:{color}">{text}</span>'


@st.cache_data(ttl=600, show_spinner=False)
def load(code: str, name: str, market: str, region: str):
    return analyze.run_for(tickers.StockRef(code=code, name=name, market=market, region=region))


@st.cache_data(ttl=86400, show_spinner=False)
def find(query: str):
    return tickers.search(query)


# ─────────────────────────────────────────────────────────── 검색

st.title("📈 종목 분석")
st.caption("CANSLIM 7개 조건 판정 + 현재/예상 밸류에이션 · 데이터: 네이버 금융(한국) · 야후 파이낸스(미국)")

query = st.text_input("종목명, 6자리 종목코드, 또는 미국 티커",
                      placeholder="예) 삼성전자 · 005930 · AAPL · 엔비디아",
                      label_visibility="collapsed")

if not query.strip():
    st.info("위 칸에 종목명(한국) 또는 티커(미국)를 입력하면 분석이 시작됩니다.")
    st.stop()

with st.spinner("종목을 찾는 중…"):
    candidates = find(query.strip())

if not candidates:
    st.error(f"'{query}' 에 해당하는 종목을 찾지 못했습니다. "
             "한국은 이름 일부나 6자리 코드, 미국은 티커(예: AAPL)나 영문 회사명을 입력해 보세요.")
    st.stop()

ref = candidates[0]
if len(candidates) > 1:
    picked = st.selectbox("종목 선택", candidates, format_func=lambda r: r.label)
    ref = picked

try:
    with st.spinner(f"{ref.name} 분석 중…"):
        a = load(ref.code, ref.name, ref.market, ref.region)
except Exception as exc:  # 비공식 API라 언제든 바뀔 수 있다
    st.error(f"분석에 실패했습니다: {exc}")
    st.caption("데이터 출처가 형식을 바꿨거나 일시적인 네트워크 오류일 수 있습니다. "
               "잠시 후 다시 시도해 보세요.")
    st.stop()

snap, val = a.snap, a.valuation

# ─────────────────────────────────────────────────────────── 현재 시세

st.subheader(f"{snap.name} · {a.ref.code} · {a.ref.market}")

usd = snap.currency == "USD"
change_txt = None
if snap.change is not None and snap.change_pct is not None:
    change_txt = (f"{snap.change:+,.2f}달러 ({snap.change_pct:+.2f}%)" if usd
                  else f"{snap.change:+,.0f}원 ({snap.change_pct:+.2f}%)")

cols = st.columns(5)
cols[0].metric("현재가", snap.money(snap.price) if snap.price else "—", change_txt)
cols[1].metric("시가총액", snap.money_big(snap.market_cap) if snap.market_cap else "—")
cols[2].metric("목표주가 평균", snap.money(snap.target_price) if snap.target_price else "—",
               f"상승여력 {snap.upside_pct:+.1f}%" if snap.upside_pct is not None else None)
cols[3].metric("투자의견", f"{snap.recomm_mean:.2f} / 5" if snap.recomm_mean else "—",
               help="5에 가까울수록 매수 의견이 강합니다."
               + (" 야후 원값(1=강력매수)을 같은 방향이 되도록 뒤집은 값입니다." if usd else " (네이버 기준)"))
cols[4].metric("52주 최고 대비",
               f"{snap.price/snap.high_52w:.0%}" if snap.price and snap.high_52w else "—",
               help=f"52주 최고 {snap.money(snap.high_52w)} / 최저 {snap.money(snap.low_52w)}"
               if snap.high_52w and snap.low_52w else None)

# 무엇이 언제 기준인지 명시한다 — "가격이 틀렸다"는 오해의 대부분은 기준일 미표시에서 온다
latest_actual = a.quarterly.actual_periods()
_fresh_bits = [f"가격: {snap.price_date_label or '—'} 종가"]
if latest_actual:
    _fresh_bits.append(f"재무: {latest_actual[-1].label} 분기까지 확정")
if snap.consensus_date:
    _fresh_bits.append(f"컨센서스: {snap.consensus_date}")
st.caption("🗓 기준일 — " + " · ".join(_fresh_bits))

if snap.upside_pct is not None and abs(snap.upside_pct) > 50:
    st.caption(f"⚠ 목표주가와 현재가의 괴리가 {snap.upside_pct:+.1f}%로 큽니다. "
               "컨센서스가 급변하는 구간이거나 애널리스트 수가 적을 수 있으니 원문 리포트를 확인하세요.")

if snap.summary:
    st.caption(snap.summary)

# ─────────────────────────────────────────────────────────── CANSLIM

st.markdown("### CANSLIM 판정")
st.markdown(f"**{a.canslim.summary}** · 판단이 불가능한 항목은 분모에서 제외했습니다 "
            f"(모르는 것을 틀렸다고 보지 않습니다).")

badges = st.columns(7)
for col, itm in zip(badges, a.canslim.items):
    color = VERDICT_COLOR[itm.verdict]
    col.markdown(
        f'<div class="cans"><div class="l">{itm.letter}</div>'
        f'<div class="n">{itm.name}</div>'
        f'<div class="v" style="color:{color}">{itm.verdict.badge} {itm.verdict.value}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

rows = "".join(
    f"<tr><td><b>{i.letter}</b> {i.name}</td>"
    f"<td class='dim'>{i.criterion}</td>"
    f"<td class='num'>{i.actual}</td>"
    f"<td style='color:{VERDICT_COLOR[i.verdict]};white-space:nowrap'>{i.verdict.badge} {i.verdict.value}</td>"
    f"<td class='dim'>{i.evidence}</td></tr>"
    for i in a.canslim.items
)
st.markdown(
    f'<div class="panel"><table class="grid">'
    f'<tr><th>항목</th><th>기준</th><th>실제값</th><th>판정</th><th>근거</th></tr>'
    f'{rows}</table></div>',
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────── 밸류에이션

st.markdown("### 밸류에이션")

header = "".join(
    f"<th style='text-align:right'>{c.label}<br>"
    f"{tag(SOURCE_STYLE[c.source][1] + ' ' + c.source.value, SOURCE_STYLE[c.source][0])}</th>"
    for c in val.columns
)


def metric_row(title: str, attr: str, unit: str, digits: int = 2, scale: float = 1.0) -> str:
    cells = ""
    for c in val.columns:
        m = getattr(c, attr)
        text = "—" if not m.is_ok else f"{m.value / scale:,.{digits}f}{unit}"
        cells += f"<td class='num'>{text}</td>"
    return f"<tr><td><b>{title}</b></td>{cells}</tr>"


if usd:
    eps_unit, eps_digits = "$", 2
    rev_unit, rev_digits, rev_scale = "억$", 0, 1e8
else:
    eps_unit, eps_digits = "원", 0
    rev_unit, rev_digits, rev_scale = "조원", 1, 1e12

body = (
    metric_row("PER", "per", "배")
    + metric_row("PSR", "psr", "배")
    + metric_row("PEG", "peg", "")
    + metric_row("ROE", "roe", "%")
    + metric_row(f"EPS (12개월)", "eps_ttm", eps_unit, eps_digits)
    + metric_row(f"매출 (12개월)", "revenue_ttm", rev_unit, rev_digits, rev_scale)
    + "<tr><td class='dim'>산출 근거</td>"
    + "".join(f"<td class='dim'>{c.note}</td>" for c in val.columns)
    + "</tr>"
)
st.markdown(
    f'<div class="panel"><table class="grid">'
    f'<tr><th>지표</th>{header}</tr>{body}</table></div>',
    unsafe_allow_html=True,
)

g = val.growth
peg_capped = any(
    (not c.peg.is_ok) and "극단" in (c.peg.note or "") for c in val.columns
)
extra_lines = ""
if peg_capped:
    extra_lines += (
        '· <b>PEG를 표시하지 않은 칸</b> — 성장률이 100%를 넘는 구간에서는 PEG가 0에 붙어 '
        '아무 정보도 주지 못합니다 (PEG는 성장률 20~50% 수준을 염두에 둔 지표입니다).<br>'
    )
if usd:
    tail = "야후는 Q+1·Q+2 분기 컨센서스를 원본으로 제공해 역산이 필요 없습니다."
else:
    tail = "네이버는 미래 분기 컨센서스를 하나만 제공합니다."
st.markdown(
    f'<div class="note">'
    f'· <b>교차검증</b> — {val.per_cross_check}<br>'
    f'· <b>PEG에 쓴 성장률</b> — 현재 열은 연간 EPS {g.annual_cagr_years}년 CAGR '
    f'<b>{g.annual_cagr.text("%")}</b>, 예상 열은 연간 컨센서스 성장률 '
    f'<b>{g.forward_annual.text("%")}</b> 기준입니다.<br>'
    f'· <b>최근 분기 EPS</b> — 전년 동기 대비 <b>{g.quarter_yoy.text("%")}</b><br>'
    f'{extra_lines}'
    f'· 🟡 컨센서스는 애널리스트 추정치이고, 🟠 역산추정은 <b>연간 컨센서스에서 계산해 뽑아낸 값</b>이라 '
    f'신뢰도가 한 단계 낮습니다. {tail}'
    f'</div>',
    unsafe_allow_html=True,
)

# ─────────────────────────────────────────────────────────── 차트

st.markdown("### 차트")
left, right = st.columns(2)

with left:
    st.markdown("**주가 흐름 (최근 1년 반)**")
    st.plotly_chart(charts.price_chart(a.stock_df, snap.high_52w, snap.low_52w,
                                       currency=snap.currency),
                    config={"displayModeBar": False})

with right:
    st.markdown(f"**{snap.name} vs {a.index_name}** — 1년 전을 100으로 맞춘 비교")
    st.plotly_chart(
        charts.relative_chart(a.stock_df, a.index_df, a.index_name, snap.name),
        config={"displayModeBar": False},
    )

metric_name = st.radio("분기 실적 지표", ["EPS", "매출액"], horizontal=True,
                       label_visibility="collapsed")
st.markdown(f"**분기 {metric_name} 추이** — 확정 실적과 추정치를 색으로 구분했습니다")
derived = val.derived
st.plotly_chart(
    charts.earnings_chart(
        a.quarterly,
        derived.key if derived else None,
        derived.values.get(metric_name) if derived else None,
        metric_name,
        currency=snap.currency,
    ),
    config={"displayModeBar": False},
)

# ─────────────────────────────────────────────────────────── 각주

with st.expander("이 분석의 한계 — 반드시 읽어 주세요"):
    if usd:
        market_specific = f"""
- **`I`는 '추세'를 판정할 수 없습니다.** 야후는 기관 보유 비중의 현재 시점 값만 주기 때문에
  오닐이 요구하는 '기관 보유 증가 중'인지는 알 수 없어 판단불가 + 수치 표기로 둡니다.
- **`N`의 재료는 야후 영문 뉴스 제목을 키워드로 자동 분류**한 것입니다. 공시(8-K 등)는 보지 않습니다.
- **Q+1·Q+2는 야후 애널리스트 컨센서스 원본**입니다 (한국과 달리 역산이 필요 없습니다).
- **회사 개요는 야후가 주는 영문 원문**을 그대로 표시합니다.
- **연간 성장률은 {g.annual_cagr_years}년 기준입니다.** 야후가 연간 확정 데이터를 4개년 안팎만 제공합니다.
- **야후 파이낸스 비공식 라이브러리(yfinance)에 의존합니다.** 야후가 형식을 바꾸면 동작하지 않을 수 있습니다.
"""
    else:
        market_specific = f"""
- **`I`는 기관 보유 '비중'이 아니라 외국인 소진율 추세입니다.**
- **Q+2는 역산 추정치입니다.** 네이버가 미래 분기 컨센서스를 하나만 주기 때문에,
  연간 컨센서스에서 이미 알려진 분기를 빼고 전년도 계절성 비중으로 나눠 뽑았습니다.
- **최신 확정 분기가 한 분기 늦을 수 있습니다.** 잠정실적 발표 후에도 네이버 확정 재무 반영까지는
  시차가 있습니다 (그 사이 해당 분기는 '컨센서스'로 표시됩니다).
- **연간 성장률은 {g.annual_cagr_years}년 기준입니다.** 네이버가 연간 데이터를 3개년만 제공합니다.
- **비공식 API에 의존합니다.** 네이버가 예고 없이 형식을 바꾸면 동작하지 않을 수 있습니다.
"""
    st.markdown(
        f"""
- **오닐 원본 RS Rating(1~99점)이 아닙니다.** `L` 항목은 전 종목 백분위 순위가 아니라
  **{a.index_name} 대비 초과수익 여부**입니다. 원본 등급은 IBD 유료 서비스라 가져올 수 없습니다.
- **`N`(New)은 신고가 하나가 아닙니다.** 오닐의 N은 신제품·신규 서비스·새 경영진·새로운 산업
  환경, 그리고 그 결과인 신고가를 모두 뜻합니다. 이 도구는 **① 신고가 근접**과
  **② 새로운 재료**를 함께 보고, 둘 다 충족해야 합격으로 봅니다.
  재료는 최근 {a.newness.window_days}일 치 제목을 키워드로 자동 분류한 것입니다.
  기계적 분류라 사람의 판단을 대신할 수 없으니, 표의 근거란에 뜬 제목을 직접 읽어 보세요.
  (같은 사건을 여러 매체가 쓴 기사는 하나로 합칩니다.)
- **`S`는 유통주식수(float)를 반영하지 못합니다.** 무료로 안정적으로 구할 수 없어 거래량 급증으로
  대체했고, 장중에는 부분 거래량 왜곡을 피하려고 **직전 완결 거래일**의 거래량을 씁니다.
{market_specific}
- 애널리스트 커버리지가 없는 소형주는 컨센서스가 아예 없는 것이 정상입니다.
"""
    )

source_note = "야후 파이낸스" if usd else "네이버 금융"
st.markdown(
    f'<div class="note">데이터: {source_note} · '
    f'시세 기준일 {snap.price_date_label or "—"} · 컨센서스 기준일 {snap.consensus_date or "—"}<br>'
    f'<b>이 도구는 투자 판단을 돕는 참고 자료이며 매수·매도 신호가 아닙니다. '
    f'투자 결정과 그 결과는 전적으로 본인의 책임입니다.</b> 개인 리서치 용도로만 사용하세요.'
    f'</div>',
    unsafe_allow_html=True,
)
