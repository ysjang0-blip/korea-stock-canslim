"""종목명 ↔ 종목코드 변환."""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import naver

_CODE_RE = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class StockRef:
    code: str
    name: str
    market: str  # '코스피' / '코스닥'

    @property
    def label(self) -> str:
        return f"{self.name} ({self.code} · {self.market})"


def search(query: str, limit: int = 10) -> list[StockRef]:
    """종목명 일부 또는 6자리 코드로 검색. 국내 주식만 돌려준다."""
    query = (query or "").strip()
    if not query:
        return []

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
            )
        )
        if len(results) >= limit:
            break
    return results


def resolve(query: str) -> StockRef | None:
    """검색어를 종목 하나로 확정한다. 6자리 코드면 정확히 그 코드를 우선 고른다."""
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

    # 이름이 정확히 일치하는 종목이 있으면 그것을 (예: '삼성전자' vs '삼성전자우')
    for hit in hits:
        if hit.name == query:
            return hit
    return hits[0]
