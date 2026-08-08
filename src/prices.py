"""일봉 시세 파싱.

네이버 fchart 응답은 JSON이 아니라 작은따옴표를 쓰는 자바스크립트 리터럴이다.
    [['날짜', '시가', ...],
    ["20260720", 241000, 257500, 240000, 244000, 26804038, 46.59],
    ...]
json.loads() 는 작은따옴표를 거부하므로 ast.literal_eval() 로 읽는다.
"""

from __future__ import annotations

import ast
import datetime as dt

import pandas as pd

from . import naver

COLUMN_MAP = {
    "날짜": "date",
    "시가": "open",
    "고가": "high",
    "저가": "low",
    "종가": "close",
    "거래량": "volume",
    "외국인소진율": "foreign_rate",
}

INDEX_SYMBOL = {"KOSPI": "KOSPI", "KOSDAQ": "KOSDAQ"}


class PriceParseError(RuntimeError):
    pass


def parse_sise(raw: str) -> pd.DataFrame:
    """fchart 원문 문자열을 DataFrame 으로. 날짜 오름차순, date 는 datetime64."""
    text = raw.strip()
    if not text:
        raise PriceParseError("시세 응답이 비어 있습니다")

    # 자바스크립트 null 은 파이썬 리터럴이 아니므로 None 으로 바꾼다
    text = text.replace("null", "None")

    try:
        rows = ast.literal_eval(text)
    except (ValueError, SyntaxError) as exc:
        raise PriceParseError(f"시세 응답을 해석하지 못했습니다: {exc}") from exc

    if not rows or len(rows) < 2:
        return pd.DataFrame(columns=list(COLUMN_MAP.values()))

    header, *body = rows
    columns = [COLUMN_MAP.get(str(h).strip(), str(h).strip()) for h in header]

    # 열 개수가 헤더와 다른 행은 버린다 (네이버가 열을 늘려도 죽지 않게)
    body = [r for r in body if len(r) == len(columns)]
    if not body:
        return pd.DataFrame(columns=columns)

    df = pd.DataFrame(body, columns=columns)
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])

    for col in ("open", "high", "low", "close", "volume", "foreign_rate"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 지수는 외국인소진율이 0.0 으로 채워져 오므로 의미 없는 값으로 표시
    return df.sort_values("date").reset_index(drop=True)


def load_ohlcv(symbol: str, days: int = 540, today: dt.date | None = None) -> pd.DataFrame:
    """종목코드 또는 'KOSPI'/'KOSDAQ' 의 일봉을 days 일 치 가져온다.

    12개월 상대수익률 계산에 1년치 거래일이 필요하므로 기본 540일(약 1년 반)을 받는다.
    """
    today = today or dt.date.today()
    start = (today - dt.timedelta(days=days)).strftime("%Y%m%d")
    end = today.strftime("%Y%m%d")
    return parse_sise(naver.sise_json(symbol, start, end))


def market_symbol(market_name: str | None) -> str:
    """'코스닥'/'KOSDAQ' 이면 KOSDAQ, 그 외에는 KOSPI 지수를 비교 대상으로."""
    if market_name and ("코스닥" in market_name or "KOSDAQ" in market_name.upper()):
        return "KOSDAQ"
    return "KOSPI"


KST = dt.timezone(dt.timedelta(hours=9))
KR_MARKET_CLOSE = dt.time(15, 30)


def complete_sessions(
    df: pd.DataFrame,
    close_time: dt.time = KR_MARKET_CLOSE,
    tz: dt.tzinfo = KST,
    now: dt.datetime | None = None,
) -> pd.DataFrame:
    """마지막 행이 '아직 끝나지 않은 오늘 장'이면 제외한다.

    장중의 부분 거래량을 50일 평균과 비교하면 거의 항상 '거래량 부족'으로 나온다.
    수급(S) 같은 판정에는 완결된 거래일만 써야 한다.
    """
    if df.empty or "date" not in df:
        return df
    now = now or dt.datetime.now(tz)
    last = df["date"].iloc[-1]
    if last.date() == now.date() and now.time() < close_time:
        return df.iloc[:-1].reset_index(drop=True)
    return df


def pct_return(close: pd.Series, trading_days: int) -> float | None:
    """trading_days 거래일 전 대비 수익률(%). 데이터가 모자라면 None."""
    s = close.dropna()
    if len(s) <= trading_days:
        return None
    past = s.iloc[-(trading_days + 1)]
    now = s.iloc[-1]
    if past is None or past == 0:
        return None
    return (now / past - 1.0) * 100.0


def moving_average(close: pd.Series, window: int) -> float | None:
    s = close.dropna()
    if len(s) < window:
        return None
    return float(s.iloc[-window:].mean())
