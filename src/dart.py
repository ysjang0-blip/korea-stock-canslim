"""한국 종목 분기 EPS — DART(금융감독원 전자공시) 공식 OpenAPI.

무료 인증키가 필요하다 (https://opendart.fss.or.kr 에서 발급). 환경변수 `DART_API_KEY` 에 넣고,
없으면 호출하지 않는다.

3개월 EPS 를 직접 주는 1·2·3분기 보고서만 쓴다. 4분기는 사업보고서(연간)에서 3분기 누적을
빼야 하는데 EPS 는 주식수 변동 때문에 뺄셈이 정확하지 않아 비교에서 뺀다.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import zipfile

import requests
from defusedxml import ElementTree as ET

from . import crosscheck, naver
from .fundamentals import FinancialTable

SOURCE = "DART"
API = "https://opendart.fss.or.kr/api"
CORP_CACHE = naver.CACHE_DIR / "dart_corp_codes.json"
CORP_TTL = 30 * 24 * 3600
REPORTS = {3: "11013", 6: "11012", 9: "11014"}   # 1분기 · 반기 · 3분기 보고서
ABS_FLOOR = 1.0                                  # 원
EPS_NAMES = ("기본주당이익", "기본주당순이익", "기본주당손익", "기본주당이익(손실)", "기본주당순이익(손실)")


def api_key() -> str:
    return os.environ.get("DART_API_KEY", "").strip()


def load_corp_codes(key: str) -> dict[str, str]:
    """{종목코드 6자리: DART 고유번호 8자리}. 내려받는 파일이 커서 30일 캐시한다."""
    import time
    if CORP_CACHE.exists() and time.time() - CORP_CACHE.stat().st_mtime < CORP_TTL:
        try:
            return json.loads(CORP_CACHE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    resp = requests.get(f"{API}/corpCode.xml", params={"crtfc_key": key}, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        root = ET.fromstring(z.read(z.namelist()[0]))
    out = {}
    for item in root.iter("list"):
        stock = (item.findtext("stock_code") or "").strip()
        if stock:
            out[stock] = (item.findtext("corp_code") or "").strip()
    try:
        CORP_CACHE.parent.mkdir(parents=True, exist_ok=True)
        CORP_CACHE.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


def parse_eps(payload: dict) -> float | None:
    """fnlttSinglAcntAll 응답 → 해당 보고서의 3개월 기본 EPS. 못 찾으면 None."""
    if str(payload.get("status")) != "000":
        return None
    for row in payload.get("list") or []:
        if row.get("sj_div") not in ("IS", "CIS"):
            continue
        name = str(row.get("account_nm", "")).replace(" ", "")
        if "BasicEarningsLossPerShare" in str(row.get("account_id", "")) or name in EPS_NAMES:
            raw = str(row.get("thstrm_amount", "")).replace(",", "").strip()
            try:
                return float(raw)
            except ValueError:
                return None
    return None


def _report(key: str, corp: str, year: int, code: str, fs_div: str) -> float | None:
    params = (f"crtfc_key={key}&corp_code={corp}&bsns_year={year}"
              f"&reprt_code={code}&fs_div={fs_div}")
    # 과거 연도의 보고서는 바뀌지 않으므로 오래 캐시한다
    ttl = 24 * 3600 if year >= dt.date.today().year else 30 * 24 * 3600
    text = naver.fetch_text(f"{API}/fnlttSinglAcntAll.json?{params}", ttl=ttl,
                            headers={"Accept": "application/json"})
    return parse_eps(json.loads(text))


def fetch_quarterly_eps(code: str, years: int = 2) -> dict[str, float]:
    key = api_key()
    if not key:
        raise RuntimeError("DART_API_KEY 환경변수가 설정되지 않았습니다")
    corp = load_corp_codes(key).get(code)
    if not corp:
        raise RuntimeError(f"DART 에 종목코드 {code} 가 없습니다")
    this_year = dt.date.today().year
    out: dict[str, float] = {}
    for year in range(this_year, this_year - years, -1):
        for month, report in REPORTS.items():
            eps = _report(key, corp, year, report, "CFS")        # 연결 우선
            if eps is None:
                eps = _report(key, corp, year, report, "OFS")    # 연결이 없으면 별도
            if eps is not None:
                out[f"{year}{month:02d}"] = eps
    return out


def cross_check(code: str, quarterly: FinancialTable) -> crosscheck.CrossCheck:
    try:
        eps = fetch_quarterly_eps(code)
    except Exception as exc:  # 보조 검증이라 어떤 실패도 분석을 멈추지 않는다
        # 오류 문구에 요청 주소(인증키 포함)가 들어갈 수 있어, 화면·보고서로 새지 않게 지운다
        msg, key = str(exc), api_key()
        return crosscheck.unavailable(SOURCE, msg.replace(key, "***") if key else msg)
    if not eps:
        return crosscheck.unavailable(SOURCE, "1~3분기 보고서에서 EPS 를 찾지 못했습니다")
    return crosscheck.compare(quarterly, eps, SOURCE, ABS_FLOOR, unit="원")
