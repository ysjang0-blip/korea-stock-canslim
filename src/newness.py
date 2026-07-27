"""CANSLIM 의 N — 'New' 를 판정하기 위한 재료 추출.

오닐의 N 은 신고가 하나가 아니다. **New product, New service, New management,
New industry condition, New price high** 를 모두 가리킨다.
주가가 신고가로 올라서는 '결과'보다, 그렇게 만든 '새로운 무언가'가 본질이다.

주가는 숫자라 자동으로 재지만 '새로운 무언가'는 글이다.
그래서 공시 제목·뉴스 제목·증권사 리포트 제목을 키워드로 분류한다.

한계는 분명하다. 키워드 매칭은 사람의 판단을 대신하지 못한다.
그래서 점수를 매기지 않고 **찾은 근거를 그대로 보여주어 사용자가 직접 읽고 판단**하게 한다.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from dataclasses import dataclass, field

# 먼저 걸러낼 것 — 새로운 재료가 아니거나 오히려 악재인 공시
NOISE = (
    "풍문", "해명", "조회공시", "불성실공시", "관리종목", "투자주의", "투자경고", "투자위험",
    "가격제한폭", "상장폐지", "감사의견", "소송", "횡령", "배임", "부도", "회생절차",
    "자기주식 처분", "자기주식처분", "정정", "기재정정", "특정증권등 소유상황",
    "주식등의 대량보유", "결산실적공시", "매출액또는손익구조",
)

# (분류 이름, 키워드들) — 순서대로 검사한다
CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("신제품·신사업", (
        "신제품", "신규 사업", "신규사업", "사업목적", "사업 목적", "출시", "런칭", "론칭",
        "개발 완료", "개발완료", "신규 브랜드", "진출", "양산", "상용화",
    )),
    ("수주·공급계약", (
        "단일판매", "공급계약", "수주", "계약 체결", "계약체결", "납품", "공급 계약",
    )),
    ("설비투자·증설", (
        "시설투자", "신규 시설", "증설", "신공장", "유형자산 취득", "생산능력",
    )),
    ("인수·합병", (
        "타법인 주식", "출자증권 취득", "합병", "영업양수", "영업 양수", "인수", "분할",
        "지분 취득", "자회사 편입",
    )),
    ("경영진 변경", (
        "대표이사 변경", "대표이사변경", "최대주주 변경", "최대주주변경", "임원 변경",
        "경영권", "각자대표", "신규 선임",
    )),
    ("인허가·기술", (
        "임상", "품목허가", "승인", "인증", "특허", "국책과제", "기술이전", "라이선스",
    )),
    ("자사주 매입", (
        "자기주식 취득", "자기주식취득", "자사주 매입",
    )),
)

_DATE_RE = re.compile(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})")
_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

# 같은 사건을 여러 매체가 조금씩 다르게 쓴 기사를 하나로 본다.
# 단어가 아니라 '글자 두 개씩' 겹치는 비율로 잰다. 단어로 재면 '핵심 소재'와 '핵심소재',
# '두산에너빌'과 '두산에너빌리티' 처럼 띄어쓰기·표기만 다른 같은 사건을 놓친다.
SIMILARITY_THRESHOLD = 0.6


def clean_title(raw) -> str:
    """HTML 이스케이프(&amp; 등)를 풀고 공백을 정리한다."""
    return re.sub(r"\s+", " ", html.unescape(str(raw or ""))).strip()


def _bigrams(title: str) -> set[str]:
    """제목에서 기호·공백을 뺀 뒤 이어지는 글자 두 개씩 뽑는다."""
    flat = "".join(_TOKEN_RE.findall(title))
    if len(flat) < 2:
        return set()
    return {flat[i:i + 2] for i in range(len(flat) - 1)}


def _similar(a: str, b: str) -> bool:
    """두 제목이 같은 사건을 말하는지. 글자 두 개씩 겹치는 비율로 본다."""
    ba, bb = _bigrams(a), _bigrams(b)
    if not ba or not bb:
        return False
    return len(ba & bb) / len(ba | bb) >= SIMILARITY_THRESHOLD


@dataclass
class NewsItem:
    category: str
    title: str
    date: dt.date | None
    source: str  # '공시' / '뉴스' / '리포트'

    @property
    def date_text(self) -> str:
        return self.date.strftime("%Y-%m-%d") if self.date else "날짜미상"


@dataclass
class Newness:
    """찾아낸 '새로운 재료'."""

    items: list[NewsItem] = field(default_factory=list)
    scanned: int = 0          # 훑어본 제목 수
    window_days: int = 180
    available: bool = True    # 원천 데이터를 받아왔는지

    @property
    def found(self) -> bool:
        return bool(self.items)

    @property
    def categories(self) -> list[str]:
        seen: list[str] = []
        for item in self.items:
            if item.category not in seen:
                seen.append(item.category)
        return seen

    def top(self, count: int = 3) -> list[NewsItem]:
        return sorted(
            self.items, key=lambda i: i.date or dt.date.min, reverse=True
        )[:count]


def parse_date(raw) -> dt.date | None:
    if not raw:
        return None
    match = _DATE_RE.search(str(raw))
    if not match:
        return None
    try:
        return dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def classify(title: str) -> str | None:
    """제목 하나를 분류한다. 잡음이거나 해당 없으면 None."""
    if not title:
        return None
    text = title.replace(" ", "")
    if any(noise.replace(" ", "") in text for noise in NOISE):
        return None
    for name, keywords in CATEGORIES:
        if any(keyword.replace(" ", "") in text for keyword in keywords):
            return name
    return None


def _collect(rows, title_key, date_key, source: str, cutoff: dt.date | None) -> list[NewsItem]:
    found = []
    for row in rows or []:
        title = clean_title((row or {}).get(title_key))
        category = classify(title)
        if not category:
            continue
        date = parse_date((row or {}).get(date_key))
        if cutoff and date and date < cutoff:
            continue
        found.append(NewsItem(category=category, title=title, date=date, source=source))
    return found


def dedupe(items: list[NewsItem]) -> list[NewsItem]:
    """같은 사건을 다룬 기사는 하나만 남긴다.

    '두산에너빌, 中 라이양 원전 5·6호기 핵심소재 공급 계약' 과
    '두산에너빌리티, 중국 라이양 원전 5∙6호기 핵심부품 공급 계약' 은 같은 사건이다.
    공시를 뉴스보다 먼저 두어, 겹치면 공시 쪽이 남게 한다.
    """
    priority = {"공시": 0, "리포트": 1, "뉴스": 2}
    ordered = sorted(
        items,
        key=lambda i: (priority.get(i.source, 3), -(i.date or dt.date.min).toordinal()),
    )
    kept: list[NewsItem] = []
    for item in ordered:
        if not any(_similar(item.title, k.title) for k in kept):
            kept.append(item)
    # 화면에는 최신순으로 보여준다
    return sorted(kept, key=lambda i: i.date or dt.date.min, reverse=True)


def detect(
    disclosures: list | None,
    articles: list | None,
    researches: list | None,
    window_days: int = 180,
    today: dt.date | None = None,
) -> Newness:
    """공시·뉴스·리포트 제목에서 '새로운 재료'를 찾는다."""
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=window_days)

    rows = [
        (disclosures, "title", "datetime", "공시"),
        (articles, "title", "datetime", "뉴스"),
        (researches, "tit", "wdt", "리포트"),
    ]
    items: list[NewsItem] = []
    scanned = 0
    for data, title_key, date_key, source in rows:
        scanned += len(data or [])
        items.extend(_collect(data, title_key, date_key, source, cutoff))

    return Newness(
        items=dedupe(items),
        scanned=scanned,
        window_days=window_days,
        available=scanned > 0,
    )


def load(code: str, researches: list | None = None, window_days: int = 180) -> Newness:
    """네트워크에서 받아와 판정까지. 실패해도 예외를 던지지 않는다 (N 은 보조 근거)."""
    from . import naver

    def safe(fn, *args):
        try:
            return fn(*args)
        except Exception:
            return []

    return detect(
        disclosures=safe(naver.disclosures, code),
        articles=safe(naver.news, code),
        researches=researches or [],
        window_days=window_days,
    )
