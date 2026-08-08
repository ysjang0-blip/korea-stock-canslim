"""야후 파이낸스(yfinance) 어댑터 — 미국 종목 전용.

야후 응답을 네이버와 동일한 도메인 모델(Snapshot·FinancialTable)로 정규화한다.
그래서 canslim / valuation / charts 는 시장 구분 없이 하나의 구현으로 돈다.

네이버와 다른 점:
  * 매출액·순이익이 달러 '그대로' 온다 → FinancialTable.money_unit = 1
  * 미래 분기 컨센서스를 두 개(Q+1, Q+2) 원본으로 준다 → 역산이 필요 없다
  * 기관 '보유 비중'을 주지만 시점값이라 증가 추세는 알 수 없다
  * 디스크 캐시 계층이 없다 — 화면의 st.cache_data(10분)가 캐시 역할을 한다
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

from .fundamentals import FinancialTable, Period, Snapshot
from .valuation import next_quarter_key

SP500_SYMBOL = "^GSPC"
SP500_NAME = "S&P500"

# 야후 거래소 코드 → 한국어 표기
EXCHANGE_KO = {
    "NMS": "나스닥", "NGM": "나스닥", "NCM": "나스닥", "NAS": "나스닥",
    "NYQ": "NYSE", "ASE": "AMEX", "PCX": "NYSE Arca", "BTS": "BATS",
}

EPS_ROWS = ("Diluted EPS", "Basic EPS")
REVENUE_ROW = "Total Revenue"
NET_INCOME_ROW = "Net Income"
EQUITY_ROW = "Stockholders Equity"


class YahooFetchError(RuntimeError):
    """야후에서 데이터를 받아오지 못했을 때."""


def _num(value) -> float | None:
    """NaN·None 을 걸러낸 float."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def _quarter_key(ts: pd.Timestamp) -> str:
    return f"{ts.year}{ts.month:02d}"


def _row_series(frame: pd.DataFrame, candidates: tuple[str, ...] | str) -> pd.Series | None:
    """행 이름 후보 중 첫 번째로 존재하는 행을 돌려준다."""
    if isinstance(candidates, str):
        candidates = (candidates,)
    for name in candidates:
        if frame is not None and not frame.empty and name in frame.index:
            return frame.loc[name]
    return None


def _est_value(est: pd.DataFrame | None, period: str, column: str = "avg") -> float | None:
    """earnings_estimate / revenue_estimate 표에서 '0q' 같은 행의 값."""
    if est is None or getattr(est, "empty", True):
        return None
    if period not in est.index or column not in est.columns:
        return None
    return _num(est.loc[period, column])


# ------------------------------------------------------------- 재무 정규화

def normalize_quarterly(
    income: pd.DataFrame,
    balance: pd.DataFrame | None = None,
    earnings_est: pd.DataFrame | None = None,
    revenue_est: pd.DataFrame | None = None,
) -> FinancialTable:
    """분기 손익 + 추정치를 FinancialTable 로.

    야후의 '0q'는 아직 발표되지 않은 현재 분기, '+1q'는 그다음 분기다.
    각각 마지막 확정 분기의 +1, +2 분기 키를 붙인다.
    """
    if income is None or income.empty:
        return FinancialTable(money_unit=1.0)

    cols = sorted(income.columns)  # 야후는 최신부터 주므로 오름차순으로
    periods = [Period(key=_quarter_key(ts), title=f"{ts:%Y.%m.}", is_consensus=False) for ts in cols]

    eps_row = _row_series(income, EPS_ROWS)
    rev_row = _row_series(income, REVENUE_ROW)
    net_row = _row_series(income, NET_INCOME_ROW)

    rows: dict[str, dict[str, float | None]] = {"EPS": {}, "매출액": {}, "당기순이익": {}}
    for ts in cols:
        key = _quarter_key(ts)
        rows["EPS"][key] = _num(eps_row[ts]) if eps_row is not None else None
        rows["매출액"][key] = _num(rev_row[ts]) if rev_row is not None else None
        rows["당기순이익"][key] = _num(net_row[ts]) if net_row is not None else None

    # TTM ROE = 최근 4개 분기 순이익 합 ÷ 평균 자기자본. 최신 확정 분기에 붙인다.
    latest_key = periods[-1].key if periods else None
    if latest_key and net_row is not None:
        net4 = [_num(net_row[ts]) for ts in cols[-4:]]
        equity_row = _row_series(balance, EQUITY_ROW) if balance is not None else None
        if len(net4) == 4 and all(v is not None for v in net4) and equity_row is not None:
            equities = [v for v in (_num(x) for x in equity_row.tolist()[:2]) if v]
            if equities:
                avg_eq = sum(equities) / len(equities)
                if avg_eq > 0:
                    rows["ROE"] = {latest_key: sum(net4) / avg_eq * 100.0}

    # 컨센서스 분기 (Q+1 = '0q', Q+2 = '+1q')
    if latest_key:
        for offset, est_key in ((1, "0q"), (2, "+1q")):
            eps_est = _est_value(earnings_est, est_key)
            rev_est_v = _est_value(revenue_est, est_key)
            if eps_est is None and rev_est_v is None:
                continue
            key = latest_key
            for _ in range(offset):
                key = next_quarter_key(key)
            periods.append(Period(key=key, title=f"{key[:4]}.{key[4:]}.", is_consensus=True))
            rows["EPS"][key] = eps_est
            rows["매출액"][key] = rev_est_v

    periods.sort(key=lambda p: p.key)
    return FinancialTable(periods=periods, rows=rows, money_unit=1.0)


