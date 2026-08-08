"""PER / PSR / PEG / ROE 계산 — 현재 주가 기준과 컨센서스 기반 예상치.

핵심은 **롤링 TTM(최근 12개월)** 방식이다.
미래 분기 추정치가 하나 들어오면 가장 오래된 분기 하나를 밀어낸다.

    현재     = 확정된 최근 4개 분기
    Q+1 기준 = 확정 3개 분기 + Q+1 컨센서스
    Q+2 기준 = 확정 2개 분기 + Q+1 컨센서스 + Q+2 역산추정

Q+2 는 네이버가 원본을 주지 않는다. 연간 컨센서스에서 이미 알려진 분기를 빼고
남은 금액을 전년도 같은 분기 비중(계절성)으로 나눠 뽑아낸다. 추정에서 뽑은 추정이므로
반드시 '역산추정'으로 표시한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .fundamentals import FinancialTable, Period, Snapshot
from .models import Metric, Source

EPS = "EPS"
REVENUE = "매출액"
ROE_ROW = "ROE"

QUARTER_MONTHS = (3, 6, 9, 12)

# PEG는 성장률 20~50% 구간을 염두에 두고 만들어진 지표다.
# 성장률이 이보다 극단적으로 크면 PEG가 0에 붙어 아무 정보도 주지 못한다.
PEG_GROWTH_CAP = 100.0


def next_quarter_key(key: str) -> str:
    """'202606' → '202609', '202612' → '202703'."""
    year, month = int(key[:4]), int(key[4:6])
    month += 3
    if month > 12:
        month -= 12
        year += 1
    return f"{year}{month:02d}"


# ------------------------------------------------------------------ 성장률

def cagr(first: float, last: float, years: int) -> float | None:
    """연평균 성장률(%). 시작값이 0 이하면 성장률이 성립하지 않는다."""
    if years <= 0 or first is None or last is None or first <= 0 or last <= 0:
        return None
    return ((last / first) ** (1.0 / years) - 1.0) * 100.0


def yoy(current: float | None, year_ago: float | None) -> float | None:
    """전년동기 대비 증감률(%). 작년이 적자였으면 배수가 성립하지 않는다."""
    if current is None or year_ago is None or year_ago <= 0:
        return None
    return (current / year_ago - 1.0) * 100.0


@dataclass
class GrowthRates:
    quarter_yoy: Metric        # 최근 확정 분기 EPS 전년동기비
    annual_cagr: Metric        # 확정 연간 EPS 연평균 성장률
    annual_cagr_years: int = 0
    forward_annual: Metric = field(default_factory=Metric.no_data)  # 연간 컨센서스 성장률
    prev_quarter_yoy: Metric = field(default_factory=Metric.no_data)  # 가속 여부 확인용
    next_quarter_yoy: Metric = field(default_factory=Metric.no_data)  # 다음 분기 컨센서스 전년동기비
    latest_quarter_label: str = ""     # 최신 확정 분기 (예: '2026.03')
    next_quarter_label: str = ""       # 다음 컨센서스 분기 (예: '2026.06')


def compute_growth(quarterly: FinancialTable, annual: FinancialTable) -> GrowthRates:
    actual_q = [p for p in quarterly.actual_periods() if quarterly.value(EPS, p.key) is not None]

    def q_yoy(idx: int) -> Metric:
        if len(actual_q) <= idx:
            return Metric.no_data("분기 데이터 부족")
        target = actual_q[-(idx + 1)]
        ago_key = f"{target.year - 1}{target.month:02d}"
        now, ago = quarterly.value(EPS, target.key), quarterly.value(EPS, ago_key)
        if ago is None:
            return Metric.no_data("전년 동기 데이터 없음")
        rate = yoy(now, ago)
        if rate is None:
            return Metric.na("전년 동기가 적자라 증감률이 성립하지 않음")
        return Metric.ok(rate, Source.ACTUAL, f"{target.label} vs {target.year-1}.{target.month:02d}")

    actual_years = [
        (p, annual.value(EPS, p.key))
        for p in annual.actual_periods()
        if annual.value(EPS, p.key) is not None
    ]
    if len(actual_years) >= 2:
        span = len(actual_years) - 1
        rate = cagr(actual_years[0][1], actual_years[-1][1], span)
        note = f"{actual_years[0][0].year}→{actual_years[-1][0].year} ({span}년)"
        annual_metric = (
            Metric.ok(rate, Source.ACTUAL, note)
            if rate is not None
            else Metric.na("과거 연간 EPS가 적자라 CAGR이 성립하지 않음")
        )
        years = span
    else:
        annual_metric, years = Metric.no_data("연간 데이터 2개년 미만"), 0

    forward = Metric.no_data("연간 컨센서스 없음")
    cons_years = [p for p in annual.consensus_periods() if annual.value(EPS, p.key) is not None]
    if cons_years and actual_years:
        base, target = actual_years[-1][1], annual.value(EPS, cons_years[0].key)
        rate = yoy(target, base)
        forward = (
            Metric.ok(rate, Source.CONSENSUS, f"{actual_years[-1][0].year}→{cons_years[0].year}")
            if rate is not None
            else Metric.na("직전 연도가 적자라 증감률이 성립하지 않음")
        )

    # 다음 분기(컨센서스) 전년동기비 — 확정 실적이 한 분기 늦게 반영되는 것을 보완하는 참고치
    next_q = Metric.no_data("분기 컨센서스 없음")
    next_label = ""
    cons_q = [p for p in quarterly.consensus_periods() if quarterly.value(EPS, p.key) is not None]
    if cons_q:
        target = cons_q[0]
        next_label = target.label
        ago_key = f"{target.year - 1}{target.month:02d}"
        now, ago = quarterly.value(EPS, target.key), quarterly.value(EPS, ago_key)
        rate = yoy(now, ago)
        if ago is None:
            next_q = Metric.no_data("전년 동기 데이터 없음")
        elif rate is None:
            next_q = Metric.na("전년 동기가 적자라 증감률이 성립하지 않음")
        else:
            next_q = Metric.ok(rate, Source.CONSENSUS,
                               f"{target.label} 컨센서스 vs {target.year - 1}.{target.month:02d}")

    return GrowthRates(
        quarter_yoy=q_yoy(0),
        annual_cagr=annual_metric,
        annual_cagr_years=years,
        forward_annual=forward,
        prev_quarter_yoy=q_yoy(1),
        next_quarter_yoy=next_q,
        latest_quarter_label=actual_q[-1].label if actual_q else "",
        next_quarter_label=next_label,
    )


# ------------------------------------------------------- Q+2 역산 추정

@dataclass
class DerivedQuarter:
    key: str
    values: dict[str, float]
    method: str  # '계절성 가중' 또는 '균등 배분'


def derive_quarter(
    quarterly: FinancialTable, annual: FinancialTable, after_key: str, labels: tuple[str, ...]
) -> DerivedQuarter | None:
    """연간 컨센서스에서 after_key 다음 분기 값을 역산한다."""
    target_key = next_quarter_key(after_key)
    year = int(target_key[:4])

    annual_period = next(
        (p for p in annual.consensus_periods() if p.year == year),
        None,
    )
    if annual_period is None:
        return None

    year_quarters = [f"{year}{m:02d}" for m in QUARTER_MONTHS]
    if target_key not in year_quarters:
        return None  # 12월 결산이 아닌 종목은 역산하지 않는다

    known_keys = [k for k in year_quarters if k <= after_key]
    remaining = [k for k in year_quarters if k > after_key]
    if not remaining:
        return None

    values: dict[str, float] = {}
    method = ""
    for label in labels:
        annual_total = annual.value(label, annual_period.key)
        if annual_total is None:
            continue
        known = [quarterly.value(label, k) for k in known_keys]
        if any(v is None for v in known):
            continue
        rest = annual_total - sum(known)

        # 전년도 같은 분기 비중으로 나눈다. 전년 값이 하나라도 적자/결측이면 균등 배분.
        prior = {k: quarterly.value(label, f"{year - 1}{k[4:]}") for k in remaining}
        if all(v is not None and v > 0 for v in prior.values()) and sum(prior.values()) > 0:
            weight = prior[target_key] / sum(prior.values())
            method = "계절성 가중"
        else:
            weight = 1.0 / len(remaining)
            method = "균등 배분"
        values[label] = rest * weight

    if not values:
        return None
    return DerivedQuarter(key=target_key, values=values, method=method)


# ------------------------------------------------------------- 밸류에이션

@dataclass
class ValuationColumn:
    key: str
    label: str
    source: Source
    note: str = ""
    eps_ttm: Metric = field(default_factory=Metric.no_data)
    revenue_ttm: Metric = field(default_factory=Metric.no_data)  # 원 단위
    per: Metric = field(default_factory=Metric.no_data)
    psr: Metric = field(default_factory=Metric.no_data)
    peg: Metric = field(default_factory=Metric.no_data)
    roe: Metric = field(default_factory=Metric.no_data)


@dataclass
class ValuationResult:
    columns: list[ValuationColumn] = field(default_factory=list)
    growth: GrowthRates | None = None
    derived: DerivedQuarter | None = None
    per_cross_check: str = ""   # 자체 계산 PER vs 네이버 PER


def _per(price: float | None, eps_ttm: float | None) -> Metric:
    if price is None:
        return Metric.no_data("현재가 없음")
    if eps_ttm is None:
        return Metric.no_data("EPS 없음")
    if eps_ttm <= 0:
        return Metric.na("적자 구간이라 PER이 성립하지 않음")
    return Metric.ok(price / eps_ttm)


def _psr(market_cap: float | None, revenue_ttm: float | None) -> Metric:
    if market_cap is None:
        return Metric.no_data("시가총액 없음")
    if revenue_ttm is None or revenue_ttm <= 0:
        return Metric.no_data("매출액 없음")
    return Metric.ok(market_cap / revenue_ttm)


def _peg(per: Metric, growth: Metric) -> Metric:
    if not per.is_ok:
        return Metric.na("PER이 성립하지 않아 PEG도 성립하지 않음")
    if not growth.is_ok:
        return Metric.no_data("성장률을 구할 수 없음")
    if growth.value <= 0:
        return Metric.na("성장률이 0 이하라 PEG가 의미를 갖지 않음")
    if growth.value > PEG_GROWTH_CAP:
        # 예: 성장률 +630%면 PEG가 0.01이 되어 '싸다'가 아니라 '무의미'다
        return Metric.na(f"성장률 {growth.value:+,.0f}%가 극단적이라 PEG가 정보를 주지 못함")
    return Metric.ok(per.value / growth.value)


def _roe_from_eps(eps_ttm: float | None, bps: float | None) -> Metric:
    if eps_ttm is None or not bps:
        return Metric.no_data("BPS 또는 EPS 없음")
    return Metric.ok(eps_ttm / bps * 100.0, Source.DERIVED, "근사값 (EPS ÷ BPS)")


def _sum_or_none(values: list[float | None]) -> float | None:
    return None if any(v is None for v in values) else sum(values)


def compute_valuation(
    snap: Snapshot, quarterly: FinancialTable, annual: FinancialTable
) -> ValuationResult:
    growth = compute_growth(quarterly, annual)
    price, cap, bps = snap.price, snap.market_cap, snap.bps
    unit = quarterly.money_unit  # 매출액 → 통화 기본 단위 배수 (한국 억원=1e8, 미국 달러=1)

    actual = [p for p in quarterly.actual_periods() if quarterly.value(EPS, p.key) is not None]
    actual_keys = [p.key for p in actual]

    def ttm(label: str, keys: list[str], extra: list[float | None]) -> float | None:
        return _sum_or_none([quarterly.value(label, k) for k in keys] + extra)

    columns: list[ValuationColumn] = []

    # ── 현재: 확정 4개 분기 ────────────────────────────────────────────
    cur_keys = actual_keys[-4:]
    cur_eps = ttm(EPS, cur_keys, []) if len(cur_keys) == 4 else None
    cur_rev = ttm(REVENUE, cur_keys, []) if len(cur_keys) == 4 else None
    cur_rev_won = cur_rev * unit if cur_rev is not None else None

    latest_roe = next(
        (quarterly.value(ROE_ROW, p.key) for p in reversed(actual)
         if quarterly.value(ROE_ROW, p.key) is not None),
        None,
    )
    cur_per = _per(price, cur_eps)
    cur_range = ""
    if len(cur_keys) >= 2:
        by_key = {p.key: p for p in actual}
        cur_range = f" ({by_key[cur_keys[0]].label}~{by_key[cur_keys[-1]].label})"
    current = ValuationColumn(
        key="current",
        label="현재",
        source=Source.ACTUAL,
        note=f"확정 실적 {len(cur_keys)}개 분기 합산{cur_range}" if cur_keys else "분기 데이터 부족",
        eps_ttm=Metric.ok(cur_eps, Source.ACTUAL) if cur_eps is not None else Metric.no_data(),
        revenue_ttm=Metric.ok(cur_rev_won, Source.ACTUAL) if cur_rev_won is not None else Metric.no_data(),
        per=cur_per,
        psr=_psr(cap, cur_rev_won),
        peg=_peg(cur_per, growth.annual_cagr),
        roe=(Metric.ok(latest_roe, Source.ACTUAL, "네이버 제공 최신 분기 ROE")
             if latest_roe is not None else Metric.no_data()),
    )
    columns.append(current)

    # ── Q+1: 확정 3개 + 컨센서스 1개 ──────────────────────────────────
    cons_quarters = quarterly.consensus_periods()
    q1 = cons_quarters[0] if cons_quarters else None
    if q1 is not None and len(actual_keys) >= 3:
        q1_eps = quarterly.value(EPS, q1.key)
        q1_rev = quarterly.value(REVENUE, q1.key)
        eps_ttm = ttm(EPS, actual_keys[-3:], [q1_eps])
        rev_ttm = ttm(REVENUE, actual_keys[-3:], [q1_rev])
        rev_won = rev_ttm * unit if rev_ttm is not None else None
        per = _per(price, eps_ttm)
        # 컨센서스 '칸'은 있어도 애널리스트가 없으면 값이 비어 온다. 있는 척하지 않는다.
        covered = q1_eps is not None or q1_rev is not None
        columns.append(
            ValuationColumn(
                key=q1.key,
                label=f"Q+1 ({q1.label})",
                source=Source.CONSENSUS,
                note=("확정 3개 분기 + 컨센서스 1개 분기" if covered
                      else "분기 컨센서스 수치가 없습니다 (애널리스트 미커버)"),
                eps_ttm=Metric.ok(eps_ttm, Source.CONSENSUS) if eps_ttm is not None else Metric.no_data(),
                revenue_ttm=Metric.ok(rev_won, Source.CONSENSUS) if rev_won is not None else Metric.no_data(),
                per=per,
                psr=_psr(cap, rev_won),
                peg=_peg(per, growth.forward_annual),
                roe=_roe_from_eps(eps_ttm, bps),
            )
        )
    else:
        columns.append(
            ValuationColumn(
                key="q1", label="Q+1", source=Source.CONSENSUS,
                note="이 종목은 분기 컨센서스가 없습니다 (애널리스트 미커버)",
            )
        )

    # ── Q+2: 확정 2개 + 컨센서스 2개 ─────────────────────────────────
    # 원본 컨센서스가 두 분기 이상 있으면 그대로 쓴다 (미국 데이터가 이 경우).
    # 하나뿐이면(한국) 연간 컨센서스에서 역산한다.
    derived = None
    q2_cons = cons_quarters[1] if len(cons_quarters) >= 2 else None
    if q2_cons is not None and quarterly.value(EPS, q2_cons.key) is None:
        q2_cons = None  # 칸만 있고 값이 없으면 없는 것
    if q2_cons is None and q1 is not None and len(actual_keys) >= 2:
        derived = derive_quarter(quarterly, annual, q1.key, (EPS, REVENUE))

    if q2_cons is not None and q1 is not None and len(actual_keys) >= 2:
        q2_eps = quarterly.value(EPS, q2_cons.key)
        q2_rev = quarterly.value(REVENUE, q2_cons.key)
        eps_ttm = ttm(EPS, actual_keys[-2:], [quarterly.value(EPS, q1.key), q2_eps])
        rev_ttm = ttm(REVENUE, actual_keys[-2:], [quarterly.value(REVENUE, q1.key), q2_rev])
        rev_won = rev_ttm * unit if rev_ttm is not None else None
        per = _per(price, eps_ttm)
        columns.append(
            ValuationColumn(
                key=q2_cons.key,
                label=f"Q+2 ({q2_cons.label})",
                source=Source.CONSENSUS,
                note="확정 2개 분기 + 컨센서스 2개 분기",
                eps_ttm=Metric.ok(eps_ttm, Source.CONSENSUS) if eps_ttm is not None else Metric.no_data(),
                revenue_ttm=Metric.ok(rev_won, Source.CONSENSUS) if rev_won is not None else Metric.no_data(),
                per=per,
                psr=_psr(cap, rev_won),
                peg=_peg(per, growth.forward_annual),
                roe=_roe_from_eps(eps_ttm, bps),
            )
        )
    elif derived is not None:
        q2_eps = derived.values.get(EPS)
        q2_rev = derived.values.get(REVENUE)
        eps_ttm = ttm(EPS, actual_keys[-2:], [quarterly.value(EPS, q1.key), q2_eps])
        rev_ttm = ttm(REVENUE, actual_keys[-2:], [quarterly.value(REVENUE, q1.key), q2_rev])
        rev_won = rev_ttm * unit if rev_ttm is not None else None
        per = _per(price, eps_ttm)
        label_period = f"{derived.key[:4]}.{derived.key[4:]}"
        columns.append(
            ValuationColumn(
                key=derived.key,
                label=f"Q+2 ({label_period})",
                source=Source.DERIVED,
                note=f"연간 컨센서스에서 역산 · {derived.method}",
                eps_ttm=Metric.ok(eps_ttm, Source.DERIVED) if eps_ttm is not None else Metric.no_data(),
                revenue_ttm=Metric.ok(rev_won, Source.DERIVED) if rev_won is not None else Metric.no_data(),
                per=per,
                psr=_psr(cap, rev_won),
                peg=_peg(per, growth.forward_annual),
                roe=_roe_from_eps(eps_ttm, bps),
            )
        )
    else:
        columns.append(
            ValuationColumn(
                key="q2", label="Q+2", source=Source.DERIVED,
                note="연간 컨센서스가 없어 역산할 수 없습니다",
            )
        )

    # ── 12개월 선행: 당해 연간 컨센서스 ──────────────────────────────
    cons_years = annual.consensus_periods()
    if cons_years:
        cy = cons_years[0]
        eps_y = annual.value(EPS, cy.key)
        rev_y = annual.value(REVENUE, cy.key)
        rev_won = rev_y * annual.money_unit if rev_y is not None else None
        per = _per(price, eps_y)
        roe_y = annual.value(ROE_ROW, cy.key)
        covered_y = eps_y is not None or rev_y is not None
        columns.append(
            ValuationColumn(
                key=cy.key,
                label=f"연간 선행 ({cy.year}년)",
                source=Source.CONSENSUS,
                note=(f"{cy.year}년 연간 컨센서스" if covered_y
                      else f"{cy.year}년 연간 컨센서스 수치가 없습니다 (애널리스트 미커버)"),
                eps_ttm=Metric.ok(eps_y, Source.CONSENSUS) if eps_y is not None else Metric.no_data(),
                revenue_ttm=Metric.ok(rev_won, Source.CONSENSUS) if rev_won is not None else Metric.no_data(),
                per=per,
                psr=_psr(cap, rev_won),
                peg=_peg(per, growth.forward_annual),
                roe=(Metric.ok(roe_y, Source.CONSENSUS) if roe_y is not None
                     else _roe_from_eps(eps_y, bps)),
            )
        )
    else:
        columns.append(
            ValuationColumn(
                key="fy", label="연간 선행", source=Source.CONSENSUS,
                note="연간 컨센서스가 없습니다",
            )
        )

    # ── 교차검증: 우리 계산이 원본 제공값과 맞는가 ───────────────────
    check = "비교 불가"
    if current.per.is_ok and snap.per_naver:
        diff = current.per.value - snap.per_naver
        mark = "일치" if abs(diff) < 0.15 else "차이 있음"
        check = f"자체계산 {current.per.value:.2f}배 / {snap.source_name} {snap.per_naver:.2f}배 → {mark}"

    return ValuationResult(
        columns=columns, growth=growth, derived=derived, per_cross_check=check
    )
