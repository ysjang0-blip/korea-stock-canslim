"""차트 생성 테스트 — 렌더링 사고를 막는 회귀 테스트."""

import pytest

from src import charts
from src.fundamentals import parse_finance
from src.models import Source
from tests.conftest import (
    SAMSUNG_Q_EPS, SAMSUNG_Q_PERIODS, SAMSUNG_Q_REVENUE, make_finance, make_ohlcv,
)


@pytest.fixture
def quarter_table():
    return parse_finance(make_finance(
        SAMSUNG_Q_PERIODS, {"EPS": SAMSUNG_Q_EPS, "매출액": SAMSUNG_Q_REVENUE}))


class Test주가차트:
    def test_단일계열이라_범례를_달지_않는다(self):
        fig = charts.price_chart(make_ohlcv([100.0] * 10), 120.0, 80.0)
        assert len(fig.data) == 1
        assert fig.layout.showlegend is False

    def test_52주_라벨은_그림_안쪽_선_위에_붙인다(self):
        """바깥(right)이면 오른쪽 여백에서 잘리고, 아래(bottom)면 x축과 겹친다."""
        fig = charts.price_chart(make_ohlcv([100.0] * 10), 120.0, 80.0)
        notes = fig.layout.annotations
        assert len(notes) == 2
        assert all("52주" in a.text and "원" in a.text for a in notes)
        assert all(a.xanchor == "left" for a in notes)   # 왼쪽 안쪽에 정렬
        assert all(a.yanchor == "bottom" for a in notes)  # 선 위에 얹는다
        assert all(a.bgcolor == charts.C["surface"] for a in notes)  # 선과 겹쳐도 읽힌다

    def test_52주_값이_없으면_선을_긋지_않는다(self):
        fig = charts.price_chart(make_ohlcv([100.0] * 10), None, None)
        assert len(fig.layout.annotations) == 0


class Test실적차트:
    def test_x축은_반드시_범주형이다(self, quarter_table):
        """'2025.03' 을 숫자로 읽으면 막대가 엉뚱한 위치로 흩어진다."""
        fig = charts.earnings_chart(quarter_table, None, None, "EPS")
        assert fig.layout.xaxis.type == "category"

    def test_출처별로_계열을_나누고_범례를_단다(self, quarter_table):
        fig = charts.earnings_chart(quarter_table, "202609", 11145.0, "EPS")
        assert [t.name for t in fig.data] == ["실적확정", "컨센서스", "역산추정"]
        assert fig.layout.showlegend is True

    def test_출처마다_정해진_색을_쓴다(self, quarter_table):
        fig = charts.earnings_chart(quarter_table, "202609", 11145.0, "EPS")
        colors = {t.name: t.marker.color for t in fig.data}
        assert colors["실적확정"] == charts.SOURCE_COLOR[Source.ACTUAL]
        assert colors["컨센서스"] == charts.SOURCE_COLOR[Source.CONSENSUS]
        assert colors["역산추정"] == charts.SOURCE_COLOR[Source.DERIVED]

    def test_막대들이_같은_슬롯을_공유한다(self, quarter_table):
        """offsetgroup 이 다르면 분기마다 막대가 좌우로 밀린다."""
        fig = charts.earnings_chart(quarter_table, "202609", 11145.0, "EPS")
        assert {t.offsetgroup for t in fig.data} == {"q"}

    def test_역산값이_없으면_역산_계열도_없다(self, quarter_table):
        fig = charts.earnings_chart(quarter_table, None, None, "EPS")
        assert "역산추정" not in [t.name for t in fig.data]

    def test_데이터가_없어도_죽지_않는다(self):
        fig = charts.earnings_chart(parse_finance({}), None, None, "EPS")
        assert len(fig.data) == 0


class Test상대차트:
    def test_두_계열을_100으로_맞춰_비교한다(self):
        stock = make_ohlcv([100.0 + i for i in range(300)])
        index = make_ohlcv([200.0 + i for i in range(300)])
        fig = charts.relative_chart(stock, index, "KOSPI", "삼성전자")
        assert [t.name for t in fig.data] == ["삼성전자", "KOSPI"]
        assert all(t.y[0] == pytest.approx(100.0) for t in fig.data)

    def test_이중축을_쓰지_않는다(self):
        stock = make_ohlcv([100.0 + i for i in range(300)])
        fig = charts.relative_chart(stock, stock, "KOSPI", "종목")
        assert all(t.yaxis in (None, "y") for t in fig.data)

    def test_데이터가_한_줄이면_그리지_않는다(self):
        fig = charts.relative_chart(make_ohlcv([100.0]), make_ohlcv([100.0]), "KOSPI", "종목")
        assert len(fig.data) == 0
