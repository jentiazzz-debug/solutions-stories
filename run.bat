@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist .venv (
    py -3 -m venv .venv || goto :fail
    .venv\Scripts\python -m pip install -U pip
    .venv\Scripts\pip install -r requirements.txt || goto :fail
)

if not exist .env (
    echo Нет .env — скопируй .env.example в .env и впиши BOT_TOKEN.
    pause
    exit /b 1
)

.venv\Scripts\python main.py
pause
exit /b 0

:fail
echo Не удалось поставить зависимости.
pause
exit /b 1
