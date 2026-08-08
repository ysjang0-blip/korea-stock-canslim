"""네이버 재무/시세 JSON을 계산하기 좋은 형태로 정규화한다.

두 가지를 다룬다.
  * FinancialTable — 분기/연간 재무제표 (매출액·EPS·ROE ...)
  * Snapshot       — 현재가·시가총액·52주 고저·목표주가 등 요약

네이버가 행 순서를 바꿔도 깨지지 않도록, 행은 순서가 아니라 **한글 라벨**로 찾는다.
단위 주의: 매출액·이익은 '억원', EPS·BPS는 '원', 비율은 '%'.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from . import naver

EOK = 100_000_000        # 1억
JO = 1_000_000_000_000   # 1조

_NUM_RE = re.compile(r"[-+]?[\d,]*\.?\d+")


def to_number(raw) -> float | None:
    """'1,738,644' → 1738644.0 / '20.53배' → 20.53 / '-' → None / '+487,617' → 487617.0"""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip()
    if not text or text in {"-", "N/A", "NaN", "null"}:
        return None
    match = _NUM_RE.search(text.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group().replace(",", ""))
    except ValueError:
        return None


def parse_korean_amount(raw) -> float | None:
    """'1,484조 9,548억' → 1.4849548e15 (원 단위). '8조 5,199억' 같은 표기 전용."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == "-":
        return None

    total = 0.0
    matched = False
    for value, unit in re.findall(r"([\d,]+(?:\.\d+)?)\s*(조|억|만)?", text):
        if not value.strip(","):
            continue
        try:
            num = float(value.replace(",", ""))
        except ValueError:
            continue
        multiplier = {"조": JO, "억": EOK, "만": 10_000, "": 1.0, None: 1.0}[unit or ""]
        total += num * multiplier
        matched = True
    return total if matched else None


# ------------------------------------------------------------- 재무제표

@dataclass(frozen=True)
class Period:
    key: str          # '202603'
    title: str        # '2026.03.'
    is_consensus: bool

    @property
    def year(self) -> int:
        return int(self.key[:4])

    @property
    def month(self) -> int:
        return int(self.key[4:6])

    @property
    def label(self) -> str:
        return f"{self.year}.{self.month:02d}"


@dataclass
class FinancialTable:
    """기간(오름차순)과 라벨별 값. 값 단위는 원본 그대로.

    money_unit: 매출액 같은 금액 행을 통화 기본 단위로 바꾸는 배수.
    네이버(한국)는 억원이라 1억, 야후(미국)는 달러 그대로라 1.
    """

    periods: list[Period] = field(default_factory=list)
    rows: dict[str, dict[str, float | None]] = field(default_factory=dict)
    money_unit: float = EOK

    def value(self, label: str, key: str) -> float | None:
        return self.rows.get(label, {}).get(key)

    def actual_periods(self) -> list[Period]:
        """실적이 확정된 기간. 값이 실제로 있는 것만."""
        return [p for p in self.periods if not p.is_consensus]

    def consensus_periods(self) -> list[Period]:
        return [p for p in self.periods if p.is_consensus]

    def series(self, label: str, consensus: bool | None = None) -> list[tuple[Period, float | None]]:
        """(기간, 값) 목록. consensus=False면 실적확정만, True면 컨센서스만."""
        out = []
        for p in self.periods:
            if consensus is not None and p.is_consensus is not consensus:
                continue
            out.append((p, self.value(label, p.key)))
        return out

    def last_actual_values(self, label: str, count: int) -> list[tuple[Period, float]]:
        """실적확정 기간 중 값이 있는 것을 최신순 count 개, 오래된 것부터 반환."""
        pairs = [(p, v) for p, v in self.series(label, consensus=False) if v is not None]
        return pairs[-count:] if count <= len(pairs) else []


def parse_finance(payload: dict) -> FinancialTable:
    info = (payload or {}).get("financeInfo") or {}

    periods = [
        Period(
            key=str(t.get("key", "")).strip(),
            title=str(t.get("title", "")).strip(),
            is_consensus=str(t.get("isConsensus", "N")).upper() == "Y",
        )
        for t in info.get("trTitleList", [])
        if str(t.get("key", "")).strip()
    ]
    periods.sort(key=lambda p: p.key)  # columns 사전은 순서가 뒤섞여 오므로 반드시 정렬

    rows: dict[str, dict[str, float | None]] = {}
    for row in info.get("rowList", []):
        label = str(row.get("title", "")).strip()
        if not label:
            continue
        rows[label] = {
            str(key): to_number((cell or {}).get("value"))
            for key, cell in (row.get("columns") or {}).items()
        }

    return FinancialTable(periods=periods, rows=rows)


# ------------------------------------------------------------- 요약 정보

