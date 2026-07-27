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

echo 잠시 후 브라우저가 열립니다. 종료하려면 이 창에서 Ctrl+C 를 누르세요.
start "" http://localhost:8501
".venv\Scripts\python.exe" -m streamlit run app.py
pause
