@echo off
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv-win\Scripts\python.exe" (
    ".venv-win\Scripts\python.exe" runtime_check.py
    if not errorlevel 1 goto install
    echo Mevcut .venv-win uyumsuz. Klasoru yeniden adlandirip tekrar dene.
    goto failed
)
py -3.12 runtime_check.py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -m venv .venv-win
    goto created
)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" runtime_check.py
    if not errorlevel 1 (
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv-win
        goto created
    )
)
python runtime_check.py
if errorlevel 1 goto failed
python -m venv .venv-win
:created
if errorlevel 1 goto failed
if not exist ".venv-win\Scripts\python.exe" goto failed
:install
".venv-win\Scripts\python.exe" runtime_check.py
if errorlevel 1 goto failed
".venv-win\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv-win\Scripts\python.exe" -m pip check
if errorlevel 1 goto failed
echo Kurulum tamamlandi. BASLAT.bat ile acabilirsin.
exit /b 0
:failed
echo HATA: Resmi Windows CPython 3.12 x64 ve internet gerekir.
echo https://www.python.org/downloads/windows/
echo Eski MSYS2 .venv klasoru kullanilmaz veya silinmez.
pause
exit /b 1
