"""분석 결과를 담는 자료구조.

핵심 원칙: "값이 없음"은 오류가 아니라 정상적인 결과다.
소형주는 애널리스트 커버리지가 없어 컨센서스가 아예 없고,
적자 기업은 PER 자체가 의미를 갖지 못한다.
그래서 모든 지표는 숫자가 아니라 Metric 으로 감싸서 상태를 함께 들고 다닌다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Status(str, Enum):
    OK = "정상"
    NO_DATA = "데이터없음"      # 원천 데이터가 없다 (예: 컨센서스 미커버 종목)
    NOT_APPLICABLE = "계산불가"  # 데이터는 있으나 지표가 성립하지 않는다 (예: 적자기업 PER)


class Source(str, Enum):
    ACTUAL = "실적확정"    # 발표된 재무제표
    CONSENSUS = "컨센서스"  # 애널리스트 추정치
    DERIVED = "역산추정"    # 연간 컨센서스에서 계산해 뽑아낸 값
    NAVER = "네이버제공"    # 네이버가 직접 계산해 준 값 (교차검증용)


@dataclass(frozen=True)
class Metric:
    """지표 하나. 값과 함께 '믿을 만한 값인지'를 들고 다닌다."""

    value: float | None = None
    status: Status = Status.OK
    source: Source | None = None
    note: str = ""

    @classmethod
    def ok(cls, value: float, source: Source | None = None, note: str = "") -> "Metric":
        return cls(value=value, status=Status.OK, source=source, note=note)

    @classmethod
    def no_data(cls, note: str = "") -> "Metric":
        return cls(value=None, status=Status.NO_DATA, note=note)

    @classmethod
    def na(cls, note: str = "") -> "Metric":
        return cls(value=None, status=Status.NOT_APPLICABLE, note=note)

    @property
    def is_ok(self) -> bool:
        return self.status is Status.OK and self.value is not None

    def text(self, unit: str = "", digits: int = 2) -> str:
        """화면에 그대로 넣을 문자열. 값이 없으면 '—'."""
        if not self.is_ok:
            return "—"
        return f"{self.value:,.{digits}f}{unit}"


class Verdict(str, Enum):
    PASS = "합격"
    FAIL = "불합격"
    UNKNOWN = "판단불가"

    @property
    def badge(self) -> str:
        return {"합격": "🟢", "불합격": "🔴", "판단불가": "⚪"}[self.value]


@dataclass(frozen=True)
class SubCheck:
    """항목 하나를 이루는 세부 조건 (예: C1 분기 EPS 전년동기比 +17% 이상).

    passed 가 None 이면 '자료가 없어 판단불가'다. 세부 조건을 전부 만족해야 항목이 합격이고,
    하나라도 확실히 어긋나면 나머지가 판단불가여도 항목은 불합격이다.
    """

    code: str            # 'C1'
    label: str           # '분기 EPS 전년동기比'
    actual: str          # '+48.2%'
    passed: bool | None

    def __post_init__(self):
        # numpy 비교 결과(np.bool_)가 들어와도 `is False` 판정이 되도록 순수 bool 로 맞춘다
        if self.passed is not None:
            object.__setattr__(self, "passed", bool(self.passed))

    @property
    def mark(self) -> str:
        return {True: "✓", False: "✗", None: "?"}[self.passed]

    @property
    def text(self) -> str:
        return f"{self.code} {self.label} {self.actual} {self.mark}"


def verdict_of(checks: list[SubCheck]) -> Verdict:
    """세부 조건 묶음 → 항목 판정. 확실한 불합격 하나가 판단불가보다 우선한다."""
    if not checks:
        return Verdict.UNKNOWN
    if any(c.passed is False for c in checks):
        return Verdict.FAIL
    if any(c.passed is None for c in checks):
        return Verdict.UNKNOWN
    return Verdict.PASS


@dataclass
class CanslimItem:
    """CANSLIM 7개 항목 중 하나."""

    letter: str          # 'C'
    name: str            # '최근 분기 실적'
    criterion: str       # '분기 EPS 전년동기比 +17% 이상 (2분기 연속) …'
    actual: str          # '+489.6%'
    verdict: Verdict
    evidence: str = ""   # 판정 근거 상세 (서술)
    checks: list[SubCheck] = field(default_factory=list)

    @property
    def checks_text(self) -> str:
        """세부 조건 결과를 한 줄씩. 예: 'C1 … ✓' 다음 줄 'C2 … ✗'."""
        return "\n".join(c.text for c in self.checks)

    @property
    def detail(self) -> str:
        """화면·리포트 '근거' 칸에 넣을 전체 글: 세부 조건 줄들 + 서술."""
        parts = [self.checks_text, self.evidence]
        return "\n".join(p for p in parts if p)


@dataclass
class CanslimResult:
    """종합 판정. 7개 항목을 **모두** 합격해야 'CANSLIM 충족'이다.

    판단불가는 불합격과 구별해서 표시하지만, 충족으로 쳐 주지도 않는다 —
    모르는 것을 틀렸다고 하지 않되, 모르는 채로 통과시키지도 않는다.
    """

    items: list[CanslimItem] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for i in self.items if i.verdict is Verdict.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if i.verdict is Verdict.FAIL)

    @property
    def unknown(self) -> int:
        return sum(1 for i in self.items if i.verdict is Verdict.UNKNOWN)

    @property
    def qualified(self) -> bool:
        return bool(self.items) and all(i.verdict is Verdict.PASS for i in self.items)

    @property
    def tally(self) -> str:
        return f"합격 {self.passed} · 불합격 {self.failed} · 판단불가 {self.unknown}"

    @property
    def summary(self) -> str:
        if self.qualified:
            return "CANSLIM 충족"
        if self.failed == 0 and self.unknown > 0:
            return "미충족 (자료 부족)"
        return "미충족"
