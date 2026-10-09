"""코스피·코스닥 전 종목 CANSLIM 스크리너 — 웹앱과 분리된 실행 파일.

실행:  screen.bat 더블클릭   (또는  .venv\\Scripts\\python.exe screen.py [옵션])

  --market KOSPI|KOSDAQ|ALL   대상 시장 (기본 ALL)
  --limit N                   시가총액 상위 N개만 (시험용)
  --min-cap 억원               시가총액 하한 (기본 0)
  --no-deep                   2차(정밀 CANSLIM)를 건너뛴다

결과: screens/CANSLIM_스크리닝_YYYY-MM-DD.xlsx — 끝나면 자동으로 열린다.
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
    p.add_argument("--market", choices=["KOSPI", "KOSDAQ", "ALL"], default="ALL")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--min-cap", type=float, default=0.0, help="시가총액 하한 (억원)")
    p.add_argument("--no-deep", action="store_true")
    p.add_argument("--no-open", action="store_true", help="끝난 뒤 엑셀을 자동으로 열지 않는다")
    return p.parse_args(argv)


def output_path(today: dt.date | None = None) -> Path:
    today = today or dt.date.today()
    path = OUT_DIR / f"CANSLIM_스크리닝_{today:%Y-%m-%d}.xlsx"
    n = 2
    while path.exists():  # 같은 날 여러 번 돌리면 덮어쓰지 않는다 (열려 있으면 저장이 막힘)
        path = OUT_DIR / f"CANSLIM_스크리닝_{today:%Y-%m-%d}_{n}.xlsx"
        n += 1
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    markets = screener.MARKETS if args.market == "ALL" else (args.market,)
    result = screener.run(markets=markets, limit=args.limit, min_cap=args.min_cap,
                          deep=not args.no_deep)
    path = write_excel(result, output_path())

    deep_ok = sum(1 for d in result.deep.values() if d.qualified)
    print()
    print(f"완료 — 통과 {len(result.by_status(screener.PASS))} · 근접 {len(result.by_status(screener.NEAR))} · "
          f"CANSLIM 충족 {deep_ok}")
    print(f"결과 파일: {path}")
    if not args.no_open and sys.platform == "win32":
        os.startfile(path)  # noqa: S606 — 사용자가 보려고 만든 파일
    return 0


if __name__ == "__main__":
    sys.exit(main())
