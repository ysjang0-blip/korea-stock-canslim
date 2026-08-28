"""옛 분기 EPS 보강(야후 실적 발표 이력) 테스트."""

import datetime as dt

import pytest

from src.eps_history import (
    EPS_REPORTED, extend_quarterly, map_earnings_to_quarters, quarter_key_for,
)


class Test발표일_분기_매핑:
    def test_한국_달력분기(self):
        # 삼성전자: 7/29 발표 → 6월 분기, 1/28 발표 → 전년 12월 분기
        assert quarter_key_for(dt.date(2026, 7, 29)) == "202606"
        assert quarter_key_for(dt.date(2026, 1, 28)) == "202512"
        assert quarter_key_for(dt.date(2026, 4, 29)) == "202603"
        assert quarter_key_for(dt.date(2025, 10, 29)) == "202509"

    def test_회계분기가_다른_미국_회사(self):
        # 엔비디아: 분기 말이 1·4·7·10월. 8/26 발표 → 7월 분기, 2/25 발표 → 1월 분기
        months = (1, 4, 7, 10)
        assert quarter_key_for(dt.date(2026, 8, 26), months) == "202607"
        assert quarter_key_for(dt.date(2026, 2, 25), months) == "202601"
        assert quarter_key_for(dt.date(2025, 11, 19), months) == "202510"

    def test_값_없는_행은_건너뛰고_같은_분기는_늦은_발표를_쓴다(self):
        rows = [
            (dt.date(2026, 10, 28), None),          # 예정된 발표 — 값 없음
            (dt.date(2026, 7, 29), 10849.0),
            (dt.date(2026, 7, 7), 10500.0),         # 같은 6월 분기의 잠정치 → 늦은 발표(7/29)가 이긴다
            (dt.date(2026, 4, 29), 7123.0),
        ]
        mapped = map_earnings_to_quarters(rows)
        assert mapped == {"202606": 10849.0, "202603": 7123.0}


class Test재무표_보강:
    def test_겹치는_분기가_비슷하면_발표행을_붙인다(self, quarterly):
        # 삼성 표: 202503 1,186 · 202603 6,993 … 야후 발표치는 1~2% 높다
        reported = {"202412": 1116.0, "202503": 1192.0, "202506": 737.0, "202509": 1802.0,
                    "202512": 2909.0, "202603": 7123.0}
        result = extend_quarterly(quarterly, reported)
        assert result.accepted
        assert result.added == 1                       # 202412 가 새로 생겼다
        assert quarterly.value(EPS_REPORTED, "202412") == 1116.0
        assert quarterly.value("EPS", "202603") == 6993.0   # 원래 EPS 행은 그대로
        assert "최대" in result.note and "%" in result.note

    def test_많이_다르면_버린다(self, quarterly):
        reported = {"202412": 1116.0, "202603": 9000.0}     # 6,993 vs 9,000 = 29% 차이
        result = extend_quarterly(quarterly, reported)
        assert not result.accepted
        assert EPS_REPORTED not in quarterly.rows
        assert "차이" in result.note

    def test_부호가_다르면_버린다(self, quarterly):
        result = extend_quarterly(quarterly, {"202412": 1116.0, "202603": -100.0})
        assert not result.accepted and "부호" in result.note

    def test_겹치는_분기가_없거나_자료가_없으면_붙이지_않는다(self, quarterly):
        assert not extend_quarterly(quarterly, {"202112": 500.0}).accepted
        assert not extend_quarterly(quarterly, {}).accepted
        assert EPS_REPORTED not in quarterly.rows
