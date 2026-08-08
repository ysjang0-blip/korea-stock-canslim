"""CANSLIM 의 N — '새로운 재료' 추출 테스트.

제목은 2026-07-27 네이버에서 실제로 받아온 형식을 따랐다.
"""

import datetime as dt

import pytest

from src.newness import classify, clean_title, detect, parse_date

TODAY = dt.date(2026, 7, 27)


class Test분류:
    @pytest.mark.parametrize("title,expected", [
        ("(주)에이비씨 단일판매ㆍ공급계약체결", "수주·공급계약"),
        ("(주)에이비씨 신규 시설투자 등", "설비투자·증설"),
        ("(주)에이비씨 타법인 주식 및 출자증권 취득결정", "인수·합병"),
        ("(주)에이비씨 최대주주 변경", "경영진 변경"),
        ("(주)에이비씨 자기주식 취득 결정", "자사주 매입"),
        ("에이비씨, 차세대 배터리 신제품 출시", "신제품·신사업"),
        ("에이비씨, 임상 3상 품목허가 획득", "인허가·기술"),
    ])
    def test_새로운_재료를_분류한다(self, title, expected):
        assert classify(title) == expected

    @pytest.mark.parametrize("title", [
        "삼성전자(주) 풍문 또는 보도에 대한 해명(미확정)",
        "삼성전자(주) 주식선물ㆍ주식옵션 2단계 가격제한폭 확대요건 도달(하락)",
        "(주)에이비씨 불성실공시법인 지정",
        "(주)에이비씨 소송 등의 제기",
        "롤러코스피 끝 6,700선 사수…코스닥 2% 강세",
    ])
    def test_잡음과_악재는_걸러낸다(self, title):
        assert classify(title) is None

    def test_자기주식_처분은_재료가_아니다(self):
        """취득(자사주 매입)은 호재지만 처분은 반대다. 둘을 구분해야 한다."""
        assert classify("삼성전자(주) 자기주식 취득 결정") == "자사주 매입"
        assert classify("삼성전자(주) 자기주식 처분 결정") is None

    def test_정정공시는_새_재료로_치지_않는다(self):
        assert classify("(주)에이비씨 [기재정정]단일판매ㆍ공급계약체결") is None

    def test_띄어쓰기가_달라도_잡아낸다(self):
        assert classify("(주)에이비씨 공급 계약 체결") == "수주·공급계약"

    def test_빈_제목(self):
        assert classify("") is None and classify(None) is None


class Test제목정리:
    def test_HTML_이스케이프를_푼다(self):
        """실측: 네이버 뉴스가 '삼성E&amp;A' 형태로 내려준다."""
        assert clean_title("에코프로에이치엔, 삼성E&amp;A에 &#39;330억&#39; 규모 공급 계약") == (
            "에코프로에이치엔, 삼성E&A에 '330억' 규모 공급 계약"
        )

    def test_공백을_정리한다(self):
        assert clean_title("  가나다   \n 라마바 ") == "가나다 라마바"

    def test_None도_처리한다(self):
        assert clean_title(None) == ""


class Test날짜:
    @pytest.mark.parametrize("raw,expected", [
        ("2026-07-23T06:52:43", dt.date(2026, 7, 23)),   # 공시 형식
        ("20260708", dt.date(2026, 7, 8)),               # 리포트 형식
        ("202607272103", dt.date(2026, 7, 27)),          # 뉴스 형식
    ])
    def test_세_가지_날짜_형식을_모두_읽는다(self, raw, expected):
        assert parse_date(raw) == expected

    def test_읽을_수_없으면_None(self):
        assert parse_date("") is None and parse_date("어제") is None


