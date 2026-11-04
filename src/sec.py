"""미국 종목 분기 EPS — SEC EDGAR 공식 API (무료, 키 없음).

SEC 는 요청 헤더의 User-Agent 에 **연락처(이름·이메일)** 를 적도록 요구한다. 환경변수
`SEC_USER_AGENT` 에 "앱이름 연락처이메일" 형태로 넣어야 하고, 없으면 호출하지 않는다.
초당 10건 제한이 있지만 이 앱은 종목당 요청이 2건뿐이고 결과를 캐시한다.
"""

from __future__ import annotations

import datetime as dt
import json
import os

from . import crosscheck, naver
from .fundamentals import FinancialTable

SOURCE = "SEC EDGAR"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "EarningsPerShareBasic")
QUARTER_DAYS = (80, 100)       # 3개월짜리 값만 (누적 6·9개월, 연간은 제외)
ABS_FLOOR = 0.02               # 달러 — 센트 반올림 오차


def user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "").strip()


def _headers(ua: str) -> dict:
    return {"User-Agent": ua, "Accept": "application/json"}


def cik_for(symbol: str, tickers_json: dict) -> int | None:
    want = symbol.upper().replace("-", ".")
    for row in tickers_json.values():
        if str(row.get("ticker", "")).upper().replace("-", ".") == want:
            return int(row["cik_str"])
    return None


def quarterly_eps(facts: dict) -> dict[str, float]:
    """companyfacts → {'YYYYMM': 3개월 EPS}. 같은 분기가 여러 번 나오면(다음 해 비교 열 등)
    **가장 나중에 제출된 값**을 쓴다 — 주식분할 후 재작성된 값이 그쪽이다."""
    gaap = (facts.get("facts") or {}).get("us-gaap") or {}
    for tag in EPS_TAGS:
        entries = ((gaap.get(tag) or {}).get("units") or {}).get("USD/shares") or []
        best: dict[str, tuple[str, float]] = {}
        for e in entries:
            try:
                start = dt.date.fromisoformat(e["start"])
                end = dt.date.fromisoformat(e["end"])
                val = float(e["val"])
            except (KeyError, ValueError, TypeError):
                continue
            if not QUARTER_DAYS[0] <= (end - start).days <= QUARTER_DAYS[1]:
                continue
            key = f"{end.year}{end.month:02d}"
            filed = str(e.get("filed", ""))
            if key not in best or filed > best[key][0]:
                best[key] = (filed, val)
        if best:
            return {k: v for k, (_, v) in best.items()}
    return {}


def fetch_quarterly_eps(symbol: str) -> dict[str, float]:
    """SEC 에서 분기 EPS. 호출할 수 없으면 예외 (호출부가 CrossCheck 로 감싼다)."""
    ua = user_agent()
    if not ua:
        raise RuntimeError("SEC_USER_AGENT 환경변수(연락처 포함)가 설정되지 않았습니다")
    hdr = _headers(ua)
    tickers = json.loads(naver.fetch_text(TICKERS_URL, ttl=7 * 24 * 3600, headers=hdr))
    cik = cik_for(symbol, tickers)
    if cik is None:
        raise RuntimeError(f"SEC 에 {symbol} 티커가 없습니다 (외국 기업이거나 비상장)")
    facts = json.loads(naver.fetch_text(FACTS_URL.format(cik=cik), ttl=24 * 3600, headers=hdr))
    return quarterly_eps(facts)


def cross_check(symbol: str, quarterly: FinancialTable) -> crosscheck.CrossCheck:
    try:
        eps = fetch_quarterly_eps(symbol)
    except Exception as exc:  # 보조 검증이라 어떤 실패도 분석을 멈추지 않는다
        return crosscheck.unavailable(SOURCE, str(exc))
    if not eps:
        return crosscheck.unavailable(SOURCE, "분기 EPS 항목이 없습니다")
    return crosscheck.compare(quarterly, eps, SOURCE, ABS_FLOOR, unit="$")
