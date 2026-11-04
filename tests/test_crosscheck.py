"""분기 EPS 공시 교차검증(src/crosscheck.py · sec.py · dart.py) 테스트 — 네트워크 없이."""

from __future__ import annotations

from src import crosscheck, dart, sec, verification
from src.fundamentals import FinancialTable, Period
from tests.conftest import make_ohlcv
from tests.test_bands import annual_table
from tests.test_verification import build as build_verification, quarterly_table, snap, val


def table(eps: dict[str, float]) -> FinancialTable:
    periods = [Period(key=k, title=k, is_consensus=False) for k in sorted(eps)]
    return FinancialTable(periods=periods, rows={"EPS": dict(eps)}, money_unit=1.0)


class Test비교:
    def test_모두_일치하면_확인(self):
        r = crosscheck.compare(table({"202503": 1.00, "202506": 1.10, "202509": 1.20}),
                               {"202503": 1.01, "202506": 1.10, "202509": 1.19}, "SEC EDGAR", 0.02)
        assert r.ok is True and r.compared == 3 and r.matched == 3

    def test_센트_반올림_차이는_허용(self):
        r = crosscheck.compare(table({"202503": 0.03, "202506": 0.06}),
                               {"202503": 0.02, "202506": 0.05}, "SEC EDGAR", 0.02)
        assert r.ok is True

    def test_크게_다르면_불일치와_사유(self):
        r = crosscheck.compare(table({"202503": 1.00, "202506": 1.10}),
                               {"202503": 1.00, "202506": 0.11}, "SEC EDGAR", 0.02)  # 10:1 분할 의심
        assert r.ok is False and r.matched == 1
        assert "2025.06" in r.note and "주식분할" in r.note

    def test_겹치는_분기가_부족하면_판단_불가(self):
        r = crosscheck.compare(table({"202503": 1.0}), {"202503": 1.0, "202412": 2.0}, "DART", 1.0)
        assert r.ok is None and "겹치는 분기" in r.note

    def test_컨센서스_분기는_비교에서_빠진다(self):
        t = table({"202503": 1.0, "202506": 1.1})
        t.periods.append(Period(key="202509", title="x", is_consensus=True))
        t.rows["EPS"]["202509"] = 99.0
        assert crosscheck.compare(t, {"202503": 1.0, "202506": 1.1, "202509": 1.2}, "SEC", 0.02).ok is True


class TestSEC파싱:
    @staticmethod
    def facts(entries, tag="EarningsPerShareDiluted"):
        return {"facts": {"us-gaap": {tag: {"units": {"USD/shares": entries}}}}}

    def test_3개월_값만_쓰고_누적은_버린다(self):
        f = self.facts([
            {"start": "2025-01-27", "end": "2025-04-27", "val": 0.76, "filed": "2025-05-28"},
            {"start": "2025-01-27", "end": "2025-07-27", "val": 1.84, "filed": "2025-08-27"},  # 6개월 누적
            {"start": "2025-04-28", "end": "2025-07-27", "val": 1.08, "filed": "2025-08-27"},
        ])
        assert sec.quarterly_eps(f) == {"202504": 0.76, "202507": 1.08}

    def test_같은_분기가_여러_번이면_나중에_제출된_값(self):
        f = self.facts([
            {"start": "2024-01-29", "end": "2024-04-28", "val": 5.98, "filed": "2024-05-29"},
            {"start": "2024-01-29", "end": "2024-04-28", "val": 0.60, "filed": "2025-05-28"},  # 분할 후 재작성
        ])
        assert sec.quarterly_eps(f) == {"202404": 0.60}

    def test_희석이_없으면_다음_태그(self):
        f = self.facts([{"start": "2025-01-01", "end": "2025-03-31", "val": 2.0, "filed": "2025-05-01"}],
                       tag="EarningsPerShareBasicAndDiluted")
        assert sec.quarterly_eps(f) == {"202503": 2.0}

    def test_티커로_CIK_찾기(self):
        data = {"0": {"cik_str": 1045810, "ticker": "NVDA"}, "1": {"cik_str": 1067983, "ticker": "BRK-B"}}
        assert sec.cik_for("nvda", data) == 1045810
        assert sec.cik_for("BRK.B", data) == 1067983
        assert sec.cik_for("ZZZZ", data) is None

    def test_연락처_없으면_호출_없이_판단_불가(self, monkeypatch):
        monkeypatch.delenv("SEC_USER_AGENT", raising=False)
        r = sec.cross_check("NVDA", table({"202503": 1.0, "202506": 1.1}))
        assert r.ok is None and "SEC_USER_AGENT" in r.note


class TestDART파싱:
    def test_기본주당이익_행을_찾는다(self):
        payload = {"status": "000", "list": [
            {"sj_div": "BS", "account_nm": "자본총계", "thstrm_amount": "100"},
            {"sj_div": "IS", "account_id": "ifrs-full_BasicEarningsLossPerShare",
             "account_nm": "기본주당이익(손실)", "thstrm_amount": "1,234"},
        ]}
        assert dart.parse_eps(payload) == 1234.0

    def test_오류_응답이나_행_없음은_None(self):
        assert dart.parse_eps({"status": "013", "message": "조회된 데이타가 없습니다."}) is None
        assert dart.parse_eps({"status": "000", "list": []}) is None

    def test_키가_없으면_호출_없이_판단_불가(self, monkeypatch):
        monkeypatch.delenv("DART_API_KEY", raising=False)
        r = dart.cross_check("005930", table({"202503": 1.0, "202506": 1.1}))
        assert r.ok is None and "DART_API_KEY" in r.note


class Test검증표_반영:
    def test_일치하면_교차검증_행이_확인_등급(self):
        cc = crosscheck.CrossCheck(True, "SEC EDGAR", 3, 3, note="일치")
        df = make_ohlcv([10_000.0] * 260)
        v = verification.build(snap(), quarterly_table(), annual_table({2024: 900.0, 2025: 1_000.0}),
                               val(), df, df, "KOSPI", eps_cross=cc)
        row = next(c for c in v.checks if c.item == "분기 EPS (공시 교차검증)")
        assert row.grade == verification.CONFIRMED
        # 매출은 대조하지 않았으므로 기존 행은 단일 그대로
        assert next(c for c in v.checks if c.item == "분기 EPS·매출").grade == verification.SINGLE

    def test_판단_불가면_단일로_남는다(self):
        v = build_verification(snap())
        assert all(c.item != "분기 EPS (공시 교차검증)" for c in v.checks)  # 시도 안 했으면 행 없음
        df = make_ohlcv([10_000.0] * 260)
        v = verification.build(snap(), quarterly_table(), annual_table({2024: 900.0, 2025: 1_000.0}),
                               val(), df, df, "KOSPI",
                               eps_cross=crosscheck.unavailable("DART", "키 없음"))
        row = next(c for c in v.checks if c.item == "분기 EPS (공시 교차검증)")
        assert row.grade == verification.SINGLE and "키 없음" in row.value
