"""종목 하나를 끝까지 분석하는 진입점."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import canslim, fundamentals, newness as newness_mod, prices, tickers, valuation
from .fundamentals import FinancialTable, Snapshot
from .models import CanslimResult
from .newness import Newness
from .tickers import StockRef
from .valuation import ValuationResult


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
        raise StockNotFound(f"'{query}' 에 해당하는 국내 종목을 찾지 못했습니다.")
    return run_for(ref)


def run_for(ref: StockRef) -> Analysis:
    snap, quarterly, annual = fundamentals.load_all(ref.code, ref.name)

    index_name = prices.market_symbol(ref.market)
    stock_df = prices.load_ohlcv(ref.code)
    index_df = prices.load_ohlcv(index_name)

    fresh = newness_mod.load(ref.code, researches=snap.researches)

    val = valuation.compute_valuation(snap, quarterly, annual)
    cans, rs = canslim.analyze(
        snap, quarterly, annual, val.growth, stock_df, index_df, index_name, newness=fresh
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
