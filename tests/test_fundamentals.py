"""재무 JSON 정규화 테스트."""

import pytest

from src.fundamentals import (
    EOK, parse_finance, parse_korean_amount, parse_snapshot, to_number,
)
from tests.conftest import SAMSUNG_A_PERIODS, SAMSUNG_A_EPS, make_finance, make_integration


class Test숫자변환:
    @pytest.mark.parametrize("raw,expected", [
        ("1,738,644", 1738644.0),
        ("20.53배", 20.53),
        ("46.71%", 46.71),
        ("12,372원", 12372.0),
        ("+487,617", 487617.0),
        ("-3,319,368", -3319368.0),
        ("-78", -78.0),
        (1234, 1234.0),
        (12.5, 12.5),
    ])
    def test_다양한_표기를_숫자로(self, raw, expected):
        assert to_number(raw) == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["-", "", None, "N/A", "   "])
    def test_값이_없으면_None(self, raw):
        assert to_number(raw) is None


class Test한글금액:
    def test_조와_억을_함께_읽는다(self):
        assert parse_korean_amount("1,484조 9,548억") == pytest.approx(1_484_9548 * 10**8)

    def test_억만_있는_경우(self):
        assert parse_korean_amount("8조 5,199억") == pytest.approx(8 * 10**12 + 5199 * 10**8)

    def test_단위가_없으면_그대로(self):
        assert parse_korean_amount("249,500") == pytest.approx(249500.0)

    def test_값이_없으면_None(self):
        assert parse_korean_amount("-") is None
        assert parse_korean_amount(None) is None


class Test재무표:
    def test_기간이_뒤섞여_와도_오름차순으로_정렬한다(self, quarterly):
        assert [p.key for p in quarterly.periods] == [
            "202503", "202506", "202509", "202512", "202603", "202606"
        ]

    def test_컨센서스_기간을_구분한다(self, quarterly):
        assert [p.key for p in quarterly.consensus_periods()] == ["202606"]
        assert [p.key for p in quarterly.actual_periods()] == [
            "202503", "202506", "202509", "202512", "202603"
        ]

    def test_하이픈은_결측으로_읽는다(self, quarterly):
        assert quarterly.value("ROE", "202606") is None
        assert quarterly.value("ROE", "202603") == pytest.approx(19.16)

    def test_확정_최근_4개_분기를_가져온다(self, quarterly):
        pairs = quarterly.last_actual_values("EPS", 4)
        assert [p.key for p, _ in pairs] == ["202506", "202509", "202512", "202603"]
        assert sum(v for _, v in pairs) == pytest.approx(12373.0)

    def test_분기합이_연간값과_일치한다(self, quarterly, annual):
        """네이버 분기 값은 누적이 아니라 개별 분기값이다. 실측으로 확인된 성질."""
        q_sum = sum(quarterly.value("EPS", k) for k in ("202503", "202506", "202509", "202512"))
        assert q_sum == pytest.approx(annual.value("EPS", "202512"), abs=2)

    def test_없는_라벨은_None(self, quarterly):
        assert quarterly.value("존재하지않는행", "202503") is None

    def test_행_순서가_바뀌어도_라벨로_찾는다(self):
        reversed_rows = {"EPS": SAMSUNG_A_EPS, "매출액": {"202312": "1"}}
        table = parse_finance(make_finance(SAMSUNG_A_PERIODS, reversed_rows))
        assert table.value("EPS", "202512") == pytest.approx(6564.0)

    def test_빈_payload도_죽지_않는다(self):
        table = parse_finance({})
        assert table.periods == [] and table.rows == {}


class Test요약정보:
    def test_현재가는_전일종가가_아니라_최신_거래일_종가다(self, snapshot):
        assert snapshot.price == pytest.approx(254000.0)  # dealTrendInfos 최신
        assert snapshot.price_date == "20260727"

    def test_상승일_때_등락폭은_양수(self, snapshot):
        assert snapshot.change == pytest.approx(4500.0)
        assert snapshot.change_pct == pytest.approx(4500 / 249500 * 100)

    def test_하락일_때_등락폭은_음수로_뒤집는다(self):
        payload = make_integration()
        payload["dealTrendInfos"] = payload["dealTrendInfos"][1:]  # FALLING 인 날
        snap = parse_snapshot(payload)
        assert snap.change == pytest.approx(-20500.0)

    def test_시가총액을_원_단위로_읽는다(self, snapshot):
        assert snapshot.market_cap == pytest.approx(1_484_9548 * 10**8)

    def test_목표주가와_상승여력(self, snapshot):
        assert snapshot.target_price == pytest.approx(513958.0)
        assert snapshot.upside_pct == pytest.approx((513958 / 254000 - 1) * 100)

    def test_컨센서스가_없으면_상승여력도_없다(self):
        payload = make_integration()
        payload["consensusInfo"] = {}
        assert parse_snapshot(payload).upside_pct is None

    def test_기관외국인_순매수를_표로_만든다(self, snapshot):
        df = snapshot.deal_trend
        assert len(df) == 2
        assert list(df["date"].dt.strftime("%Y%m%d")) == ["20260724", "20260727"]  # 오름차순
        assert df["organ_net"].iloc[-1] == pytest.approx(487617.0)

    def test_거래정보가_없어도_전일종가로_버틴다(self):
        payload = make_integration()
        payload["dealTrendInfos"] = []
        snap = parse_snapshot(payload)
        assert snap.price == pytest.approx(249500.0)
        assert snap.deal_trend.empty
