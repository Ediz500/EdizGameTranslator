@echo off
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv-win\Scripts\python.exe" (
    echo Once KURULUM.bat dosyasini calistir.
    pause
    exit /b 1
)
".venv-win\Scripts\python.exe" runtime_check.py
if errorlevel 1 exit /b 1
".venv-win\Scripts\python.exe" launcher.py
if errorlevel 1 (
    echo.
    echo Uygulama hata ile kapandi. Hata mesaji yukarida.
    pause
)