def normalize_annual(
    income: pd.DataFrame,
    earnings_est: pd.DataFrame | None = None,
    revenue_est: pd.DataFrame | None = None,
) -> FinancialTable:
    """연간 손익 + 당해 회계연도 컨센서스('0y')를 FinancialTable 로."""
    if income is None or income.empty:
        return FinancialTable(money_unit=1.0)

    cols = sorted(income.columns)
    periods = [Period(key=_quarter_key(ts), title=f"{ts:%Y.%m.}", is_consensus=False) for ts in cols]

    eps_row = _row_series(income, EPS_ROWS)
    rev_row = _row_series(income, REVENUE_ROW)

    rows: dict[str, dict[str, float | None]] = {"EPS": {}, "매출액": {}}
    for ts in cols:
        key = _quarter_key(ts)
        rows["EPS"][key] = _num(eps_row[ts]) if eps_row is not None else None
        rows["매출액"][key] = _num(rev_row[ts]) if rev_row is not None else None

    # 당해 회계연도 컨센서스: 마지막 확정 연도 + 1년, 같은 결산월
    eps_y = _est_value(earnings_est, "0y")
    rev_y = _est_value(revenue_est, "0y")
    if periods and (eps_y is not None or rev_y is not None):
        last = periods[-1]
        key = f"{last.year + 1}{last.key[4:6]}"
        periods.append(Period(key=key, title=f"{key[:4]}.{key[4:]}.", is_consensus=True))
        rows["EPS"][key] = eps_y
        rows["매출액"][key] = rev_y

    periods.sort(key=lambda p: p.key)
    return FinancialTable(periods=periods, rows=rows, money_unit=1.0)


# ------------------------------------------------------------- 시세·뉴스

def normalize_history(h: pd.DataFrame) -> pd.DataFrame:
    """yfinance history() → 네이버 일봉과 같은 열 이름의 DataFrame."""
    if h is None or h.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    df = h.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col]).dt.tz_localize(None).dt.normalize(),
            "open": pd.to_numeric(df.get("Open"), errors="coerce"),
            "high": pd.to_numeric(df.get("High"), errors="coerce"),
            "low": pd.to_numeric(df.get("Low"), errors="coerce"),
            "close": pd.to_numeric(df.get("Close"), errors="coerce"),
            "volume": pd.to_numeric(df.get("Volume"), errors="coerce"),
        }
    )
    return out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def normalize_news(raw: list) -> list[dict]:
    """yfinance 뉴스 → newness.detect 가 그대로 읽는 {'title','datetime'} 목록."""
    items: list[dict] = []
    for entry in raw or []:
        content = (entry or {}).get("content") or entry or {}
        title = content.get("title") or ""
        stamp = ""
        pub = content.get("pubDate") or content.get("displayTime")
        if pub:
            stamp = str(pub)[:10].replace("-", "")  # '2026-08-08T..' → '20260808'
        elif entry.get("providerPublishTime"):
            stamp = dt.datetime.fromtimestamp(
                int(entry["providerPublishTime"]), tz=dt.timezone.utc
            ).strftime("%Y%m%d")
        if title:
            items.append({"title": title, "datetime": stamp})
    return items


