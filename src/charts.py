"""차트. 색은 데이터의 역할에 따라 배정한다.

카테고리 색은 '출처'라는 정체성에 붙는다 — 파랑=실적확정, 주황=컨센서스, 청록=역산추정.
순위나 크기에 따라 색을 바꾸지 않는다. 두 개의 세로축(이중축)은 쓰지 않는다.
"""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import indicators
from .models import Source

# 검증된 레퍼런스 팔레트 (라이트 모드) — 슬롯 순서가 CVD 안전장치이므로 바꾸지 않는다
C = {
    "surface": "#fcfcfb",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "s1": "#2a78d6",   # 파랑 — 실적확정 / 이 종목 / 각 패널의 주 계열
    "s2": "#eb6834",   # 주황 — 컨센서스 / 비교 지수 / 각 패널의 보조 계열
    "s3": "#1baf7a",   # 청록 — 역산추정
    "s4": "#eda100",   # 노랑 — 네 번째 슬롯 (세 번째 이동평균선)
    "good": "#0ca30c",
    "critical": "#d03b3b",
}

SOURCE_COLOR = {
    Source.ACTUAL: C["s1"],
    Source.CONSENSUS: C["s2"],
    Source.DERIVED: C["s3"],
}

FONT = 'system-ui, -apple-system, "Segoe UI", "Malgun Gothic", sans-serif'


def _base(fig: go.Figure, height: int = 320, legend: bool = False) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=28, b=8),
        paper_bgcolor=C["surface"],
        plot_bgcolor=C["surface"],
        font=dict(family=FONT, size=12, color=C["ink2"]),
        hovermode="x unified",
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                    bgcolor="rgba(0,0,0,0)", font=dict(color=C["ink2"])),
        dragmode=False,
    )
    fig.update_xaxes(showgrid=False, linecolor=C["axis"], ticks="outside",
                     tickcolor=C["axis"], tickfont=dict(color=C["muted"]))
    fig.update_yaxes(gridcolor=C["grid"], zeroline=False, linecolor="rgba(0,0,0,0)",
                     tickfont=dict(color=C["muted"]))
    return fig


def price_chart(df: pd.DataFrame, high_52w: float | None, low_52w: float | None,
                currency: str = "KRW") -> go.Figure:
    """주가 흐름. 단일 계열이므로 범례 없이 제목이 계열을 설명한다."""
    usd = currency == "USD"
    unit, digits = ("$", 2) if usd else ("원", 0)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["close"], mode="lines", name="종가",
        line=dict(color=C["s1"], width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>종가 %{y:,." + str(digits) + "f}" + unit + "<extra></extra>",
    ))

    # 라벨은 선 위쪽·그림 안쪽에 붙인다.
    # 바깥(right)에 두면 오른쪽 여백에서 잘리고, 아래(bottom)에 두면 x축과 겹친다.
    for value, label, dash in ((high_52w, "52주 최고", "dash"), (low_52w, "52주 최저", "dot")):
        if value:
            fig.add_hline(
                y=value, line=dict(color=C["muted"], width=1, dash=dash),
                annotation_text=f"{label} {value:,.{digits}f}{unit}",
                annotation_position="top left",
                annotation_font=dict(color=C["muted"], size=11),
                annotation_bgcolor=C["surface"], annotation_borderpad=2,
            )
    fig.update_yaxes(tickformat=f",.{digits}f", ticksuffix=unit)
    return _base(fig, height=300)


# 이동평균선 색 — 기간 오름차순으로 주황 / 진초록 / 보라.
# 종가가 파랑이므로 이동평균선에는 파랑·검정 계열을 쓰지 않는다 (겹치면 구별 불가).
# 세 색은 색상과 밝기가 모두 벌어져 겹치는 구간에서도 갈라져 보인다.
MA_COLORS = (C["s2"], "#008300", "#4a3aa7")


