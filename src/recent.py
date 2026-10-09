"""최근 분석한 종목 목록 — 브라우저 쿠키에 기기별로 저장한다.

쿠키 값은 URL 인코딩한 짧은 JSON 배열: [{"c":코드,"n":이름,"m":시장,"r":지역}, ...].
쿠키 한 개는 4KB 제한이 있어 최대 MAX_ITEMS 개만 두고, 깨진 값은 조용히 빈 목록으로 본다.
"""

from __future__ import annotations

import json
from urllib.parse import quote, unquote

from .tickers import StockRef

COOKIE_NAME = "recent_stocks"
MAX_ITEMS = 10
MAX_AGE_SEC = 365 * 24 * 60 * 60


def _key(ref: StockRef) -> tuple[str, str]:
    return ref.region, ref.code


def push(items: list[StockRef], ref: StockRef) -> list[StockRef]:
    """ref 를 맨 앞으로 (이미 있으면 옮김), 최대 MAX_ITEMS 개."""
    rest = [r for r in items if _key(r) != _key(ref)]
    return [ref, *rest][:MAX_ITEMS]


def remove(items: list[StockRef], ref: StockRef) -> list[StockRef]:
    return [r for r in items if _key(r) != _key(ref)]


def encode(items: list[StockRef]) -> str:
    payload = [{"c": r.code, "n": r.name, "m": r.market, "r": r.region} for r in items[:MAX_ITEMS]]
    return quote(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), safe="")


def decode(value: str | None) -> list[StockRef]:
    if not value:
        return []
    try:
        payload = json.loads(unquote(value))
    except (ValueError, TypeError):
        return []
    out: list[StockRef] = []
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict) or not item.get("c") or not item.get("n"):
            continue
        ref = StockRef(code=str(item["c"]), name=str(item["n"]),
                       market=str(item.get("m") or ""), region=str(item.get("r") or "KR"))
        if all(_key(r) != _key(ref) for r in out):
            out.append(ref)
    return out[:MAX_ITEMS]


def cookie_script(items: list[StockRef]) -> str:
    """쿠키를 쓰는 <script>. 값은 encode() 결과라 따옴표·세미콜론이 들어갈 수 없다."""
    return (f"<script>document.cookie='{COOKIE_NAME}={encode(items)};"
            f"max-age={MAX_AGE_SEC};path=/;SameSite=Lax';</script>")