# ------------------------------------------------------------- 스냅샷·로드

def build_snapshot(
    symbol: str, info: dict, targets: dict | None, price_df: pd.DataFrame,
    inst_pct: float | None = None,
) -> Snapshot:
    price = price_date = change = None
    if not price_df.empty:
        price = _num(price_df["close"].iloc[-1])
        price_date = f"{price_df['date'].iloc[-1]:%Y%m%d}"
        if len(price_df) >= 2:
            prev = _num(price_df["close"].iloc[-2])
            if price is not None and prev is not None:
                change = price - prev
    if price is None:
        price = _num(info.get("currentPrice"))

    cns_eps = _num(info.get("_cns_eps"))  # load_all 이 채워 넣는다
    recomm = _num(info.get("recommendationMean"))
    return Snapshot(
        code=symbol,
        name=str(info.get("shortName") or info.get("longName") or symbol),
        market_cap=_num(info.get("marketCap")),
        price=price,
        price_date=price_date or "",
        change=change,
        per_naver=_num(info.get("trailingPE")),
        eps_naver=_num(info.get("trailingEps")),
        cns_eps_naver=cns_eps,
        cns_per_naver=(price / cns_eps) if price and cns_eps and cns_eps > 0 else None,
        pbr=_num(info.get("priceToBook")),
        bps=_num(info.get("bookValue")),
        high_52w=_num(info.get("fiftyTwoWeekHigh")),
        low_52w=_num(info.get("fiftyTwoWeekLow")),
        target_price=_num((targets or {}).get("mean")),
        # 야후는 1(강력매수)~5(매도), 네이버는 5가 매수 강함 → 화면 표기를 맞추려 뒤집는다
        recomm_mean=(6.0 - recomm) if recomm is not None else None,
        summary=str(info.get("longBusinessSummary") or ""),
        currency="USD",
        source_name="야후",
        inst_holding_pct=inst_pct * 100.0 if inst_pct is not None else None,
    )


def load_all(symbol: str) -> tuple[Snapshot, FinancialTable, FinancialTable, list[dict], pd.DataFrame]:
    """미국 종목 하나의 스냅샷 + 분기 + 연간 + 뉴스 + 일봉을 한 번에."""
    import yfinance as yf

    try:
        t = yf.Ticker(symbol)
        info = t.info or {}
        if not info.get("shortName") and not info.get("longName"):
            raise YahooFetchError(f"'{symbol}' 종목 정보를 찾지 못했습니다")

        q_income = t.quarterly_income_stmt
        a_income = t.income_stmt
        balance = t.quarterly_balance_sheet
        try:
            earnings_est = t.earnings_estimate
            revenue_est = t.revenue_estimate
        except Exception:  # 추정치는 없어도 분석은 계속한다
            earnings_est = revenue_est = None
        try:
            targets = t.analyst_price_targets
        except Exception:
            targets = None

        price_df = normalize_history(t.history(period="18mo", auto_adjust=True))
        articles = normalize_news(t.news)
    except YahooFetchError:
        raise
    except Exception as exc:
        raise YahooFetchError(f"야후 파이낸스 조회 실패 ({symbol}): {exc}") from exc

    quarterly = normalize_quarterly(q_income, balance, earnings_est, revenue_est)
    annual = normalize_annual(a_income, earnings_est, revenue_est)

    info = dict(info)
    info["_cns_eps"] = _est_value(earnings_est, "0y")
    snap = build_snapshot(
        symbol, info, targets, price_df, inst_pct=_num(info.get("heldPercentInstitutions"))
    )
    return snap, quarterly, annual, articles, price_df


def index_history(period: str = "18mo") -> pd.DataFrame:
    """S&P500 일봉 (L·M 판정용)."""
    import yfinance as yf

    try:
        return normalize_history(yf.Ticker(SP500_SYMBOL).history(period=period, auto_adjust=True))
    except Exception as exc:
        raise YahooFetchError(f"S&P500 지수 조회 실패: {exc}") from exc