@dataclass
class Snapshot:
    code: str
    name: str
    market_cap: float | None            # 원
    price: float | None                 # 원 (최신 종가)
    price_date: str = ""                # 'YYYYMMDD'
    change: float | None = None         # 전일 대비 (원)
    per_naver: float | None = None
    eps_naver: float | None = None      # TTM EPS (원)
    cns_per_naver: float | None = None  # 네이버 '추정PER'
    cns_eps_naver: float | None = None  # 네이버 '추정EPS' = 당해연도 연간 컨센서스 EPS
    pbr: float | None = None
    bps: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    foreign_rate: float | None = None   # 외국인 소진율 %
    dividend_yield: float | None = None
    target_price: float | None = None   # 애널리스트 목표주가 평균
    recomm_mean: float | None = None    # 투자의견 평균 (1~5, 낮을수록 매수)
    consensus_date: str = ""
    summary: str = ""                   # 기업 개요
    deal_trend: pd.DataFrame = field(default_factory=pd.DataFrame)
    researches: list = field(default_factory=list)  # 증권사 리포트 (CANSLIM N 보조 근거)
    currency: str = "KRW"               # 'KRW' 또는 'USD'
    source_name: str = "네이버"          # 교차검증 문구에 쓸 출처 이름
    inst_holding_pct: float | None = None  # 기관 보유 비중 % (미국 전용)

    @property
    def change_pct(self) -> float | None:
        if self.price is None or self.change is None:
            return None
        prev = self.price - self.change
        return (self.change / prev * 100.0) if prev else None

    @property
    def upside_pct(self) -> float | None:
        """목표주가까지 상승여력 %."""
        if not self.target_price or not self.price:
            return None
        return (self.target_price / self.price - 1.0) * 100.0

    @property
    def price_date_label(self) -> str:
        """'20260807' → '2026-08-07'."""
        d = self.price_date
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d

    def money(self, value: float | None, digits: int | None = None) -> str:
        """통화에 맞는 금액 문자열. 원화는 정수, 달러는 소수 2자리 기본."""
        if value is None:
            return "—"
        if self.currency == "USD":
            return f"${value:,.{2 if digits is None else digits}f}"
        return f"{value:,.{0 if digits is None else digits}f}원"

    def money_big(self, value: float | None) -> str:
        """시가총액처럼 큰 금액. 원화는 조원, 달러는 억/조 달러."""
        if value is None:
            return "—"
        if self.currency == "USD":
            if value >= 1e12:
                return f"{value / 1e12:,.2f}조 달러"
            return f"{value / 1e8:,.0f}억 달러"
        return f"{value / 1e12:,.1f}조원"


def _deal_trend_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["date", "close", "foreigner_net", "organ_net", "individual_net"])
    records = []
    for r in rows:
        records.append(
            {
                "date": pd.to_datetime(str(r.get("bizdate", "")), format="%Y%m%d", errors="coerce"),
                "close": to_number(r.get("closePrice")),
                "foreigner_net": to_number(r.get("foreignerPureBuyQuant")),
                "organ_net": to_number(r.get("organPureBuyQuant")),
                "individual_net": to_number(r.get("individualPureBuyQuant")),
                "foreigner_hold_ratio": to_number(r.get("foreignerHoldRatio")),
            }
        )
    df = pd.DataFrame(records).dropna(subset=["date"])
    return df.sort_values("date").reset_index(drop=True)


def parse_snapshot(payload: dict, ref_code: str = "", ref_name: str = "") -> Snapshot:
    payload = payload or {}
    totals = {
        str(t.get("code", "")): t.get("value")
        for t in payload.get("totalInfos", [])
        if t.get("code")
    }

    deals = payload.get("dealTrendInfos") or []
    deal_df = _deal_trend_frame(deals)

    # 현재가는 dealTrendInfos 의 최신 종가. totalInfos 의 lastClosePrice 는 '전일' 종가라 다르다.
    latest = deals[0] if deals else {}
    price = to_number(latest.get("closePrice")) or to_number(totals.get("lastClosePrice"))
    change = to_number(latest.get("compareToPreviousClosePrice"))
    if change is not None and str(latest.get("compareToPreviousPrice", {}).get("name")) == "FALLING":
        change = -abs(change)

    consensus = payload.get("consensusInfo") or {}

    return Snapshot(
        code=str(payload.get("itemCode") or ref_code),
        name=str(payload.get("stockName") or ref_name),
        market_cap=parse_korean_amount(totals.get("marketValue")),
        price=price,
        price_date=str(latest.get("bizdate", "")),
        change=change,
        per_naver=to_number(totals.get("per")),
        eps_naver=to_number(totals.get("eps")),
        cns_per_naver=to_number(totals.get("cnsPer")),
        cns_eps_naver=to_number(totals.get("cnsEps")),
        pbr=to_number(totals.get("pbr")),
        bps=to_number(totals.get("bps")),
        high_52w=to_number(totals.get("highPriceOf52Weeks")),
        low_52w=to_number(totals.get("lowPriceOf52Weeks")),
        foreign_rate=to_number(totals.get("foreignRate")),
        dividend_yield=to_number(totals.get("dividendYieldRatio")),
        target_price=to_number(consensus.get("priceTargetMean")),
        recomm_mean=to_number(consensus.get("recommMean")),
        consensus_date=str(consensus.get("createDate", "")),
        deal_trend=deal_df,
        researches=payload.get("researches") or [],
    )


def company_summary(finance_payload: dict) -> str:
    """기업 개요. integration 이 아니라 finance 응답에 들어 있다."""
    corp = (finance_payload or {}).get("corporationSummary") or {}
    return " ".join(
        str(corp[k]) for k in ("comment1", "comment2", "comment3") if corp.get(k)
    )


def load_all(code: str, name: str = "") -> tuple[Snapshot, FinancialTable, FinancialTable]:
    """한 종목의 요약 + 분기 + 연간 재무를 한 번에."""
    snap = parse_snapshot(naver.integration(code), ref_code=code, ref_name=name)
    quarter_payload = naver.finance(code, "quarter")
    snap.summary = company_summary(quarter_payload)
    quarterly = parse_finance(quarter_payload)
    annual = parse_finance(naver.finance(code, "annual"))
    return snap, quarterly, annual
