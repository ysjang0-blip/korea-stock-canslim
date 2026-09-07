"""사업부문별 매출 구성 파싱(src/segments.py) 테스트.

fixture HTML은 네이버 종목분석(WiseReport) 기업개요 페이지(c1020001)의 실제 구조를
그대로 줄인 것이다 — 빈 채움 줄, 음수 '기타', 기간 표기까지 포함.
"""

from __future__ import annotations

from src import segments
from src.segments import SegmentBreakdown, SegmentShare


def make_page(rows_html: str, period: str = "2026 / 03") -> str:
    return f"""
    <html><body>
    <table id="cTB203" class="gHead fl_le" summary="주요제품의 매출구성">
      <caption class="blind">주요제품 매출구성</caption>
      <thead><tr><th scope="col">제품명</th><th scope="col">구성비</th></tr></thead>
      <tbody>
        {rows_html}
        <tr><th scope="row" class="c1 txt ">&nbsp;</th><td class="c2 num ">&nbsp;</td></tr>
        <tr><th scope="row" class="c1 txt noline-bottom">&nbsp;</th>
            <td class="c2 num noline-bottom">&nbsp;</td></tr>
      </tbody>
    </table>
    <h6 class="spanCT">주요제품 매출구성({period})</h6>
    </body></html>
    """


def row(name: str, pct: str) -> str:
    return (f'<tr><th scope="row" class="c1 txt " title="{name}">'
            f'<span class="cut">{name}</span></th>'
            f'<td class="c2 num ">{pct}</td></tr>')


SAMSUNG_PAGE = make_page(
    row("DS", "61.04") + row("DX", "39.33") + row("SDC", "5.00")
    + row("Harman", "2.86") + row("기타", "-8.23")
)


class Test파싱:
    def test_부문과_비중을_큰_순서로(self):
        got = segments.parse_segments(SAMSUNG_PAGE)
        assert got is not None
        assert [s.name for s in got.items] == ["DS", "DX", "SDC", "Harman", "기타"]
        assert got.items[0].share_pct == 61.04
        assert got.top.name == "DS"

    def test_음수_기타도_그대로_담는다(self):
        got = segments.parse_segments(SAMSUNG_PAGE)
        assert got.items[-1] == SegmentShare(name="기타", share_pct=-8.23)

    def test_빈_채움_줄은_건너뛴다(self):
        got = segments.parse_segments(SAMSUNG_PAGE)
        assert len(got.items) == 5

    def test_기준_시점(self):
        assert segments.parse_segments(SAMSUNG_PAGE).period_label == "2026/03"

    def test_기준_시점이_없어도_동작(self):
        page = SAMSUNG_PAGE.replace("주요제품 매출구성(2026 / 03)", "주요제품 매출구성")
        got = segments.parse_segments(page)
        assert got is not None
        assert got.period_label == ""

    def test_정렬은_입력_순서와_무관(self):
        page = make_page(row("작은부문", "3.5") + row("큰부문", "96.5"))
        got = segments.parse_segments(page)
        assert [s.name for s in got.items] == ["큰부문", "작은부문"]

    def test_HTML_엔티티가_들어간_이름(self):
        page = make_page(row("반도체 &amp; 부품", "100.00"))
        got = segments.parse_segments(page)
        assert got.items[0].name == "반도체 & 부품"

    def test_span_없이_th에_바로_이름이_있어도(self):
        page = make_page(
            '<tr><th scope="row" class="c1 txt ">이동통신</th>'
            '<td class="c2 num ">100.00</td></tr>'
        )
        got = segments.parse_segments(page)
        assert got.items[0].name == "이동통신"

    def test_천단위_쉼표가_있는_비중(self):
        page = make_page(row("본업", "1,234.56"))
        assert segments.parse_segments(page).items[0].share_pct == 1234.56


