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

    def test_기간을_바꾸면_그만큼만_그린다(self):
        """3개월(63일)·6개월(126일) 전환 — 화면 라디오가 넘기는 days 값."""
        stock = make_ohlcv([100.0 + i for i in range(300)])
        index = make_ohlcv([200.0 + i for i in range(300)])
        for days in (63, 126):
            fig = charts.relative_chart(stock, index, "KOSPI", "종목", days=days)
            assert all(len(t.y) == days for t in fig.data)
            # 어느 기간이든 시작점은 100으로 다시 맞춘다
            assert all(t.y[0] == pytest.approx(100.0) for t in fig.data)


class Test기술적차트:
    def _fig(self, ma_windows=(20, 50, 200)):
        df = make_ohlcv([100.0 + (i % 7) + i * 0.1 for i in range(300)])
        return charts.technical_chart(df, 120.0, 80.0, ma_windows=ma_windows)

    def test_3단_구성이다(self):
        """주가(y), RSI(y2), %B(y3) — 이중축이 아니라 분리된 패널."""
        fig = self._fig()
        axes = {t.yaxis for t in fig.data}
        assert axes == {"y", "y2", "y3"}

    def test_계열_이름이_전부_있다(self):
        names = [t.name for t in self._fig().data]
        for expected in ("종가", "MA 20", "MA 50", "MA 200", "RSI(14)", "RSI MA(14)", "%B"):
            assert expected in names

    def test_이동평균_기간을_바꾸면_계열도_바뀐다(self):
        names = [t.name for t in self._fig(ma_windows=(5, 60)).data]
        assert "MA 5" in names and "MA 60" in names
        assert "MA 200" not in names

    def test_RSI_축은_0에서_100으로_고정(self):
        fig = self._fig()
        assert list(fig.layout.yaxis2.range) == [0, 100]

    def test_빈_데이터도_죽지_않는다(self):
        import pandas as pd
        empty = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
        fig = charts.technical_chart(empty, None, None)
        assert fig is not None


class Test실적QoQ:
    def test_막대_라벨에_QoQ가_병기된다(self, quarter_table):
        """202603 EPS 6,993 vs 202512 2,864 → +144.2% (손계산)."""
        fig = charts.earnings_chart(quarter_table, None, None, "EPS")
        actual = next(t for t in fig.data if t.name == "실적확정")
        by_x = dict(zip(actual.x, actual.text))
        assert by_x["2026.03"] == "6,993<br>+144.2%"

    def test_첫_분기에는_QoQ_줄이_없다(self, quarter_table):
        fig = charts.earnings_chart(quarter_table, None, None, "EPS")
        actual = next(t for t in fig.data if t.name == "실적확정")
        by_x = dict(zip(actual.x, actual.text))
        assert by_x["2025.03"] == "1,186"  # 직전 분기가 없어 값만

    def test_역산_분기의_QoQ는_컨센서스_대비다(self, quarter_table):
        """Q+2 11,145 vs Q+1 컨센서스 10,625 → +4.9%."""
        fig = charts.earnings_chart(quarter_table, "202609", 11145.0, "EPS")
        derived = next(t for t in fig.data if t.name == "역산추정")
        assert derived.text[0] == "11,145<br>+4.9%"

    def test_직전_분기가_적자면_QoQ를_붙이지_않는다(self):
        eps = dict(SAMSUNG_Q_EPS, **{"202512": "-500"})
        table = parse_finance(make_finance(SAMSUNG_Q_PERIODS, {"EPS": eps}))
        fig = charts.earnings_chart(table, None, None, "EPS")
        actual = next(t for t in fig.data if t.name == "실적확정")
        by_x = dict(zip(actual.x, actual.text))
        assert by_x["2026.03"] == "6,993"  # 증가율이 성립하지 않으니 값만

    def test_hover에_QoQ가_들어간다(self, quarter_table):
        fig = charts.earnings_chart(quarter_table, None, None, "EPS")
        actual = next(t for t in fig.data if t.name == "실적확정")
        assert "QoQ %{customdata}" in actual.hovertemplate
        assert actual.customdata[0] == "—"  # 첫 분기


class Test로그축:
    def test_주가_패널만_log이고_RSI는_선형_고정(self):
        df = make_ohlcv([100.0 + i for i in range(60)])
        fig = charts.technical_chart(df, 150.0, 90.0)
        assert fig.layout.yaxis.type == "log"          # 1단 주가
        assert fig.layout.yaxis2.type != "log"          # 2단 RSI
        assert list(fig.layout.yaxis2.range) == [0, 100]

    def test_52주_라벨이_log_좌표로_붙는다(self):
        """log축에서 주석 y는 log10(값) — 선형 값 그대로 주면 화면 밖으로 사라진다."""
        import math
        df = make_ohlcv([100.0 + i for i in range(60)])
        fig = charts.technical_chart(df, 150.0, 90.0)
        notes = [a for a in fig.layout.annotations if a.text and "52주" in a.text]
        assert len(notes) == 2
        ys = sorted(a.y for a in notes)
        assert ys[0] == pytest.approx(math.log10(90.0))
        assert ys[1] == pytest.approx(math.log10(150.0))

    def test_이동평균_색은_주황_진초록_보라_순서다(self):
        """기간 오름차순: 20=주황, 50=진초록, 200=보라.
        종가(파랑)·볼린저밴드(회색)와 겹치지 않는 색으로만 고른다."""
        df = make_ohlcv([100.0 + i for i in range(60)])
        fig = charts.technical_chart(df, 150.0, 90.0, ma_windows=(20, 50, 200))
        colors = {t.name: t.line.color for t in fig.data if t.name and t.name.startswith("MA")}
        assert colors["MA 20"] == charts.C["s2"]
        assert colors["MA 50"] == "#008300"
        assert colors["MA 200"] == "#4a3aa7"