def technical_chart(
    df: pd.DataFrame,
    high_52w: float | None,
    low_52w: float | None,
    currency: str = "KRW",
    ma_windows: tuple[int, ...] = (20, 50, 200),
) -> go.Figure:
    """주가 + 이동평균 + 볼린저밴드 / RSI / %B 를 x축을 공유하는 3단으로 그린다.

    RSI(0~100)와 %B(0~1)는 주가와 축 단위가 달라 한 그림에 겹칠 수 없다
    (이중축 금지). 각 패널의 주 계열은 파랑, 보조 계열은 주황 — 패널이
    분리된 좌표계이므로 패널 안에서 팔레트 슬롯 순서를 다시 시작한다.
    """
    usd = currency == "USD"
    unit, digits = ("$", 2) if usd else ("원", 0)
    close = df["close"] if "close" in df.columns else pd.Series(dtype=float)

    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.055,
        row_heights=[0.56, 0.22, 0.22],
        subplot_titles=("", "RSI(14)", f"볼린저 %B ({indicators.BB_WINDOW}일 · {indicators.BB_STD:.0f}σ)"),
    )

    # ── 1단: 볼린저밴드(배경 띠) → 종가 → 이동평균 ─────────────────────
    _, bb_upper, bb_lower, pct_b = indicators.bollinger(close)
    fig.add_trace(go.Scatter(
        x=df["date"], y=bb_upper, mode="lines", name="볼린저밴드",
        line=dict(color=C["axis"], width=0.8), showlegend=False, hoverinfo="skip",
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df["date"], y=bb_lower, mode="lines", name="볼린저밴드",
        line=dict(color=C["axis"], width=0.8),
        fill="tonexty", fillcolor="rgba(137,135,129,0.10)", hoverinfo="skip",
    ), row=1, col=1)

    fig.add_trace(go.Scatter(
        x=df["date"], y=close, mode="lines", name="종가",
        line=dict(color=C["s1"], width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>종가 %{y:,." + str(digits) + "f}" + unit + "<extra></extra>",
    ), row=1, col=1)

    for window, color in zip(ma_windows, MA_COLORS):
        fig.add_trace(go.Scatter(
            x=df["date"], y=indicators.sma(close, window), mode="lines", name=f"MA {window}",
            line=dict(color=color, width=1.4),
            hovertemplate="%{x|%Y-%m-%d}<br>MA " + str(window)
                          + " %{y:,." + str(digits) + "f}" + unit + "<extra></extra>",
        ), row=1, col=1)

    for value, label, dash in ((high_52w, "52주 최고", "dash"), (low_52w, "52주 최저", "dot")):
        if value and value > 0:
            fig.add_hline(y=value, row=1, col=1,
                          line=dict(color=C["muted"], width=1, dash=dash))
            # 주가 축이 log 라서 주석 y 는 log10 좌표로 줘야 한다
            # (add_hline 의 annotation 은 log 변환을 하지 않아 화면 밖으로 사라진다)
            fig.add_annotation(
                row=1, col=1, xref="x domain", x=0.0, xanchor="left",
                y=math.log10(value), yanchor="bottom", showarrow=False,
                text=f"{label} {value:,.{digits}f}{unit}",
                font=dict(color=C["muted"], size=11),
                bgcolor=C["surface"], borderpad=2,
            )

    # ── 2단: RSI + RSI 기반 이동평균 ──────────────────────────────────
    rsi = indicators.rsi(close)
    fig.add_trace(go.Scatter(
        x=df["date"], y=rsi, mode="lines", name="RSI(14)",
        line=dict(color=C["s1"], width=1.8),
        hovertemplate="%{x|%Y-%m-%d}<br>RSI %{y:,.1f}<extra></extra>",
    ), row=2, col=1)
    fig.add_trace(go.Scatter(
        x=df["date"], y=indicators.sma(rsi, indicators.RSI_PERIOD), mode="lines",
        name="RSI MA(14)", line=dict(color=C["s2"], width=1.4),
        hovertemplate="%{x|%Y-%m-%d}<br>RSI MA %{y:,.1f}<extra></extra>",
    ), row=2, col=1)
    for level in (70, 30):
        fig.add_hline(y=level, row=2, col=1,
                      line=dict(color=C["muted"], width=1, dash="dot"))
    fig.update_yaxes(range=[0, 100], tickvals=[30, 50, 70], row=2, col=1)

    # ── 3단: 볼린저 %B ────────────────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=df["date"], y=pct_b, mode="lines", name="%B",
        line=dict(color=C["s1"], width=1.8), showlegend=False,
        hovertemplate="%{x|%Y-%m-%d}<br>%B %{y:,.2f}<extra></extra>",
    ), row=3, col=1)
    for level in (1.0, 0.0):
        fig.add_hline(y=level, row=3, col=1,
                      line=dict(color=C["muted"], width=1, dash="dot"))
    fig.update_yaxes(tickvals=[0, 0.5, 1], row=3, col=1)

    # 주가 축은 log — 몇 배씩 오르는 종목도 '같은 비율 = 같은 기울기'로 읽힌다.
    # RSI(0~100)·%B 패널은 값 범위가 좁고 0을 포함할 수 있어 선형 유지.
    fig.update_yaxes(type="log", tickformat=f",.{digits}f", ticksuffix=unit, row=1, col=1)
    fig = _base(fig, height=640, legend=True)
    fig.update_layout(legend_traceorder="normal")  # 종가·MA 가 앞, RSI 가 뒤에 오도록
    for note in fig.layout.annotations:
        if note.text in ("RSI(14)",) or note.text.startswith("볼린저 %B"):
            note.update(font=dict(size=12, color=C["ink2"]), x=0, xanchor="left")
    return fig


