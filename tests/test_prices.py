"""시세 파서 테스트 — 네트워크를 타지 않는다."""

import pandas as pd
import pytest

from src.prices import PriceParseError, moving_average, parse_sise, pct_return, market_symbol

# 네이버 실제 응답 형태: 작은따옴표 헤더 + 탭/개행 섞임
RAW = """
 [['날짜', '시가', '고가', '저가', '종가', '거래량', '외국인소진율'],

\t\t
["20260720", 241000, 257500, 240000, 244000, 26804038, 46.59],
\t\t
["20260721", 247000, 263500, 243000, 259000, 20386896, 46.63],
\t\t
["20260722", 276000, 276000, 260000, 260500, 22292003, 46.71]]
"""


def test_작은따옴표_리터럴을_파싱한다():
    df = parse_sise(RAW)
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "foreign_rate"]
    assert len(df) == 3
    assert df["close"].iloc[-1] == 260500
    assert df["date"].iloc[0] == pd.Timestamp("2026-07-20")


def test_날짜_오름차순으로_정렬된다():
    shuffled = """[['날짜','종가'],["20260722",3],["20260720",1],["20260721",2]]"""
    df = parse_sise(shuffled)
    assert list(df["close"]) == [1, 2, 3]


def test_null_값을_처리한다():
    raw = """[['날짜','종가','외국인소진율'],["20260720",244000,null]]"""
    df = parse_sise(raw)
    assert pd.isna(df["foreign_rate"].iloc[0])
    assert df["close"].iloc[0] == 244000


def test_열_개수가_안_맞는_행은_버린다():
    raw = """[['날짜','종가'],["20260720",1],["20260721",2,999],["20260722",3]]"""
    assert len(parse_sise(raw)) == 2


def test_빈_응답은_오류를_낸다():
    with pytest.raises(PriceParseError):
        parse_sise("   ")


def test_깨진_응답은_오류를_낸다():
    with pytest.raises(PriceParseError):
        parse_sise("<html>error</html>")


def test_헤더만_있으면_빈_표를_준다():
    assert len(parse_sise("""[['날짜','종가']]""")) == 0


class Test수익률:
    close = pd.Series([100.0, 110.0, 120.0, 150.0])

    def test_n거래일_전_대비_수익률(self):
        assert pct_return(self.close, 3) == pytest.approx(50.0)
        assert pct_return(self.close, 1) == pytest.approx(25.0)

    def test_데이터가_모자라면_None(self):
        assert pct_return(self.close, 10) is None

    def test_과거값이_0이면_None(self):
        assert pct_return(pd.Series([0.0, 5.0]), 1) is None


class Test이동평균:
    def test_평균을_구한다(self):
        assert moving_average(pd.Series([1.0, 2.0, 3.0]), 3) == pytest.approx(2.0)

    def test_기간이_모자라면_None(self):
        assert moving_average(pd.Series([1.0, 2.0]), 3) is None


class Test비교지수:
    def test_코스닥은_KOSDAQ를_쓴다(self):
        assert market_symbol("코스닥") == "KOSDAQ"
        assert market_symbol("KOSDAQ") == "KOSDAQ"

    def test_그_외에는_KOSPI(self):
        assert market_symbol("코스피") == "KOSPI"
        assert market_symbol(None) == "KOSPI"