class Test없는경우:
    def test_표_자체가_없으면_None(self):
        assert segments.parse_segments("<html><body>다른 페이지</body></html>") is None

    def test_표가_비어_있으면_None(self):
        assert segments.parse_segments(make_page("")) is None

    def test_숫자가_아닌_비중은_건너뛴다(self):
        page = make_page(row("본업", "해당없음"))
        assert segments.parse_segments(page) is None

    def test_네트워크_실패는_None(self, monkeypatch):
        def boom(url, ttl):
            raise RuntimeError("연결 실패")
        monkeypatch.setattr(segments.naver, "fetch_text", boom)
        assert segments.load("005930") is None


SAMSUNG_SUMMARY = (
    "동사는 1969년 설립된 글로벌 전자 기업으로, DX, DS, SDC, Harman 산하 308개 종속기업으로 구성됨. "
    "DX 부문은 TV, 가전, 스마트폰, DS는 메모리 반도체와 Foundry 사업, SDC는 OLED 패널, "
    "Harman은 전장부품·오디오 사업 운영함. "
    "동사는 AI 기술 확대, 선단 공정 개발, 고부가 솔루션 포트폴리오로 제품 차별화에 주력하고 있음."
)


class Test설명추출:
    def test_삼성전자_문체에서_부문별_설명을_잘라낸다(self):
        got = segments.describe_items(["DS", "DX", "SDC", "Harman", "기타"], SAMSUNG_SUMMARY)
        assert got["DX"] == "TV, 가전, 스마트폰"
        assert got["DS"] == "메모리 반도체와 Foundry 사업"
        assert got["SDC"] == "OLED 패널"
        assert got["Harman"] == "전장부품·오디오 사업 운영함."

    def test_조사_없이_스친_언급은_설명이_아니다(self):
        # 첫 문장의 "DX, DS, SDC, Harman 산하 ..."에서 잘못 뽑으면 안 된다
        got = segments.describe_items(["Harman"], SAMSUNG_SUMMARY)
        assert "산하" not in got["Harman"]

    def test_기타는_설명을_찾지_않는다(self):
        assert "기타" not in segments.describe_items(["기타"], SAMSUNG_SUMMARY)

    def test_개요에_없는_이름은_빈_결과(self):
        assert segments.describe_items(["차량"], SAMSUNG_SUMMARY) == {}

    def test_괄호_붙은_이름도_찾는다(self):
        text = "에코프로비엠은 이차전지 양극재 사업 운영함."
        got = segments.describe_items(["에코프로비엠 (연결)"], text)
        assert got["에코프로비엠 (연결)"] == "이차전지 양극재 사업 운영함."

    def test_빈_개요면_빈_결과(self):
        assert segments.describe_items(["DS"], "") == {}

    def test_load가_설명을_붙인다(self, monkeypatch):
        monkeypatch.setattr(segments.naver, "fetch_text", lambda url, ttl: SAMSUNG_PAGE)
        got = segments.load("005930", summary=SAMSUNG_SUMMARY)
        by_name = {s.name: s for s in got.items}
        assert by_name["DS"].description == "메모리 반도체와 Foundry 사업"
        assert by_name["기타"].description == ""

    def test_load에_summary가_없어도_동작(self, monkeypatch):
        monkeypatch.setattr(segments.naver, "fetch_text", lambda url, ttl: SAMSUNG_PAGE)
        got = segments.load("005930")
        assert all(s.description == "" for s in got.items)


class Test금액표시:
    def test_조원(self):
        assert segments.amount_text(184.3e12) == "184.3조원"

    def test_억원(self):
        assert segments.amount_text(3_500e8) == "3,500억원"

    def test_없으면_대시(self):
        assert segments.amount_text(None) == "—"

    def test_음수도_절대값으로_단위를_고른다(self):
        assert segments.amount_text(-2.5e12) == "-2.5조원"


class Test데이터모델:
    def test_불변(self):
        b = SegmentBreakdown(period_label="2026/03",
                             items=(SegmentShare(name="A", share_pct=100.0),))
        try:
            b.items[0].name = "B"  # type: ignore[misc]
            raise AssertionError("frozen 이어야 한다")
        except AttributeError:
            pass
