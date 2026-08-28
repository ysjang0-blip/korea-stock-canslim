"""윌리엄 오닐의 CANSLIM 7개 항목 판정 — 엄격 버전.

기준서는 docs/canslim_criteria.md 이며, 이 파일의 상수와 세부 조건은 그 문서를 그대로 옮긴 것이다.

  C  Current quarterly earnings   분기 EPS 전년比 2분기 연속 +17% · 직전 분기보다 증가 · 매출 +25%
  A  Annual earnings growth       연간 EPS CAGR +17% · 매년 증가 · ROE 17% (없으면 판단불가)
  N  New high / New something     52주 최고가의 90% 이상 · 새로운 재료 2건 이상
  S  Supply and demand            상승일/하락일 거래량 1.2배 · 최근 10일 거래량이 50일 평균의 1.2배
  L  Leader or laggard            지수 대비 +20%p · 종목 수익률 양수 · 현재가 > 50일선 > 200일선
  I  Institutional sponsorship    외국인 소진율 +0.5%p · 기관 누적 순매수 양수 (미국은 판단불가)
  M  Market direction             지수가 50·200일선 위 · 50일선 > 200일선 · 분산일 5일 미만

각 항목은 세부 조건(SubCheck) 여러 개로 이루어지고, 전부 만족해야 그 항목이 합격이다.
확실히 어긋난 세부 조건이 하나라도 있으면 불합격, 어긋난 것은 없는데 모르는 것이 있으면 판단불가.
종합은 7개 항목 모두 합격해야 'CANSLIM 충족'이다 — 판단불가는 불합격이 아니지만 충족도 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .fundamentals import FinancialTable, Period, Snapshot
from .models import CanslimItem, CanslimResult, SubCheck, Verdict, verdict_of
from .newness import Newness
from .prices import moving_average, pct_return
from .valuation import EPS, REVENUE, GrowthRates, yoy

# ── 기준값 (docs/canslim_criteria.md 와 같아야 한다)
C_EPS_YOY_MIN = 17.0         # C1·C2: 분기 EPS 전년동기比 %
C_REVENUE_YOY_MIN = 25.0     # C4: 분기 매출 전년동기比 %
C_BASE_EFFECT_PCT = 300.0    # C5: 이보다 크면 기저효과 경고
A_CAGR_MIN = 17.0            # A1: 연간 EPS 연평균 성장률 %
A_ROE_MIN = 17.0             # A3: ROE %
N_NEAR_HIGH_RATIO = 0.90     # N1: 52주 최고가 대비
N_MATERIAL_MIN = 2           # N2: 새 재료 건수
S_WINDOW = 50                # S1: 상승일/하락일 거래량 비교 기간 (거래일)
S_UPDOWN_RATIO_MIN = 1.2     # S1
S_RECENT_DAYS = 10           # S2: 최근 평균 거래량 기간
S_RECENT_RATIO_MIN = 1.2     # S2: 50일 평균 대비 배수
L_SPREAD_MIN = 20.0          # L1: 지수 대비 초과 수익률 %p
I_TREND_DAYS = 60            # I1: 외국인 소진율 비교 기간 (거래일)
I_FOREIGN_MIN_PP = 0.5       # I1: 최소 상승폭 %p
M_DIST_WINDOW = 25           # M3: 분산일 세는 기간 (거래일)
M_DIST_MAX = 5               # M3: 분산일이 이 수 '미만'이어야 함
M_DIST_DROP_PCT = 0.2        # M3: 분산일로 치는 최소 하락률 %

# L: 상대강도 가중치 (오닐 RS Rating 재현식에서 널리 쓰이는 배분)
RS_WEIGHTS = ((63, 0.4), (126, 0.2), (189, 0.2), (252, 0.2))


@dataclass
class RelativeStrength:
    stock: float | None
    index: float | None
    spread: float | None      # 종목 - 지수 (%포인트)
    detail: list[tuple[str, float | None, float | None]]
    coverage: str = ""


def weighted_return(close: pd.Series) -> float | None:
    """3·6·9·12개월 수익률의 가중 평균. 기간이 모자라면 남은 기간끼리 비중을 다시 나눈다."""
    parts = [(w, pct_return(close, days)) for days, w in RS_WEIGHTS]
    usable = [(w, r) for w, r in parts if r is not None]
    if not usable:
        return None
    total_weight = sum(w for w, _ in usable)
    return sum(w * r for w, r in usable) / total_weight


def relative_strength(stock: pd.DataFrame, index: pd.DataFrame) -> RelativeStrength:
    s_close = stock["close"] if "close" in stock else pd.Series(dtype=float)
    i_close = index["close"] if "close" in index else pd.Series(dtype=float)

    detail = [
        (name, pct_return(s_close, days), pct_return(i_close, days))
        for days, name in ((63, "3개월"), (126, "6개월"), (189, "9개월"), (252, "12개월"))
    ]
    s_w, i_w = weighted_return(s_close), weighted_return(i_close)
    spread = None if (s_w is None or i_w is None) else s_w - i_w
    missing = [name for name, sv, _ in detail if sv is None]
    coverage = f"{', '.join(missing)} 구간은 상장 기간이 짧아 제외" if missing else ""
    return RelativeStrength(stock=s_w, index=i_w, spread=spread, detail=detail, coverage=coverage)


def days_since_new_high(close: pd.Series, window: int = 252) -> int | None:
    """52주 신고가를 며칠 전에 갱신했는지 (거래일 기준). 갱신 이력이 없으면 None."""
    series = close.dropna()
    if len(series) < 2:
        return None
    recent = series.iloc[-window:] if len(series) > window else series
    peak_position = int(recent.to_numpy().argmax())
    return len(recent) - 1 - peak_position


def distribution_days(index: pd.DataFrame, window: int = M_DIST_WINDOW,
                      drop_pct: float = M_DIST_DROP_PCT) -> int | None:
    """최근 window 거래일 중 '분산일' 수 — 지수가 drop_pct% 이상 빠졌는데 거래량은 전일보다 많은 날.

    큰손이 파는 날을 세는 오닐의 시장 천장 신호. 지수 거래량이 없으면 None.
    """
    if "close" not in index or "volume" not in index:
        return None
    df = index[["close", "volume"]].dropna()
    df = df[df["volume"] > 0]
    if len(df) < window + 1:
        return None
    recent = df.iloc[-(window + 1):]
    change = recent["close"].pct_change().iloc[1:] * 100.0
    vol_up = recent["volume"].diff().iloc[1:] > 0
    return int(((change <= -drop_pct) & vol_up).sum())


# --------------------------------------------------------------- 항목별 판정

def _actual_quarters(quarterly: FinancialTable, row: str) -> list[Period]:
    return [p for p in quarterly.actual_periods() if quarterly.value(row, p.key) is not None]


def _yoy_check(quarterly: FinancialTable, row: str, idx: int, code: str, label: str,
               min_pct: float) -> tuple[SubCheck, float | None, Period | None]:
    """확정 분기 idx(0=최신, 1=직전) 의 row 값을 전년 같은 분기와 비교하는 세부 조건.

    전년 동기 자료가 없으면 판단불가. 전년 동기가 적자면 증가율이 성립하지 않으므로
    '흑자 전환' 여부로 본다 (기준서: 판단불가는 자료가 없는 경우뿐).
    """
    periods = _actual_quarters(quarterly, row)
    if len(periods) <= idx:
        return SubCheck(code, label, "확정 분기 자료 없음", None), None, None
    target = periods[-(idx + 1)]
    now = quarterly.value(row, target.key)
    ago = quarterly.value(row, f"{target.year - 1}{target.month:02d}")
    label = f"{label}({target.label})"
    if ago is None:
        return SubCheck(code, label, "전년 동기 자료 없음", None), None, target
    if ago <= 0:
        turned = now > 0
        return SubCheck(code, label, "흑자 전환" if turned else "적자 지속 (전년 동기 적자)", turned), None, target
    rate = yoy(now, ago)
    return SubCheck(code, label, f"{rate:+,.1f}%", rate >= min_pct), rate, target


def _item_c(quarterly: FinancialTable, growth: GrowthRates, snap: Snapshot) -> CanslimItem:
    name = "최근 분기 실적"
    criterion = (
        f"분기 EPS 전년동기比 +{C_EPS_YOY_MIN:.0f}% 이상 2분기 연속 · 직전 분기보다 EPS 증가 · "
        f"분기 매출 전년동기比 +{C_REVENUE_YOY_MIN:.0f}% 이상"
    )
    c1, rate1, latest = _yoy_check(quarterly, EPS, 0, "C1", "최근 분기 EPS 전년比", C_EPS_YOY_MIN)
    c2, _, prev = _yoy_check(quarterly, EPS, 1, "C2", "직전 분기 EPS 전년比", C_EPS_YOY_MIN)

    if latest is None or prev is None:
        c3 = SubCheck("C3", "직전 분기 대비 EPS", "확정 분기 2개 미만", None)
        now_eps = prev_eps = None
    else:
        now_eps, prev_eps = quarterly.value(EPS, latest.key), quarterly.value(EPS, prev.key)
        diff = now_eps - prev_eps
        c3 = SubCheck("C3", f"직전 분기 대비 EPS({prev.label}→{latest.label})",
                      f"{snap.money(prev_eps)} → {snap.money(now_eps)} ({diff:+,.0f})", diff > 0)

    c4, _, _ = _yoy_check(quarterly, REVENUE, 0, "C4", "최근 분기 매출 전년比", C_REVENUE_YOY_MIN)
    checks = [c1, c2, c3, c4]
    verdict = verdict_of(checks)

    actual = c1.actual if latest is not None else "—"
    notes: list[str] = []

    # 기준서: C1·C2 는 못 넘어도 C3·C4 를 만족하면 직전·최근 분기 EPS 를 보여준다 (수익 증가 종목)
    if (c1.passed is False or c2.passed is False) and c3.passed and c4.passed:
        actual += f" · 수익증가 {snap.money(prev_eps)}→{snap.money(now_eps)}"
        notes.append(
            f"수익 증가 중 — 직전 {prev.label} EPS {snap.money(prev_eps)} → 최근 {latest.label} "
            f"EPS {snap.money(now_eps)}. 전년比 문턱은 못 넘었지만 분기 EPS와 매출이 함께 늘고 있습니다"
        )
    if rate1 is not None and rate1 > C_BASE_EFFECT_PCT:
        notes.append("※ 전년 동기 EPS가 매우 낮아 증가율이 과장될 수 있습니다 (기저 효과)")
    if any(c.actual.startswith(("흑자 전환", "적자 지속")) for c in (c1, c2, c4)):
        notes.append("전년 동기가 적자인 분기는 증가율 대신 흑자 전환 여부로 봤습니다")

    # 확정실적이 한 분기 늦게 반영될 수 있음을 밝히고, 다음 분기 컨센서스를 참고로 붙인다
    if growth.next_quarter_label:
        line = (f"최신 확정 분기는 {growth.latest_quarter_label}이며 "
                f"{growth.next_quarter_label} 분기는 아직 컨센서스만 있습니다")
        if growth.next_quarter_yoy.is_ok:
            line += f" (컨센서스 기준 {growth.next_quarter_yoy.value:+,.1f}%)"
        notes.append(line)

    return CanslimItem("C", name, criterion, actual, verdict, " · ".join(notes), checks)


def _item_a(growth: GrowthRates, annual: FinancialTable, roe: float | None,
            snap: Snapshot) -> CanslimItem:
    name = "연간 실적"
    criterion = (f"연간 EPS 성장 +{A_CAGR_MIN:.0f}% 이상 · 확정 연도 EPS 매년 증가 · "
                 f"ROE {A_ROE_MIN:.0f}% 이상")
    metric, years = growth.annual_cagr, growth.annual_cagr_years

    if metric.is_ok:
        a1 = SubCheck("A1", f"연간 EPS {years}년 CAGR", f"{metric.value:+,.1f}%", metric.value >= A_CAGR_MIN)
    else:
        a1 = SubCheck("A1", "연간 EPS CAGR", metric.note or "연간 자료 없음", None)

    series = [(p, annual.value(EPS, p.key)) for p in annual.actual_periods()
              if annual.value(EPS, p.key) is not None]
    if len(series) < 2:
        a2 = SubCheck("A2", "매년 EPS 증가", "확정 연도 2개 미만", None)
    else:
        dips = [str(p.year) for (_, before), (p, after) in zip(series, series[1:]) if after <= before]
        path = " → ".join(f"{p.year} {snap.money(v)}" for p, v in series)
        a2 = SubCheck("A2", "매년 EPS 증가", path + (f" (감소: {', '.join(dips)})" if dips else ""),
                      not dips)

    if roe is None:
        a3 = SubCheck("A3", "ROE", "자료 없음", None)
    else:
        a3 = SubCheck("A3", "ROE (최근 확정 분기)", f"{roe:,.1f}%", roe >= A_ROE_MIN)

    checks = [a1, a2, a3]
    actual = f"EPS {years}년 CAGR {metric.value:+,.1f}%" if metric.is_ok else "—"
    if roe is not None:
        actual += f" · ROE {roe:,.1f}%"
    notes: list[str] = []
    if metric.is_ok:
        notes.append(f"{metric.note}. 확정 연간 데이터가 {years + 1}개년뿐이라 {years}년 CAGR 기준입니다")
    if roe is None:
        notes.append("ROE 데이터가 없어 판단불가 (성장률만으로 합격시키지 않습니다)")
    else:
        notes.append(f"ROE {roe:,.1f}% ({'기준 충족' if roe >= A_ROE_MIN else '기준 미달'})")
    return CanslimItem("A", name, criterion, actual, verdict_of(checks), " · ".join(notes), checks)


def _item_n(snap: Snapshot, stock: pd.DataFrame, newness: Newness | None) -> CanslimItem:
    """N = New. 신고가만이 아니라 '무엇이 새로워졌는가'를 함께 본다.

    오닐의 N 은 신제품·신규 서비스·새 경영진·새로운 산업 환경, 그리고 그 결과로 나타나는
    신고가를 모두 가리킨다. 주가는 결과이고 새로운 재료가 원인이므로 둘 다 확인한다.
    """
    name = "새로운 변화"
    criterion = (f"현재가가 52주 최고가의 {N_NEAR_HIGH_RATIO:.0%} 이상 · "
                 f"새로운 재료(신제품·수주·경영진 등) {N_MATERIAL_MIN}건 이상")

    # ── ① 신고가 (New price high)
    if not snap.price or not snap.high_52w:
        n1 = SubCheck("N1", "52주 최고가 대비", "가격 자료 없음", None)
        ratio = None
        price_part = "가격 데이터가 없습니다"
    else:
        ratio = snap.price / snap.high_52w
        n1 = SubCheck("N1", "52주 최고가 대비", f"{ratio:.0%}", ratio >= N_NEAR_HIGH_RATIO)
        price_part = (f"현재 {snap.money(snap.price)} / 52주 최고 {snap.money(snap.high_52w)}"
                      f"(대비 -{(1 - ratio) * 100:,.1f}%)")
        if "close" in stock:
            since = days_since_new_high(stock["close"])
            if since is not None:
                price_part += (" · 신고가를 방금 갱신했습니다" if since == 0
                               else f" · 마지막 신고가 갱신은 {since}거래일 전")

    # ── ② 새로운 재료 (New product / management / industry)
    if newness is None or not newness.available:
        n2 = SubCheck("N2", "새 재료", "공시·뉴스를 불러오지 못해 확인불가", None)
        count = None
        material_part = "공시·뉴스를 불러오지 못해 새로운 재료를 확인할 수 없었습니다"
    else:
        count = len(newness.items)
        n2 = SubCheck("N2", f"새 재료(최근 {newness.window_days}일)", f"{count}건", count >= N_MATERIAL_MIN)
        if count:
            listed = " / ".join(
                f"[{i.category}] {i.title}({i.date_text}, {i.source})" for i in newness.top(3)
            )
            material_part = (f"최근 {newness.window_days}일 새 재료 {count}건 "
                             f"— {', '.join(newness.categories)} · {listed}")
        else:
            material_part = (f"최근 {newness.window_days}일 공시·뉴스 {newness.scanned}건을 훑었으나 "
                             f"신제품·수주·증설·경영진 변경 같은 새로운 재료를 찾지 못했습니다")

    checks = [n1, n2]
    high_text = f"신고가 {ratio:.0%} {n1.mark}" if ratio is not None else "신고가 —"
    if count is None:
        material_text = "재료 확인불가"
    elif count == 0:
        material_text = "재료 없음 ✗"
    else:
        material_text = f"재료 {count}건 {n2.mark}"
    evidence = (
        f"① 신고가 — {price_part}. ② 새로운 재료 — {material_part}. "
        "※ 재료는 공시·뉴스·리포트 제목을 키워드로 자동 분류한 것이라 사람의 판단을 대신하지 못합니다. "
        "위 제목을 직접 읽어보고 판단하세요."
    )
    return CanslimItem("N", name, criterion, f"{high_text} · {material_text}",
                       verdict_of(checks), evidence, checks)


def _item_s(stock: pd.DataFrame, snap: Snapshot) -> CanslimItem:
    """수급. 반드시 '완결된 거래일'의 거래량만 쓴다 — 장중 부분 거래량을 평균과 비교하면
    거의 항상 불합격으로 나오는 왜곡이 생긴다. (완결 여부는 analyze 에서 이미 걸러져 온다)
    """
    name = "수급"
    criterion = (f"최근 {S_WINDOW}거래일 상승일 거래량 ÷ 하락일 거래량 {S_UPDOWN_RATIO_MIN}배 이상 · "
                 f"최근 {S_RECENT_DAYS}거래일 평균 거래량이 {S_WINDOW}일 평균의 {S_RECENT_RATIO_MIN}배 이상")
    cap_text = f"시가총액 {snap.money_big(snap.market_cap)}" if snap.market_cap else "시가총액 미상"
    float_note = "※ 오닐이 중시하는 유통주식수(float)는 무료로 구할 수 없어 거래량으로 대체했습니다"

    if "close" not in stock or "volume" not in stock:
        df = pd.DataFrame(columns=["close", "volume"])
    else:
        df = stock[["close", "volume"]].dropna()
    if len(df) < S_WINDOW + 1 or float(df["volume"].iloc[-S_WINDOW:].mean()) <= 0:
        return CanslimItem("S", name, criterion, "—", Verdict.UNKNOWN,
                           f"거래량 데이터 {S_WINDOW}거래일 미만 · {cap_text} {float_note}")

    recent = df.iloc[-(S_WINDOW + 1):]
    change = recent["close"].diff().iloc[1:]
    vol = recent["volume"].iloc[1:]
    up, down = float(vol[change > 0].sum()), float(vol[change < 0].sum())
    if up == 0 and down == 0:
        s1 = SubCheck("S1", "상승일/하락일 거래량", "주가 변동 없음", False)
        ratio_text = "—"
    elif down == 0:
        s1 = SubCheck("S1", "상승일/하락일 거래량", f"{up:,.0f}주 / 0주 (하락일 없음)", True)
        ratio_text = "∞"
    else:
        r = up / down
        s1 = SubCheck("S1", "상승일/하락일 거래량", f"{r:.2f}배", r >= S_UPDOWN_RATIO_MIN)
        ratio_text = f"{r:.2f}배"

    avg50 = float(vol.mean())
    avg_recent = float(vol.iloc[-S_RECENT_DAYS:].mean())
    r2 = avg_recent / avg50
    s2 = SubCheck("S2", f"최근 {S_RECENT_DAYS}일 평균 / {S_WINDOW}일 평균", f"{r2:.2f}배", r2 >= S_RECENT_RATIO_MIN)

    checks = [s1, s2]
    evidence = (
        f"상승일 거래량 {up:,.0f}주 vs 하락일 {down:,.0f}주 (최근 {S_WINDOW}거래일) · "
        f"최근 {S_RECENT_DAYS}일 평균 {avg_recent:,.0f}주 / {S_WINDOW}일 평균 {avg50:,.0f}주 · "
        f"{cap_text} {float_note}"
    )
    return CanslimItem("S", name, criterion, f"매집비 {ratio_text} · 최근{S_RECENT_DAYS}일 {r2:.2f}배",
                       verdict_of(checks), evidence, checks)


def _item_l(rs: RelativeStrength, stock: pd.DataFrame, index_name: str, snap: Snapshot) -> CanslimItem:
    name = "주도주 여부"
    criterion = (f"가중 수익률이 {index_name} 대비 +{L_SPREAD_MIN:.0f}%p 이상 · 종목 수익률 양수 · "
                 f"현재가 > 50일선 > 200일선")
    if rs.spread is None:
        l1 = SubCheck("L1", f"{index_name} 대비 초과 수익률", "시세 자료 부족", None)
        l2 = SubCheck("L2", "종목 가중 수익률", "시세 자료 부족", None)
    else:
        l1 = SubCheck("L1", f"{index_name} 대비 초과 수익률", f"{rs.spread:+,.1f}%p", rs.spread >= L_SPREAD_MIN)
        l2 = SubCheck("L2", "종목 가중 수익률", f"{rs.stock:+,.1f}%", rs.stock > 0)

    close = stock["close"].dropna() if "close" in stock else pd.Series(dtype=float)
    ma50, ma200 = moving_average(close, 50), moving_average(close, 200)
    if ma50 is None or ma200 is None or len(close) == 0:
        l3 = SubCheck("L3", "현재가 > 50일선 > 200일선", "200거래일치 자료 부족", None)
    else:
        now = float(close.iloc[-1])
        l3 = SubCheck("L3", "현재가 > 50일선 > 200일선",
                      f"{snap.money(now)} / {snap.money(ma50)} / {snap.money(ma200)}",
                      now > ma50 > ma200)

    checks = [l1, l2, l3]
    lines = [f"{n}: 종목 {sv:+,.1f}% vs 지수 {iv:+,.1f}%"
             for n, sv, iv in rs.detail if sv is not None and iv is not None]
    evidence = ""
    if rs.spread is not None:
        evidence = (f"가중 수익률 종목 {rs.stock:+,.1f}% vs {index_name} {rs.index:+,.1f}% · "
                    + " / ".join(lines) + " · ")
    evidence += ("※ 오닐 원본 RS Rating(1~99 백분위)은 전 종목 자료가 없어 만들 수 없으므로 "
                 f"지수 대비 +{L_SPREAD_MIN:.0f}%p 초과 여부로 대신합니다")
    if rs.coverage:
        evidence += f" ({rs.coverage})"
    actual = f"{index_name} 대비 {rs.spread:+,.1f}%p" if rs.spread is not None else "—"
    return CanslimItem("L", name, criterion, actual, verdict_of(checks), evidence, checks)


def _item_i(stock: pd.DataFrame, snap: Snapshot) -> CanslimItem:
    name = "기관·외국인 수급"
    criterion = (f"외국인 소진율이 {I_TREND_DAYS}거래일 전보다 +{I_FOREIGN_MIN_PP}%p 이상 · "
                 f"기관 누적 순매수 양수")
    series = stock["foreign_rate"].dropna() if "foreign_rate" in stock else pd.Series(dtype=float)
    series = series[series > 0]

    # 미국 종목: 소진율 시계열이 없다. 기관 보유 비중은 시점값이라 '증가 추세'를
    # 판정할 수 없으므로 값만 보여주고 판단불가로 둔다 (있는 척하지 않는다).
    if len(series) == 0 and snap.inst_holding_pct is not None:
        check = SubCheck("I1", "기관 보유 비중 추세", f"현재 {snap.inst_holding_pct:,.1f}% (시점값만 있음)", None)
        return CanslimItem(
            "I", "기관 수급", "기관 보유 비중 증가 (오닐 기준)",
            f"보유 비중 {snap.inst_holding_pct:,.1f}%", Verdict.UNKNOWN,
            f"기관 보유 비중 {snap.inst_holding_pct:,.1f}% — 야후는 현재 시점 값만 제공해 "
            "'증가 중인지'를 판정할 수 없습니다. 수치만 참고하세요",
            [check],
        )

    if len(series) <= I_TREND_DAYS:
        i1 = SubCheck("I1", "외국인 소진율 변화", f"자료 {I_TREND_DAYS}거래일 미만", None)
        change = None
    else:
        now, past = float(series.iloc[-1]), float(series.iloc[-(I_TREND_DAYS + 1)])
        change = now - past
        i1 = SubCheck("I1", f"외국인 소진율 {I_TREND_DAYS}거래일 변화", f"{past:.2f}% → {now:.2f}% ({change:+.2f}%p)",
                      change >= I_FOREIGN_MIN_PP)

    trend = snap.deal_trend
    organ = trend["organ_net"].dropna() if not trend.empty and "organ_net" in trend else pd.Series(dtype=float)
    if len(organ) == 0:
        i2 = SubCheck("I2", "기관 누적 순매수", "자료 없음", None)
        deal_text = ""
    else:
        total = float(organ.sum())
        i2 = SubCheck("I2", f"기관 누적 순매수(최근 {len(organ)}일)", f"{total:+,.0f}주", total > 0)
        foreign_total = float(trend["foreigner_net"].dropna().sum()) if "foreigner_net" in trend else 0.0
        deal_text = f" · 최근 {len(organ)}일 누적 순매수: 기관 {total:+,.0f}주, 외국인 {foreign_total:+,.0f}주"

    checks = [i1, i2]
    evidence = ""
    if change is not None:
        evidence = f"외국인 소진율 {past:.2f}% → {now:.2f}% ({change:+.2f}%p, 최근 {I_TREND_DAYS}거래일)"
    else:
        evidence = f"외국인 소진율 데이터가 {I_TREND_DAYS}거래일 미만입니다"
    evidence += deal_text + " ※ 기관 보유 '비중'은 무료로 구할 수 없어 외국인 소진율 추세와 기관 순매수로 대체했습니다"
    actual = f"{change:+.2f}%p" if change is not None else "—"
    if len(organ):
        actual += f" · 기관 {float(organ.sum()):+,.0f}주"
    return CanslimItem("I", name, criterion, actual, verdict_of(checks), evidence, checks)


def _item_m(index: pd.DataFrame, index_name: str) -> CanslimItem:
    name = "시장 방향"
    criterion = (f"{index_name}가 50일선·200일선 위 · 50일선 > 200일선 · "
                 f"최근 {M_DIST_WINDOW}거래일 분산일 {M_DIST_MAX}일 미만")
    close = index["close"].dropna() if "close" in index else pd.Series(dtype=float)
    ma50, ma200 = moving_average(close, 50), moving_average(close, 200)

    if len(close) == 0 or ma50 is None:
        return CanslimItem("M", name, criterion, "—", Verdict.UNKNOWN, "지수 데이터 부족")

    now = float(close.iloc[-1])
    above50 = now > ma50
    if ma200 is None:
        m1 = SubCheck("M1", "지수 > 50일선·200일선", f"50일선 {'위' if above50 else '아래'} · 200일선 자료 부족",
                      False if not above50 else None)
        m2 = SubCheck("M2", "50일선 > 200일선", "200일선 자료 부족", None)
        state = f"50일선 {'위' if above50 else '아래'}"
        level_text = f"{index_name} {now:,.2f} / 50일선 {ma50:,.2f} · 200일선은 데이터 부족"
    else:
        above200 = now > ma200
        m1 = SubCheck("M1", "지수 > 50일선·200일선",
                      f"50일선 {'위' if above50 else '아래'} · 200일선 {'위' if above200 else '아래'}",
                      above50 and above200)
        m2 = SubCheck("M2", "50일선 > 200일선", f"{ma50:,.2f} vs {ma200:,.2f}", ma50 > ma200)
        state = f"50일선 {'위' if above50 else '아래'} · 200일선 {'위' if above200 else '아래'}"
        level_text = f"{index_name} {now:,.2f} / 50일선 {ma50:,.2f} / 200일선 {ma200:,.2f}"

    dist = distribution_days(index)
    if dist is None:
        m3 = SubCheck("M3", f"분산일(최근 {M_DIST_WINDOW}일)", "지수 거래량 자료 부족", None)
    else:
        m3 = SubCheck("M3", f"분산일(최근 {M_DIST_WINDOW}일)", f"{dist}일", dist < M_DIST_MAX)
        state += f" · 분산일 {dist}일"

    checks = [m1, m2, m3]
    evidence = (
        f"{level_text}. 분산일은 지수가 {M_DIST_DROP_PCT}% 이상 빠졌는데 거래량은 전일보다 많은 날 "
        f"(큰손이 파는 날)로, {M_DIST_MAX}일 이상 쌓이면 오닐은 조정 진입으로 봤습니다. "
        "주식의 4분의 3이 시장 방향을 따라갑니다"
    )
    return CanslimItem("M", name, criterion, state, verdict_of(checks), evidence, checks)


# ------------------------------------------------------------------ 종합

def analyze(
    snap: Snapshot,
    quarterly: FinancialTable,
    annual: FinancialTable,
    growth: GrowthRates,
    stock_df: pd.DataFrame,
    index_df: pd.DataFrame,
    index_name: str = "KOSPI",
    newness: Newness | None = None,
) -> tuple[CanslimResult, RelativeStrength]:
    latest_roe = next(
        (quarterly.value("ROE", p.key) for p in reversed(quarterly.actual_periods())
         if quarterly.value("ROE", p.key) is not None),
        None,
    )
    rs = relative_strength(stock_df, index_df)

    result = CanslimResult(items=[
        _item_c(quarterly, growth, snap),
        _item_a(growth, annual, latest_roe, snap),
        _item_n(snap, stock_df, newness),
        _item_s(stock_df, snap),
        _item_l(rs, stock_df, index_name, snap),
        _item_i(stock_df, snap),
        _item_m(index_df, index_name),
    ])
    return result, rs
