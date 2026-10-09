"""최근 종목 목록(src/recent.py) 테스트 — 쿠키 인코딩·순서·제한."""

from __future__ import annotations

from src import recent
from src.tickers import StockRef

SAMSUNG = StockRef(code="005930", name="삼성전자", market="코스피", region="KR")
APPLE = StockRef(code="AAPL", name="Apple Inc.", market="나스닥", region="US")


class Test목록:
    def test_새_종목은_맨_앞(self):
        assert recent.push([SAMSUNG], APPLE) == [APPLE, SAMSUNG]

    def test_이미_있으면_맨_앞으로_옮긴다(self):
        assert recent.push([APPLE, SAMSUNG], SAMSUNG) == [SAMSUNG, APPLE]

    def test_최대_10개(self):
        items = [StockRef(code=f"{i:06d}", name=f"종목{i}", market="코스피") for i in range(10)]
        out = recent.push(items, APPLE)
        assert len(out) == recent.MAX_ITEMS and out[0] == APPLE
        assert items[-1] not in out

    def test_같은_코드라도_지역이_다르면_다른_종목(self):
        kr = StockRef(code="AAPL", name="가짜", market="코스피", region="KR")
        assert len(recent.push([APPLE], kr)) == 2

    def test_삭제(self):
        assert recent.remove([APPLE, SAMSUNG], APPLE) == [SAMSUNG]


class Test쿠키:
    def test_왕복(self):
        items = [SAMSUNG, APPLE]
        assert recent.decode(recent.encode(items)) == items

    def test_쿠키_값에는_따옴표나_세미콜론이_없다(self):
        value = recent.encode([SAMSUNG, APPLE])
        assert not set(value) & set("';\" ,")

    def test_4KB_이내(self):
        items = [StockRef(code=f"{i:06d}", name="아주긴종목이름" * 3, market="코스닥") for i in range(10)]
        assert len(recent.encode(items)) < 4000

    def test_깨진_쿠키는_빈_목록(self):
        assert recent.decode("%7Bnot-json") == []
        assert recent.decode("") == []
        assert recent.decode(None) == []

    def test_필수값이_없는_항목은_건너뛴다(self):
        value = recent.encode([SAMSUNG]).replace("005930", "")
        assert recent.decode(value) == []

    def test_스크립트는_쿠키를_1년간_저장(self):
        script = recent.cookie_script([SAMSUNG])
        assert script.startswith("<script>") and recent.COOKIE_NAME in script
        assert f"max-age={recent.MAX_AGE_SEC}" in script and "path=/" in script
