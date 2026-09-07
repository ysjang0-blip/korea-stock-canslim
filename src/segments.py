"""사업부문별 매출 구성 — 네이버 종목분석(WiseReport) 기업개요 페이지에서 추출.

한국 종목 전용이다. 페이지의 '주요제품 매출구성' 표를 파싱해 부문 이름과 매출 비중(%)을 얻는다.
알아둘 점:
  * 출처가 주는 것은 **비중(%)뿐**이다. 금액은 '최근 연간 매출 x 비중'으로 계산한 추정치다.
  * 내부거래 조정 때문에 '기타'가 음수이거나 비중 합계가 100%와 다를 수 있다 (예: 삼성전자).
  * 부문별 이익률·출시일은 어떤 무료 출처도 주지 않으므로 다루지 않는다.
  * 미국(야후)은 부문별 매출 자료 자체가 없어 이 모듈을 쓰지 않는다.
"""

from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass

from . import naver

PAGE_URL = "https://navercomp.wisereport.co.kr/v2/company/c1020001.aspx?cmp_cd={code}"
TTL = 24 * 60 * 60  # 매출구성은 분기에 한 번 바뀌는 정보라 24시간 캐시면 충분

# 표 한 줄: <th scope="row" ...><span class="cut">이름</span></th> ... <td class="c2 num ">61.04</td>
_ROW_RE = re.compile(
    r'<th scope="row"[^>]*>\s*(?:<span[^>]*>)?(.*?)(?:</span>)?\s*</th>\s*'
    r'<td class="c2 num[^"]*">([^<]+)</td>',
    re.S,
)
_TABLE_RE = re.compile(r'<table id="cTB203".*?</table>', re.S)
_PERIOD_RE = re.compile(r"매출구성\s*\(\s*(\d{4})\s*/\s*(\d{2})\s*\)")


@dataclass(frozen=True)
class SegmentShare:
    name: str        # 부문 이름 (회사가 공시에 쓰는 명칭 그대로. 예: DS, DX, Harman)
    share_pct: float  # 매출 비중 %. 내부거래 조정 항목은 음수일 수 있다


@dataclass(frozen=True)
class SegmentBreakdown:
    period_label: str                  # 기준 시점. 예: "2026/03"
    items: tuple[SegmentShare, ...]    # 비중이 큰 순서로 정렬되어 있다

    @property
    def top(self) -> SegmentShare:
        return self.items[0]


def amount_text(value_won: float | None) -> str:
    """원 단위 금액을 조원/억원으로. 부문 추정 매출액 표시에 쓴다 (한국 전용이라 원화만)."""
    if value_won is None:
        return "—"
    if abs(value_won) >= 1e12:
        return f"{value_won / 1e12:,.1f}조원"
    return f"{value_won / 1e8:,.0f}억원"


def parse_segments(page_html: str) -> SegmentBreakdown | None:
    """기업개요 페이지 HTML에서 매출구성 표를 뽑는다. 표가 없거나 비어 있으면 None."""
    table = _TABLE_RE.search(page_html)
    if not table:
        return None

    items: list[SegmentShare] = []
    for raw_name, raw_pct in _ROW_RE.findall(table.group(0)):
        name = html_mod.unescape(re.sub(r"<[^>]+>", "", raw_name)).replace("\xa0", " ").strip()
        pct_text = html_mod.unescape(raw_pct).replace("\xa0", " ").strip()
        if not name:  # 표를 채우는 빈 줄
            continue
        try:
            pct = float(pct_text.replace(",", ""))
        except ValueError:
            continue
        items.append(SegmentShare(name=name, share_pct=pct))

    if not items:
        return None

    period = _PERIOD_RE.search(page_html)
    label = f"{period.group(1)}/{period.group(2)}" if period else ""
    items.sort(key=lambda s: s.share_pct, reverse=True)
    return SegmentBreakdown(period_label=label, items=tuple(items))


def load(code: str) -> SegmentBreakdown | None:
    """종목코드로 매출구성을 받아온다. 부가 정보라 어떤 실패도 분석 전체를 막지 않는다 (None)."""
    try:
        return parse_segments(naver.fetch_text(PAGE_URL.format(code=code), ttl=TTL))
    except Exception:
        return None
