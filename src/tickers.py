"""종목명 ↔ 종목코드 변환. 한국(네이버) + 미국(야후) 검색을 하나로 합친다."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import naver

_CODE_RE = re.compile(r"^\d{6}$")            # 한국 6자리 코드
_US_TICKER_RE = re.compile(r"^[A-Za-z][A-Za-z.\-]{0,9}$")  # AAPL, BRK.B 등

# 야후 거래소 코드 중 미국 본토 시장만
_US_EXCHANGES = {"NMS", "NGM", "NCM", "NAS", "NYQ", "ASE", "PCX", "BTS"}
_EXCHANGE_KO = {"NASDAQ": "나스닥", "NYSE": "NYSE", "NYSEArca": "NYSE Arca", "AMEX": "AMEX"}


@dataclass(frozen=True)
class StockRef:
    code: str
    name: str
    market: str  # '코스피' / '코스닥' / '나스닥' / 'NYSE' ...
    region: str = "KR"  # 'KR' 또는 'US'

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code} · {self.market})"


def _search_kr(query: str, limit: int) -> list[StockRef]:
    try:
        payload = naver.autocomplete(query)
    except naver.NaverFetchError:
        return []

    results: list[StockRef] = []
    for item in payload.get("items", []):
        if item.get("nationCode") != "KOR" or item.get("category") != "stock":
            continue
        code = str(item.get("code", "")).strip()
        if not _CODE_RE.match(code):
            continue
        results.append(
            StockRef(
                code=code,
                name=str(item.get("name", "")).strip(),
                market=str(item.get("typeName") or item.get("typeCode") or "").strip(),
                region="KR",
            )
        )
        if len(results) >= limit:
            break
    return results


def _search_us(query: str, limit: int) -> list[StockRef]:
    """야후 검색. 미국 본토 거래소의 보통주만 돌려준다."""
    try:
        import yfinance as yf

        quotes = yf.Search(query, max_results=limit * 2).quotes
    except Exception:
        return []

    results: list[StockRef] = []
    for q in quotes or []:
        if q.get("quoteType") != "EQUITY":
            continue
        if q.get("exchange") not in _US_EXCHANGES:
            continue
        symbol = str(q.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        exch = str(q.get("exchDisp", "미국"))
        results.append(
            StockRef(
                code=symbol,
                name=str(q.get("shortname") or q.get("longname") or symbol).strip(),
                market=_EXCHANGE_KO.get(exch, exch),
                region="US",
            )
        )
        if len(results) >= limit:
            break
    return results


def search(query: str, limit: int = 10) -> list[StockRef]:
    """종목명 일부, 6자리 코드, 또는 미국 티커로 검색. 한국 결과를 먼저 놓는다."""
    query = (query or "").strip()
    if not query:
        return []

    kr = _search_kr(query, limit)
    us = _search_us(query, limit)

    # 'AAPL' 같은 티커 모양인데 야후 검색이 못 찾았으면 직접 입력한 티커로 간주
    if not us and not kr and _US_TICKER_RE.match(query):
        us = [StockRef(code=query.upper(), name=query.upper(), market="미국", region="US")]

    seen: set[tuple[str, str]] = set()
    merged: list[StockRef] = []
    for ref in kr + us:
        ident = (ref.region, ref.code)
        if ident in seen:
            continue
        seen.add(ident)
        merged.append(ref)
    return merged[:limit]


def resolve(query: str) -> StockRef | None:
    """검색어를 종목 하나로 확정한다. 6자리 코드/티커 정확 일치를 우선한다."""
    query = (query or "").strip()
    if not query:
        return None

    hits = search(query)
    if not hits:
        return None

    if _CODE_RE.match(query):
        for hit in hits:
            if hit.code == query:
                return hit

    upper = query.upper()
    for hit in hits:
        if hit.region == "US" and hit.code == upper:
            return hit

    # 이름이 정확히 일치하는 종목이 있으면 그것을 (예: '삼성전자' vs '삼성전자우')
    for hit in hits:
        if hit.name == query:
            return hit
    return hits[0]
