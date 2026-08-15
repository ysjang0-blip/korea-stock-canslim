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

    def test_최근_126거래일만_보여준다(self):
        """1년 반치 데이터를 받아도 화면에는 6개월(126거래일)만 그린다."""
        fig = self._fig()  # 300행 입력
        assert all(len(t.y) == 126 for t in fig.data)

    def test_이동평균은_전체_이력으로_계산한_뒤_자른다(self):
        """표시 구간만으로 계산하면 MA 50 앞 49일이 비는데, 그러면 안 된다."""
        import math
        fig = self._fig()
        ma50 = next(t for t in fig.data if t.name == "MA 50")
        assert not math.isnan(ma50.y[0])


class TestHover비활성:
    """모바일 스크롤 중 툴팁이 떠서 방해되므로 모든 차트에서 hover 를 끈다."""

    def test_모든_차트가_hover를_끈다(self, quarter_table):
        df = make_ohlcv([100.0 + i for i in range(60)])
        figs = [
            charts.technical_chart(df, 150.0, 90.0),
            charts.relative_chart(df, df, "KOSPI", "종목", days=30),
            charts.earnings_chart(quarter_table, None, None, "EPS"),
            charts.price_chart(df, 150.0, 90.0),
        ]
        assert all(fig.layout.hovermode is False for fig in figs)


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

    def test_QoQ는_막대_라벨로만_보여준다(self, quarter_table):
        """hover 를 껐으므로 hovertemplate/customdata 는 남기지 않는다."""
        fig = charts.earnings_chart(quarter_table, None, None, "EPS")
        actual = next(t for t in fig.data if t.name == "실적확정")
        assert actual.hovertemplate is None
        assert actual.customdata is None


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

    def test_표시_범위에서_먼_52주선은_긋지_않는다(self):
        """급등주의 52주 최저처럼 화면 밖 먼 값까지 축을 늘리면 6개월 확대가 무의미해진다."""
        df = make_ohlcv([100.0 + i for i in range(60)])
        fig = charts.technical_chart(df, 150.0, 20.0)  # 최저 20은 표시 범위(≈100~160)에서 멀다
        notes = [a for a in fig.layout.annotations if a.text and "52주" in a.text]
        assert len(notes) == 1
        assert "최고" in notes[0].text

    def test_주가_축_범위가_52주선까지_덮는다(self):
        """자동 범위는 hline(shape)을 반영하지 않으므로 직접 준 범위가 선을 덮어야 한다."""
        import math
        df = make_ohlcv([100.0 + i for i in range(60)])
        fig = charts.technical_chart(df, 150.0, 90.0)
        lo, hi = fig.layout.yaxis.range
        assert lo < math.log10(90.0)
        assert hi > math.log10(150.0)

    def test_이동평균_색은_주황_진초록_보라_순서다(self):
        """기간 오름차순: 20=주황, 50=진초록, 200=보라.
        종가(파랑)·볼린저밴드(회색)와 겹치지 않는 색으로만 고른다."""
        df = make_ohlcv([100.0 + i for i in range(60)])
        fig = charts.technical_chart(df, 150.0, 90.0, ma_windows=(20, 50, 200))
        colors = {t.name: t.line.color for t in fig.data if t.name and t.name.startswith("MA")}
        assert colors["MA 20"] == charts.C["s2"]
        assert colors["MA 50"] == "#008300"
        assert colors["MA 200"] == "#4a3aa7"
