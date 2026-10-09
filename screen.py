"""코스피·코스닥 전 종목 CANSLIM 스크리너 — 웹앱과 분리된 실행 파일.

실행:  screen.bat 더블클릭   (또는  .venv\\Scripts\\python.exe screen.py [옵션])

  --market KOSPI|KOSDAQ|ALL|US  대상 시장 (기본 ALL = 코스피+코스닥, US = 미국)
  --limit N                   시가총액 상위 N개만 (시험용)
  --min-cap N                 시가총액 하한 — 한국은 억원(기본 0), 미국은 억 달러(기본 20 = 20억 달러)
  --no-deep                   2차(정밀 CANSLIM)를 건너뛴다

결과: screens/CANSLIM_스크리닝_YYYY-MM-DD.xlsx (미국은 CANSLIM_스크리닝_US_…) — 끝나면 자동으로 열린다.
첫 실행은 30~45분 걸린다. 같은 날 다시 돌리면 저장된 자료(24시간)를 써서 훨씬 빠르다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from src import screener
from src.screen_excel import write_excel

OUT_DIR = Path(__file__).resolve().parent / "screens"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="코스피·코스닥 CANSLIM 스크리너")
    p.add_argument("--market", choices=["KOSPI", "KOSDAQ", "ALL", "US"], default="ALL")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--min-cap", type=float, default=None,
                   help="시가총액 하한 — 한국 억원(기본 0), 미국 억 달러(기본 20)")
    p.add_argument("--no-deep", action="store_true")
    p.add_argument("--no-open", action="store_true", help="끝난 뒤 엑셀을 자동으로 열지 않는다")
    return p.parse_args(argv)


US_DEFAULT_MIN_CAP = 20.0   # 억 달러 (= 20억 달러)


def output_path(today: dt.date | None = None, us: bool = False) -> Path:
    today = today or dt.date.today()
    stem = f"CANSLIM_스크리닝_{'US_' if us else ''}{today:%Y-%m-%d}"
    path = OUT_DIR / f"{stem}.xlsx"
    n = 2
    while path.exists():  # 같은 날 여러 번 돌리면 덮어쓰지 않는다 (열려 있으면 저장이 막힘)
        path = OUT_DIR / f"{stem}_{n}.xlsx"
        n += 1
    return path


def min_cap_base(market: str, min_cap: float | None) -> float:
    """화면 단위(한국 억원, 미국 억 달러) → 원값 (원·달러)."""
    if market == "US":
        return (US_DEFAULT_MIN_CAP if min_cap is None else min_cap) * 1e8
    return (min_cap or 0.0) * 1e8


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    us = args.market == "US"
    markets = screener.MARKETS if args.market == "ALL" else (args.market,)
    result = screener.run(markets=markets, limit=args.limit,
                          min_cap=min_cap_base(args.market, args.min_cap), deep=not args.no_deep)
    path = write_excel(result, output_path(us=us), currency="USD" if us else "KRW")

    deep_ok = sum(1 for d in result.deep.values() if d.qualified or (us and d.qualified_ex_i))
    print()
    print(f"완료 — 통과 {len(result.by_status(screener.PASS))} · 근접 {len(result.by_status(screener.NEAR))} · "
          f"CANSLIM 충족 {deep_ok}")
    print(f"결과 파일: {path}")
    if not args.no_open and sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — 사용자가 보려고 만든 파일
    return 0


if __name__ == "__main__":
    sys.exit(main())