class Test탐지:
    def test_세_소스를_모두_훑는다(self):
        result = detect(
            disclosures=[{"title": "(주)가 단일판매ㆍ공급계약체결", "datetime": "2026-07-20T09:00:00"}],
            articles=[{"title": "가, 신제품 출시", "datetime": "202607150900"}],
            researches=[{"tit": "대규모 증설 결정", "wdt": "20260710"}],
            today=TODAY,
        )
        assert result.found
        assert {i.source for i in result.items} == {"공시", "뉴스", "리포트"}
        assert result.scanned == 3

    def test_기간을_벗어난_것은_제외한다(self):
        result = detect(
            disclosures=[{"title": "(주)가 단일판매ㆍ공급계약체결", "datetime": "2024-01-01T09:00:00"}],
            articles=[], researches=[], window_days=180, today=TODAY,
        )
        assert not result.found
        assert result.scanned == 1      # 훑기는 했다

    def test_재료가_없으면_found는_False지만_available은_True(self):
        """데이터는 받았는데 재료가 없는 것과, 데이터를 못 받은 것은 다르다."""
        result = detect(disclosures=[{"title": "풍문 해명", "datetime": "2026-07-20T09:00:00"}],
                        articles=[], researches=[], today=TODAY)
        assert not result.found and result.available

    def test_아무것도_못_받으면_available이_False(self):
        result = detect(disclosures=[], articles=[], researches=[], today=TODAY)
        assert not result.available

    def test_None이_들어와도_죽지_않는다(self):
        assert not detect(None, None, None, today=TODAY).available

    def test_분류를_중복_없이_최신순으로_모은다(self):
        result = detect(
            disclosures=[
                {"title": "(주)가 단일판매ㆍ공급계약체결", "datetime": "2026-07-20T09:00:00"},
                {"title": "(주)가 신규 시설투자 등", "datetime": "2026-07-21T09:00:00"},
                {"title": "(주)가 최대주주 변경", "datetime": "2026-07-22T09:00:00"},
            ],
            articles=[], researches=[], today=TODAY,
        )
        assert result.categories == ["경영진 변경", "설비투자·증설", "수주·공급계약"]

    def test_같은_사건_기사는_하나만_남긴다(self):
        """실측: 두산 원전 수주 하나를 5개 매체가 조금씩 다르게 썼다."""
        same_event = [
            "두산에너빌, 中 라이양 원전 5·6호기 핵심소재 공급 계약",
            "두산에너빌, 中 라이양 원전 5∙6호기 핵심소재 공급 계약 체결",
            "두산에너빌리티, 中 라이양 원전 5∙6호기 핵심부품 공급 계약",
            "두산에너빌리티, 中 라이양 원전 5·6호기 핵심 소재 공급 계약",  # 띄어쓰기만 다름
        ]
        result = detect(
            disclosures=[],
            articles=[{"title": t, "datetime": "202607270900"} for t in same_event],
            researches=[], today=TODAY,
        )
        assert result.scanned == 4
        assert len(result.items) == 1     # 같은 사건 = 1건

    def test_다른_사건은_따로_센다(self):
        result = detect(
            disclosures=[],
            articles=[
                {"title": "가나다, 中 라이양 원전 핵심소재 공급 계약", "datetime": "202607270900"},
                {"title": "가나다, 미국 반도체 공장 신규 시설투자 결정", "datetime": "202607260900"},
            ],
            researches=[], today=TODAY,
        )
        assert len(result.items) == 2

    def test_공시가_뉴스보다_우선_남는다(self):
        result = detect(
            disclosures=[{"title": "(주)가나다 단일판매ㆍ공급계약체결 라이양 원전",
                          "datetime": "2026-07-27T09:00:00"}],
            articles=[{"title": "가나다 단일판매 공급계약체결 라이양 원전",
                       "datetime": "202607270900"}],
            researches=[], today=TODAY,
        )
        assert len(result.items) == 1
        assert result.items[0].source == "공시"

    def test_최신순으로_보여준다(self):
        result = detect(
            disclosures=[
                {"title": "(주)가 수주 공시", "datetime": "2026-05-01T09:00:00"},
                {"title": "(주)가 증설 공시", "datetime": "2026-07-20T09:00:00"},
            ],
            articles=[], researches=[], today=TODAY,
        )
        assert result.top(1)[0].date == dt.date(2026, 7, 20)


class Test영문분류:
    """미국 뉴스 제목 (야후) — 대소문자를 가리지 않는다."""

    @pytest.mark.parametrize("title,expected", [
        ("Apple Unveils New AI Chip For Data Centers", "신제품·신사업"),
        ("Boeing wins $2 billion defense contract", "수주·공급계약"),
        ("TSMC announces capacity expansion in Arizona", "설비투자·증설"),
        ("Broadcom completes acquisition of software firm", "인수·합병"),
        ("Intel names new CEO to lead turnaround", "경영진 변경"),
        ("Biotech gets FDA approval for cancer drug", "인허가·기술"),
        ("Apple announces $110 billion buyback", "자사주 매입"),
    ])
    def test_영문_재료를_분류한다(self, title, expected):
        assert classify(title) == expected

    @pytest.mark.parametrize("title", [
        "Tesla faces class action lawsuit over autopilot claims",
        "Chipmaker hit with SEC investigation",
        "Analyst downgrade sends shares lower",
    ])
    def test_영문_잡음과_악재는_걸러낸다(self, title):
        assert classify(title) is None
