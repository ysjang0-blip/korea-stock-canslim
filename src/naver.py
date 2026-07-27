"""네이버 금융 비공식 API 호출 계층.

이 모듈만 네트워크를 만진다. 나머지 모듈은 전부 여기서 받은 결과만 다룬다.

비공식·미문서화 API이므로 다음 세 가지를 지킨다.
  1. 디스크 캐시(기본 24시간) — 같은 데이터를 하루에 한 번만 받아온다.
  2. 요청 간 최소 간격 — 연달아 때리지 않는다.
  3. 실패 시 지수 백오프 재시도 — 일시적 오류에 바로 포기하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
DEFAULT_TTL = 24 * 60 * 60  # 24시간
MIN_INTERVAL = 0.34  # 초. 연속 요청 사이 최소 간격
TIMEOUT = 20
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://m.stock.naver.com/",
    "Accept": "application/json, text/plain, */*",
}

_lock = threading.Lock()
_last_call_at = 0.0


class NaverFetchError(RuntimeError):
    """네이버에서 데이터를 받아오지 못했을 때."""


def _throttle() -> None:
    global _last_call_at
    with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call_at)
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{digest}.txt"


def _read_cache(path: Path, ttl: int) -> str | None:
    if ttl <= 0 or not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _write_cache(path: Path, text: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass  # 캐시 실패는 조회 실패가 아니다


def fetch_text(url: str, ttl: int = DEFAULT_TTL) -> str:
    """URL을 받아 본문 문자열을 돌려준다. 캐시가 유효하면 네트워크를 타지 않는다."""
    path = _cache_path(url)
    cached = _read_cache(path, ttl)
    if cached is not None:
        return cached

    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(1.5 * (2**(attempt - 1)))  # 1.5s, 3s
        _throttle()
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            last_error = exc
            continue

        if resp.status_code == 404:
            raise NaverFetchError(f"존재하지 않는 주소이거나 없는 종목입니다 (404): {url}")
        if resp.status_code in (429, 500, 502, 503, 504):
            last_error = NaverFetchError(f"HTTP {resp.status_code}")
            continue
        if not resp.ok:
            raise NaverFetchError(f"HTTP {resp.status_code} — {url}")

        resp.encoding = resp.encoding or "utf-8"
        text = resp.text
        _write_cache(path, text)
        return text

    raise NaverFetchError(
        f"네이버 응답을 받지 못했습니다 ({MAX_RETRIES}회 시도). 마지막 오류: {last_error}"
    )


def fetch_json(url: str, ttl: int = DEFAULT_TTL) -> Any:
    text = fetch_text(url, ttl=ttl)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise NaverFetchError(f"JSON 형식이 아닙니다 — {url}") from exc


# ---------------------------------------------------------------- 엔드포인트

def integration(code: str, ttl: int = 60 * 60) -> dict:
    """현재가·PER·추정EPS·52주 고저·외인소진율·목표주가 등 요약 (시세 포함이라 1시간 캐시)."""
    return fetch_json(f"https://m.stock.naver.com/api/stock/{code}/integration", ttl=ttl)


def finance(code: str, period: str, ttl: int = DEFAULT_TTL) -> dict:
    """분기/연간 재무제표. period 는 'quarter' 또는 'annual'."""
    if period not in ("quarter", "annual"):
        raise ValueError("period 는 'quarter' 또는 'annual' 이어야 합니다")
    return fetch_json(f"https://m.stock.naver.com/api/stock/{code}/finance/{period}", ttl=ttl)


def autocomplete(query: str, ttl: int = 7 * DEFAULT_TTL) -> dict:
    """종목명 자동완성 검색."""
    return fetch_json(
        f"https://ac.stock.naver.com/ac?q={quote(query)}&target=stock&where=stock", ttl=ttl
    )


def sise_json(symbol: str, start: str, end: str, ttl: int = 6 * 60 * 60) -> str:
    """일봉 원문. symbol 은 종목코드 또는 'KOSPI'/'KOSDAQ'. 날짜는 'YYYYMMDD'.

    반환값은 JSON이 아니라 작은따옴표를 쓰는 자바스크립트 리터럴이므로 문자열 그대로 준다.
    """
    url = (
        "https://fchart.stock.naver.com/siseJson.nhn"
        f"?symbol={symbol}&requestType=1&startTime={start}&endTime={end}&timeframe=day"
    )
    return fetch_text(url, ttl=ttl)
