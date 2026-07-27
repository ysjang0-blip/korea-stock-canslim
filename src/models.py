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


@dataclass
class CanslimItem:
    """CANSLIM 7개 항목 중 하나."""

    letter: str          # 'C'
    name: str            # '최근 분기 실적'
    criterion: str       # '분기 EPS 전년동기比 +25% 이상'
    actual: str          # '+489.6%'
    verdict: Verdict
    evidence: str = ""   # 판정 근거 상세


@dataclass
class CanslimResult:
    items: list[CanslimItem] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for i in self.items if i.verdict is Verdict.PASS)

    @property
    def judged(self) -> int:
        """판단 가능했던 항목 수. 판단불가는 분모에서 뺀다 (0점 처리하지 않는다)."""
        return sum(1 for i in self.items if i.verdict is not Verdict.UNKNOWN)

    @property
    def summary(self) -> str:
        if self.judged == 0:
            return "판정 불가"
        return f"{self.passed} / {self.judged} 통과"
