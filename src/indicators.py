"""기술적 보조지표 — 이동평균 · RSI · 볼린저밴드.

전부 일봉 종가만으로 계산한다 (새 데이터 출처 불필요, 한국·미국 공용).
계산 기간이 차기 전 구간은 NaN 으로 두어 차트에서 자연스럽게 비워진다.
"""

from __future__ import annotations

import pandas as pd

RSI_PERIOD = 14
BB_WINDOW = 20
BB_STD = 2.0


def sma(close: pd.Series, window: int) -> pd.Series:
    """단순 이동평균. 기간이 차기 전에는 NaN."""
    return close.rolling(window, min_periods=window).mean()


def rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """Wilder RSI (0~100). 상승폭·하락폭을 지수 평활(α=1/기간)로 평균한다."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    out = 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
    # 기간 내 하락이 전혀 없으면 분모가 0 — 관례대로 100 (전부 보합이면 판단 불가라 NaN)
    no_loss = avg_loss == 0
    out[no_loss & (avg_gain > 0)] = 100.0
    out[no_loss & (avg_gain == 0)] = float("nan")
    return out


def bollinger(
    close: pd.Series, window: int = BB_WINDOW, num_std: float = BB_STD
) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """볼린저밴드 (중심선, 상단, 하단, %B).

    %B = (종가 − 하단) ÷ (상단 − 하단). 1 초과 = 상단 돌파, 0 미만 = 하단 이탈.
    표준편차는 모집단 기준(ddof=0) — 트레이딩뷰 등 차트 도구의 관례를 따른다.
    """
    mid = close.rolling(window, min_periods=window).mean()
    std = close.rolling(window, min_periods=window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = upper - lower
    pct_b = (close - lower) / width.where(width > 0)  # 폭이 0이면 NaN
    return mid, upper, lower, pct_b
