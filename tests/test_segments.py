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
