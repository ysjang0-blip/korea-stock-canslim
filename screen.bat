@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [!] 가상환경이 없습니다. 먼저 아래를 실행하세요:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

echo 코스피·코스닥 전 종목 CANSLIM 스크리닝을 시작합니다.
echo 첫 실행은 30~45분 걸립니다. 중간에 멈추려면 Ctrl+C (그때까지 결과는 저장됩니다).
echo.
".venv\Scripts\python.exe" -X utf8 screen.py %*
pause
