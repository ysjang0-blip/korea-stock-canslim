"""종목 하나를 끝까지 분석하는 진입점. 한국(네이버)과 미국(야후)을 여기서 가른다."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd

from . import canslim, fundamentals, newness as newness_mod, prices, tickers, valuation, yahoo
from .fundamentals import FinancialTable, Snapshot
from .models import CanslimResult
from .newness import Newness
from .tickers import StockRef
from .valuation import ValuationResult

US_MARKET_CLOSE = dt.time(16, 0)
US_TZ = ZoneInfo("America/New_York")


class StockNotFound(LookupError):
    pass


@dataclass
class Analysis:
    ref: StockRef
    snap: Snapshot
    quarterly: FinancialTable
    annual: FinancialTable
    valuation: ValuationResult
    canslim: CanslimResult
    rs: canslim.RelativeStrength
    newness: Newness
    stock_df: pd.DataFrame
    index_df: pd.DataFrame
    index_name: str


def run(query: str) -> Analysis:
    ref = tickers.resolve(query)
    if ref is None:
        raise StockNotFound(f"'{query}' 에 해당하는 종목을 찾지 못했습니다.")
    return run_for(ref)


def run_for(ref: StockRef) -> Analysis:
    if ref.region == "US":
        return _run_us(ref)
    return _run_kr(ref)


def _run_kr(ref: StockRef) -> Analysis:
    snap, quarterly, annual = fundamentals.load_all(ref.code, ref.name)

    index_name = prices.market_symbol(ref.market)
    stock_df = prices.load_ohlcv(ref.code)
    index_df = prices.load_ohlcv(index_name)

    fresh = newness_mod.load(ref.code, researches=snap.researches)

    return _assemble(ref, snap, quarterly, annual, stock_df, index_df, index_name, fresh,
                     close_time=prices.KR_MARKET_CLOSE, tz=prices.KST)


def _run_us(ref: StockRef) -> Analysis:
    snap, quarterly, annual, articles, stock_df = yahoo.load_all(ref.code)
    index_df = yahoo.index_history()

    fresh = newness_mod.detect(disclosures=[], articles=articles, researches=[])

    return _assemble(ref, snap, quarterly, annual, stock_df, index_df, yahoo.SP500_NAME, fresh,
                     close_time=US_MARKET_CLOSE, tz=US_TZ)


def _assemble(
    ref: StockRef,
    snap: Snapshot,
    quarterly: FinancialTable,
    annual: FinancialTable,
    stock_df: pd.DataFrame,
    index_df: pd.DataFrame,
    index_name: str,
    fresh: Newness,
    close_time: dt.time,
    tz: dt.tzinfo,
) -> Analysis:
    val = valuation.compute_valuation(snap, quarterly, annual)

    # 판정에는 완결된 거래일만 쓴다 — 장중 부분 거래량이 S 를 왜곡하지 않게.
    # 차트에는 원본(stock_df)을 그대로 써서 오늘 봉도 보이게 한다.
    stock_done = prices.complete_sessions(stock_df, close_time=close_time, tz=tz)
    index_done = prices.complete_sessions(index_df, close_time=close_time, tz=tz)

    cans, rs = canslim.analyze(
        snap, quarterly, annual, val.growth, stock_done, index_done, index_name, newness=fresh
    )

    return Analysis(
        ref=ref,
        snap=snap,
        quarterly=quarterly,
        annual=annual,
        valuation=val,
        canslim=cans,
        rs=rs,
        newness=fresh,
        stock_df=stock_df,
        index_df=index_df,
        index_name=index_name,
    )
