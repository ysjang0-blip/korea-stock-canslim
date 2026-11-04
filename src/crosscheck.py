"""분기 EPS 교차검증 — 공식 공시 출처(미국 SEC EDGAR, 한국 DART)와 재무표 EPS 를 맞춰 본다.

판정을 바꾸지 않는다. 앱이 쓰는 분기 EPS(네이버·야후)가 공시 원본과 같은지만 확인해서
데이터 검증 표의 신뢰도 등급(🟡 단일 → 🟢 확인)에 반영한다. 그래서 출처가 막히거나 키가 없어도
분석은 그대로 돌아가고, 검증 표에 "교차검증 못 함"이라는 사실만 남는다.

비교는 두 출처가 **같은 분기 키로 겹치는 분기**에서만 한다. EPS 정의(기본/희석)나 주식분할 반영
시점이 출처마다 달라 소수 오차가 생기므로 상대 5% 또는 절대 오차 하한 안이면 같다고 본다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .fundamentals import FinancialTable
from .valuation import EPS

REL_TOLERANCE = 0.05     # 상대 오차
MIN_OVERLAP = 2          # 이만큼은 겹쳐야 '확인'이라 부른다


@dataclass
class CrossCheck:
    ok: bool | None          # True 일치 / False 불일치 / None 판단 불가(출처 없음·겹침 부족)
    source: str = ""         # 'SEC EDGAR' · 'DART'
    compared: int = 0
    matched: int = 0
    note: str = ""
    mismatches: list[str] = field(default_factory=list)


def unavailable(source: str, why: str) -> CrossCheck:
    return CrossCheck(None, source=source, note=f"{source} 교차검증을 하지 못했습니다 — {why}")


def compare(quarterly: FinancialTable, other: dict[str, float], source: str,
            abs_floor: float, unit: str = "") -> CrossCheck:
    """재무표의 확정 분기 EPS 와 공시 출처 EPS 를 같은 분기끼리 비교한다.

    abs_floor: 이 값 이하의 차이는 반올림 오차로 본다 (달러 0.02, 원 1)."""
    mine = {p.key: quarterly.value(EPS, p.key) for p in quarterly.actual_periods()}
    mine = {k: v for k, v in mine.items() if v is not None}
    keys = sorted(k for k in mine if k in other)
    if len(keys) < MIN_OVERLAP:
        return unavailable(source, f"겹치는 분기가 {len(keys)}개뿐입니다")

    bad: list[str] = []
    for k in keys:
        a, b = mine[k], other[k]
        diff = abs(a - b)
        if diff <= abs_floor or diff <= REL_TOLERANCE * max(abs(a), abs(b)):
            continue
        bad.append(f"{k[:4]}.{k[4:]} 표 {a:,.2f}{unit} vs {source} {b:,.2f}{unit}")

    matched = len(keys) - len(bad)
    if bad:
        return CrossCheck(False, source, len(keys), matched, mismatches=bad, note=(
            f"{source} 공시와 {len(bad)}개 분기가 다릅니다 ({'; '.join(bad)}) — "
            "EPS 정의(기본/희석)나 주식분할 반영 시점 차이일 수 있습니다"))
    return CrossCheck(True, source, len(keys), matched, note=(
        f"{source} 공시 EPS 와 겹치는 {len(keys)}개 분기가 모두 일치합니다"))
