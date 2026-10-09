"""코스피·코스닥 전 종목 CANSLIM 스크리너 (웹앱과 분리된 도구 — screen.py 가 실행한다).

2단계로 거른다.
  1차 (전 종목): 네이버 분기·연간 재무만으로 C·A 실적 조건을 본다. 판정은 웹앱과 같은
      canslim._item_c / _item_a 를 그대로 쓴다. C2(직전 분기 전년비)는 재무표가 확정 5분기뿐이라
      여기선 판단불가가 정상이므로 통과를 막지 않는다.
  2차 (1차 통과 종목만): 웹앱과 같은 analyze.run_for 로 7개 항목 전부와 투자의견을 본다
      (C2 는 야후 실적 발표 이력으로 보강된다).

미국(US): 대상 목록은 나스닥 스크리너(미국 상장 전 종목, 시가총액 포함), 1차 재무는 야후.
미국은 웹앱처럼 I(기관 수급)가 늘 판단불가라 '7개 전부 합격'이 원리상 나오지 않으므로,
I만 판단불가이고 나머지 6개가 합격이면 '조건부 충족'으로 따로 표시한다.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

from . import analyze, canslim, fundamentals, naver, yahoo
from .fundamentals import Snapshot
from .models import CanslimItem, SubCheck
from .tickers import StockRef
from .valuation import EPS, REVENUE, compute_growth, yoy

MARKETS = ("KOSPI", "KOSDAQ")
MARKET_KR = {"KOSPI": "코스피", "KOSDAQ": "코스닥", "US": "미국"}
PAGE_SIZE = 100
EOK = 1e8
NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&download=true"
US_INTERVAL = 0.3   # 야후 연속 요청 사이 쉬는 시간(초) — 한꺼번에 몰아 막히지 않게
# 미국 목록에서 보통주가 아닌 것 (우선주·워런트·유닛·권리·채권)
US_NAME_EXCLUDE = re.compile(r"preferred|warrant|\bunits?\b|\brights?\b|\bnotes?\b|debenture", re.I)
US_SYMBOL = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")
C2_CODE = "C2"   # 1차에서는 판단불가를 허용하는 조건

PASS, NEAR, FAIL, ERROR = "통과", "근접", "탈락", "오류"


# ------------------------------------------------------------------ 대상 종목

@dataclass(frozen=True)
class UniverseItem:
    code: str
    name: str
    market: str            # 'KOSPI' / 'KOSDAQ' / 'US'
    cap: float | None      # 시가총액 (현지 통화 원값 — 원 또는 달러)

    @property
    def region(self) -> str:
        return "US" if self.market == "US" else "KR"

    @property
    def currency(self) -> str:
        return "USD" if self.region == "US" else "KRW"

    @property
    def ref(self) -> StockRef:
        return StockRef(code=self.code, name=self.name, market=MARKET_KR[self.market], region=self.region)


def _to_float(text) -> float | None:
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def is_excluded(code: str, name: str) -> str:
    """제외 사유. 비어 있으면 대상. 우선주는 코드 끝자리가 0이 아니다 (예: 005935 삼성전자우)."""
    if not code.isdigit() or len(code) != 6:
        return "코드 형식"
    if code[-1] != "0":
        return "우선주"
    if "스팩" in name:
        return "스팩"
    return ""


def parse_universe(payload: dict, market: str) -> list[UniverseItem]:
    out = []
    for s in (payload or {}).get("stocks", []):
        if s.get("stockEndType") != "stock":
            continue  # ETF·ETN
        code, name = str(s.get("itemCode", "")), str(s.get("stockName", ""))
        if is_excluded(code, name):
            continue
        cap = _to_float(s.get("marketValue"))   # 억원
        out.append(UniverseItem(code, name, market, cap * EOK if cap is not None else None))
    return out


_ADR = re.compile(r"\s*American Depositary Shares?.*$", re.I)
_SHARE_SUFFIX = re.compile(r"\s+(Common Stock|Common Shares|Ordinary Shares|Class [A-Z] Ordinary Shares)\s*$", re.I)


def clean_us_name(name: str) -> str:
    """'Apple Inc. Common Stock' → 'Apple Inc.', 'Taiwan Semi… American Depositary Shares' → '… (ADR)'."""
    if _ADR.search(name):
        return _ADR.sub("", name).strip() + " (ADR)"
    return _SHARE_SUFFIX.sub("", name).strip()


def parse_universe_us(payload: dict) -> list[UniverseItem]:
    """나스닥 스크리너 응답 → 보통주(ADR 포함). 'BRK/B' 같은 클래스 주식은 야후 표기 'BRK-B' 로."""
    rows = (((payload or {}).get("data") or {}).get("rows")) or []
    out: list[UniverseItem] = []
    for r in rows:
        symbol = str(r.get("symbol", "")).strip().replace("/", "-")
        name = re.sub(r"\s+", " ", str(r.get("name", ""))).strip()
        if not US_SYMBOL.match(symbol) or US_NAME_EXCLUDE.search(name):
            continue
        cap = _to_float(r.get("marketCap"))
        if not cap:
            continue
        out.append(UniverseItem(symbol, clean_us_name(name), "US", cap))
    out.sort(key=lambda i: i.cap or 0, reverse=True)
    return out


def fetch_universe_us() -> list[UniverseItem]:
    resp = requests.get(NASDAQ_SCREENER_URL, timeout=60, headers={
        "User-Agent": naver.HEADERS["User-Agent"], "Accept": "application/json"})
    resp.raise_for_status()
    return parse_universe_us(resp.json())


def fetch_universe(markets: tuple[str, ...] = MARKETS) -> list[UniverseItem]:
    items: list[UniverseItem] = []
    for market in markets:
        if market == "US":
            items.extend(fetch_universe_us())
            continue
        page = 1
        while True:
            payload = naver.market_list(market, page, PAGE_SIZE)
            if not payload.get("stocks"):
                break
            items.extend(parse_universe(payload, market))
            page += 1
    return items


# ------------------------------------------------------------------ 1차: C·A

@dataclass
class CaResult:
    item: UniverseItem
    status: str                                  # 통과 / 근접 / 탈락 / 오류
    failed: list[str] = field(default_factory=list)    # 불합격 조건 코드 (예: ['C4'])
    unknown: list[str] = field(default_factory=list)   # 판단불가 조건 코드 (C2 제외)
    latest_quarter: str = ""
    eps_yoy: float | None = None                 # C1 최근 분기 EPS 전년비 %
    revenue_yoy: float | None = None             # C4 최근 분기 매출 전년비 %
    annual_cagr: float | None = None             # A1 연간 EPS 연평균 성장률 %
    roe: float | None = None                     # A3 최근 분기 ROE %
    detail: str = ""                             # 세부 조건 문장 (줄바꿈 구분)
    error: str = ""


def classify(checks: list[SubCheck]) -> tuple[str, list[str], list[str]]:
    """세부 조건 목록 → (상태, 불합격 코드, 판단불가 코드). C2 판단불가는 1차에서 문제 삼지 않는다."""
    failed = [c.code for c in checks if c.passed is False]
    unknown = [c.code for c in checks if c.passed is None and c.code != C2_CODE]
    if not failed and not unknown:
        return PASS, failed, unknown
    if len(failed) <= 1:
        return NEAR, failed, unknown
    return FAIL, failed, unknown


def latest_roe(quarterly) -> float | None:
    """canslim.analyze 와 같은 방식 — 값이 있는 가장 최근 확정 분기 ROE."""
    return next(
        (quarterly.value("ROE", p.key) for p in reversed(quarterly.actual_periods())
         if quarterly.value("ROE", p.key) is not None),
        None,
    )


def ca_items(quarterly, annual, name: str = "", code: str = "",
             currency: str = "KRW") -> tuple[CanslimItem, CanslimItem, float | None]:
    growth = compute_growth(quarterly, annual)
    snap = Snapshot(code=code, name=name, market_cap=None, price=None, currency=currency)  # 금액 표시용
    roe = latest_roe(quarterly)
    return canslim._item_c(quarterly, growth, snap), canslim._item_a(growth, annual, roe, snap), roe


def screen_ca(item: UniverseItem) -> CaResult:
    try:
        if item.region == "US":
            quarterly, annual = yahoo.load_financials(item.code)
        else:
            quarterly = fundamentals.parse_finance(naver.finance(item.code, "quarter"))
            annual = fundamentals.parse_finance(naver.finance(item.code, "annual"))
        c, a, roe = ca_items(quarterly, annual, item.name, item.code, item.currency)
    except Exception as exc:  # 비공식 API — 한 종목 실패가 전체를 멈추면 안 된다
        return CaResult(item, ERROR, error=str(exc)[:200])

    status, failed, unknown = classify(c.checks + a.checks)
    growth = compute_growth(quarterly, annual)
    q_rev = [p for p in quarterly.actual_periods() if quarterly.value(REVENUE, p.key) is not None]
    rev_yoy = None
    if q_rev:
        last = q_rev[-1]
        rev_yoy = yoy(quarterly.value(REVENUE, last.key),
                      quarterly.value(REVENUE, f"{last.year - 1}{last.month:02d}"))
    q_eps = [p for p in quarterly.actual_periods() if quarterly.value(EPS, p.key) is not None]
    return CaResult(
        item=item, status=status, failed=failed, unknown=unknown,
        latest_quarter=q_eps[-1].label if q_eps else "",
        eps_yoy=growth.quarter_yoy.value if growth.quarter_yoy.is_ok else None,
        revenue_yoy=rev_yoy,
        annual_cagr=growth.annual_cagr.value if growth.annual_cagr.is_ok else None,
        roe=roe,
        detail="\n".join(x for x in (c.checks_text, a.checks_text) if x),
    )


# ------------------------------------------------------------------ 2차: 정밀

@dataclass
class DeepResult:
    item: UniverseItem
    summary: str = ""                       # 'CANSLIM 충족' / '미충족' / '미충족 (자료 부족)'
    tally: str = ""
    qualified: bool = False
    # I(기관 수급)만 판단불가이고 나머지 6개 합격 — 미국은 I를 판정할 자료가 없어 이것이 사실상 최고 등급
    qualified_ex_i: bool = False
    verdicts: dict[str, str] = field(default_factory=dict)   # {'C': '합격', ...}
    opinion: str = ""
    base_gap: float | None = None
    price: float | None = None
    error: str = ""


def _qualified_ex_i(cans) -> bool:
    others = [i.verdict for i in cans.items if i.letter != "I"]
    i_item = next((i for i in cans.items if i.letter == "I"), None)
    return (bool(others) and all(v.value == "합격" for v in others)
            and i_item is not None and i_item.verdict.value == "판단불가")


def deep_check(item: UniverseItem) -> DeepResult:
    try:
        a = analyze.run_for(item.ref)
    except Exception as exc:
        return DeepResult(item, error=str(exc)[:200])
    return DeepResult(
        item=item,
        summary=a.canslim.summary,
        tally=a.canslim.tally,
        qualified=a.canslim.qualified,
        qualified_ex_i=_qualified_ex_i(a.canslim),
        verdicts={i.letter: i.verdict.value for i in a.canslim.items},
        opinion=a.opinion.text if a.opinion else "",
        base_gap=a.target.base_gap if a.target else None,
        price=a.snap.price,
    )


# ------------------------------------------------------------------ 실행

@dataclass
class ScreenResult:
    started: float
    finished: float = 0.0
    universe: int = 0
    ca: list[CaResult] = field(default_factory=list)
    deep: dict[str, DeepResult] = field(default_factory=dict)   # 코드 → 2차 결과
    interrupted: bool = False

    def by_status(self, status: str) -> list[CaResult]:
        return [r for r in self.ca if r.status == status]


def _eta(done: int, total: int, started: float) -> str:
    if done == 0:
        return "계산 중"
    left = (time.time() - started) / done * (total - done)
    return f"{int(left // 60)}분 {int(left % 60)}초"


def run(
    markets: tuple[str, ...] = MARKETS,
    limit: int | None = None,
    min_cap: float = 0.0,          # 현지 통화 원값 (원 또는 달러)
    deep: bool = True,
    progress: Callable[[str], None] = print,
    universe: list[UniverseItem] | None = None,
) -> ScreenResult:
    result = ScreenResult(started=time.time())
    try:
        progress("대상 종목 목록을 받는 중…")
        items = universe if universe is not None else fetch_universe(markets)
        items = [i for i in items if (i.cap or 0) >= min_cap]
        if limit:
            items = items[:limit]
        result.universe = len(items)
        progress(f"대상 {len(items):,}종목 — 1차(C·A 실적) 시작")

        t0 = time.time()
        for n, item in enumerate(items, start=1):
            result.ca.append(screen_ca(item))
            if item.region == "US":
                time.sleep(US_INTERVAL)
            if n % 50 == 0 or n == len(items):
                progress(f"  1차 {n:,}/{len(items):,} · 통과 {len(result.by_status(PASS))} · "
                         f"근접 {len(result.by_status(NEAR))} · 남은 시간 약 {_eta(n, len(items), t0)}")

        if deep:
            passed = result.by_status(PASS)
            progress(f"2차(정밀 CANSLIM) {len(passed)}종목 시작")
            for n, r in enumerate(passed, start=1):
                result.deep[r.item.code] = deep_check(r.item)
                progress(f"  2차 {n}/{len(passed)} {r.item.name}: {result.deep[r.item.code].summary or '오류'}")
    except KeyboardInterrupt:
        result.interrupted = True
        progress("중단 요청 — 지금까지의 결과로 저장합니다.")
    result.finished = time.time()
    return result
