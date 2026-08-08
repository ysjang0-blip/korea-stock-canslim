"""차트. 색은 데이터의 역할에 따라 배정한다.

카테고리 색은 '출처'라는 정체성에 붙는다 — 파랑=실적확정, 주황=컨센서스, 청록=역산추정.
순위나 크기에 따라 색을 바꾸지 않는다. 두 개의 세로축(이중축)은 쓰지 않는다.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from .models import Source

# 검증된 레퍼런스 팔레트 (라이트 모드) — 앞 3개 슬롯만 사용한다
C = {
    "surface": "#fcfcfb",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "ink": "#0b0b0b",
    "ink2": "#52514e",
    "muted": "#898781",
    "s1": "#2a78d6",   # 파랑 — 실적확정 / 이 종목
    "s2": "#eb6834",   # 주황 — 컨센서스 / 비교 지수
    "s3": "#1baf7a",   # 청록 — 역산추정
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

    buckets: dict[Source, dict[str, list]] = {
        s: {"x": [], "y": []} for s in (Source.ACTUAL, Source.CONSENSUS, Source.DERIVED)
    }
    for period in quarterly.periods:
        value = quarterly.value(label, period.key)
        if value is None:
            continue
        source = Source.CONSENSUS if period.is_consensus else Source.ACTUAL
        buckets[source]["x"].append(period.label)
        buckets[source]["y"].append(value / scale)

    if derived_key and derived_value is not None:
        buckets[Source.DERIVED]["x"].append(f"{derived_key[:4]}.{derived_key[4:]}")
        buckets[Source.DERIVED]["y"].append(derived_value / scale)

    fig = go.Figure()
    for source, data in buckets.items():
        if not data["x"]:
            continue
        fig.add_trace(go.Bar(
            x=data["x"], y=data["y"], name=source.value,
            marker=dict(color=SOURCE_COLOR[source],
                        line=dict(color=C["surface"], width=2)),  # 막대 사이 2px 간격
            offsetgroup="q",
            text=[f"{v:,.{digits}f}" for v in data["y"]],
            textposition="outside",
            textfont=dict(color=C["ink2"], size=11),
            hovertemplate="%{x}<br>" + label + " %{y:,." + str(digits) + "f}" + unit
                          + "<extra>%{data.name}</extra>",
        ))

    fig.update_layout(barmode="group", bargap=0.35)
    fig.update_yaxes(tickformat=f",.{digits}f", ticksuffix=unit)
    fig = _base(fig, height=320, legend=True)
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