def earnings_chart(
    quarterly, derived_key: str | None, derived_value: float | None, label: str,
    currency: str = "KRW",
) -> go.Figure:
    """분기 실적 추이. 출처(확정/컨센서스/역산)를 색으로 구분하고 범례를 단다.

    EPS와 매출액을 한 그림에 겹치지 않는다 — 축이 두 개가 되기 때문이다.
    미국 매출액은 달러 원값이라 '억 달러'로 축소해 그린다.
    """
    usd = currency == "USD"
    scale = 1e8 if (usd and label != "EPS") else 1.0
    if usd:
        unit, digits = ("$", 2) if label == "EPS" else ("억$", 1)
    else:
        unit, digits = ("원", 0) if label == "EPS" else ("억원", 0)

    # 전체 기간을 순서대로 모아 인접 분기끼리 QoQ 증가율을 계산한다.
    # 역산(derived) 분기도 포함 — Q+2의 QoQ는 Q+1 컨센서스 대비다.
    ordered: list[tuple[str, float, Source]] = []
    for period in quarterly.periods:
        value = quarterly.value(label, period.key)
        if value is None:
            continue
        source = Source.CONSENSUS if period.is_consensus else Source.ACTUAL
        ordered.append((period.label, value, source))
    if derived_key and derived_value is not None:
        ordered.append((f"{derived_key[:4]}.{derived_key[4:]}", derived_value, Source.DERIVED))

    qoq: dict[str, str] = {}
    for (_, prev_value, _), (this_label, this_value, _) in zip(ordered, ordered[1:]):
        if prev_value > 0:  # 직전 분기가 적자/0이면 증가율이 성립하지 않는다
            qoq[this_label] = f"{(this_value / prev_value - 1) * 100:+,.1f}%"

    buckets: dict[Source, dict[str, list]] = {
        s: {"x": [], "y": [], "text": [], "qoq": []}
        for s in (Source.ACTUAL, Source.CONSENSUS, Source.DERIVED)
    }
    for period_label, value, source in ordered:
        bucket = buckets[source]
        bucket["x"].append(period_label)
        bucket["y"].append(value / scale)
        value_text = f"{value / scale:,.{digits}f}"
        rate = qoq.get(period_label)
        bucket["text"].append(f"{value_text}<br>{rate}" if rate else value_text)
        bucket["qoq"].append(rate or "—")

    fig = go.Figure()
    for source, data in buckets.items():
        if not data["x"]:
            continue
        fig.add_trace(go.Bar(
            x=data["x"], y=data["y"], name=source.value,
            marker=dict(color=SOURCE_COLOR[source],
                        line=dict(color=C["surface"], width=2)),  # 막대 사이 2px 간격
            offsetgroup="q",
            text=data["text"],
            customdata=data["qoq"],
            textposition="outside",
            cliponaxis=False,  # 두 줄 라벨이 위 여백에서 잘리지 않게
            textfont=dict(color=C["ink2"], size=11),
            hovertemplate="%{x}<br>" + label + " %{y:,." + str(digits) + "f}" + unit
                          + "<br>QoQ %{customdata}<extra>%{data.name}</extra>",
        ))

    fig.update_layout(barmode="group", bargap=0.35)
    fig.update_yaxes(tickformat=f",.{digits}f", ticksuffix=unit)
    fig = _base(fig, height=340, legend=True)  # 두 줄 라벨(값+QoQ) 여유분
    # '2025.03' 을 숫자 2025.03 으로 읽어 막대가 흩어지는 것을 막는다
    fig.update_xaxes(type="category")
    return fig


def relative_chart(stock: pd.DataFrame, index: pd.DataFrame, index_name: str,
                   stock_name: str, days: int = 252) -> go.Figure:
    """종목과 지수를 같은 출발점(100)으로 맞춰 비교한다. 축은 하나다."""
    fig = go.Figure()

    for df, name, color in ((stock, stock_name, C["s1"]), (index, index_name, C["s2"])):
        series = df.dropna(subset=["close"]).tail(days)
        if len(series) < 2 or series["close"].iloc[0] == 0:
            continue
        rebased = series["close"] / series["close"].iloc[0] * 100.0
        fig.add_trace(go.Scatter(
            x=series["date"], y=rebased, mode="lines", name=name,
            line=dict(color=color, width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>" + name + " %{y:,.1f}<extra></extra>",
        ))

    fig.add_hline(y=100, line=dict(color=C["axis"], width=1))
    fig.update_yaxes(ticksuffix="", tickformat=",.0f")
    return _base(fig, height=300, legend=True)
