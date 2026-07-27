"""테스트용 데이터 생성기.

네이버 실제 응답과 같은 모양의 가짜 payload 를 만들어, 네트워크 없이 테스트한다.
숫자는 2026-07-27 에 실제로 받아온 삼성전자 값을 그대로 썼다.
"""

import pandas as pd
import pytest

from src.fundamentals import parse_finance, parse_snapshot

# 삼성전자 실측값 (단위: 매출액 억원, EPS 원)
SAMSUNG_Q_PERIODS = [
    ("202503", False), ("202506", False), ("202509", False),
    ("202512", False), ("202603", False), ("202606", True),
]
SAMSUNG_Q_EPS = {
    "202503": "1,186", "202506": "733", "202509": "1,783",
    "202512": "2,864", "202603": "6,993", "202606": "10,625",
}
SAMSUNG_Q_REVENUE = {
    "202503": "791,405", "202506": "745,663", "202509": "860,617",
    "202512": "938,374", "202603": "1,338,734", "202606": "1,738,644",
}
SAMSUNG_Q_ROE = {
    "202503": "9.24", "202506": "7.95", "202509": "8.37",
    "202512": "10.85", "202603": "19.16", "202606": "-",
}
SAMSUNG_A_PERIODS = [("202312", False), ("202412", False), ("202512", False), ("202612", True)]
SAMSUNG_A_EPS = {"202312": "2,131", "202412": "4,950", "202512": "6,564", "202612": "46,664"}
SAMSUNG_A_REVENUE = {
    "202312": "2,589,355", "202412": "3,008,709",
    "202512": "3,336,059", "202612": "7,324,741",
}
SAMSUNG_A_ROE = {"202312": "4.15", "202412": "9.03", "202512": "10.85", "202612": "54.54"}

SAMSUNG_PRICE = 254_000.0
SAMSUNG_BPS = 71_907.0
SAMSUNG_MARKET_CAP = 1_484_9548 * 10**8  # '1,484조 9,548억'


def make_finance(periods, rows, *, shuffle_columns=True):
    """네이버 finance 응답 모양으로. columns 사전은 실제로 순서가 뒤섞여 오므로 기본으로 섞는다."""
    def cols(mapping):
        keys = list(mapping)
        if shuffle_columns:
            keys = keys[2:] + keys[:2]
        return {k: {"value": mapping[k], "cx": None} for k in keys}

    return {
        "financeInfo": {
            "trTitleList": [
                {"key": k, "title": f"{k[:4]}.{k[4:]}.", "isConsensus": "Y" if c else "N"}
                for k, c in periods
            ],
            "rowList": [{"title": label, "columns": cols(values)} for label, values in rows.items()],
        }
    }


@pytest.fixture
def quarterly():
    return parse_finance(make_finance(
        SAMSUNG_Q_PERIODS,
        {"매출액": SAMSUNG_Q_REVENUE, "EPS": SAMSUNG_Q_EPS, "ROE": SAMSUNG_Q_ROE},
    ))


@pytest.fixture
def annual():
    return parse_finance(make_finance(
        SAMSUNG_A_PERIODS,
        {"매출액": SAMSUNG_A_REVENUE, "EPS": SAMSUNG_A_EPS, "ROE": SAMSUNG_A_ROE},
    ))


def make_integration(**overrides):
    totals = {
        "lastClosePrice": "249,500", "marketValue": "1,484조 9,548억",
        "foreignRate": "46.71%", "highPriceOf52Weeks": "380,000",
        "lowPriceOf52Weeks": "65,600", "per": "20.53배", "eps": "12,372원",
        "cnsPer": "5.44배", "cnsEps": "46,664원", "pbr": "3.53배",
        "bps": "71,907원", "dividendYieldRatio": "0.66%",
    }
    totals.update(overrides.pop("totals", {}))
    payload = {
        "itemCode": "005930",
        "stockName": "삼성전자",
        "totalInfos": [{"code": k, "key": k, "value": v} for k, v in totals.items()],
        "dealTrendInfos": [
            {"bizdate": "20260727", "closePrice": "254,000",
             "compareToPreviousClosePrice": "4,500",
             "compareToPreviousPrice": {"name": "RISING"},
             "foreignerPureBuyQuant": "-3,319,368", "organPureBuyQuant": "+487,617",
             "individualPureBuyQuant": "+2,801,281", "foreignerHoldRatio": "46.65%"},
            {"bizdate": "20260724", "closePrice": "249,500",
             "compareToPreviousClosePrice": "-20,500",
             "compareToPreviousPrice": {"name": "FALLING"},
             "foreignerPureBuyQuant": "-3,428,259", "organPureBuyQuant": "-3,378,638",
             "individualPureBuyQuant": "+6,675,340", "foreignerHoldRatio": "46.71%"},
        ],
        "consensusInfo": {
            "createDate": "2026-07-24", "recommMean": "4.04", "priceTargetMean": "513,958",
        },
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def snapshot():
    return parse_snapshot(make_integration())


def make_ohlcv(closes, volumes=None, foreign=None, start="2024-01-01"):
    n = len(closes)
    return pd.DataFrame({
        "date": pd.date_range(start, periods=n, freq="D"),
        "open": closes, "high": closes, "low": closes,
        "close": [float(c) for c in closes],
        "volume": [float(v) for v in (volumes or [1000.0] * n)],
        "foreign_rate": [float(f) for f in (foreign or [30.0] * n)],
    })
