@echo off
set "PYTHONUTF8=1"
cd /d "%~dp0"
".venv-win\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
".venv-win\Scripts\python.exe" -m PyInstaller --noconfirm EdizGameTranslator.spec
if errorlevel 1 exit /b 1
copy /y WINDOWS_KULLANIM.txt dist\EdizGameTranslator\KULLANIM.txt >nul
echo dist\EdizGameTranslator\EdizGameTranslator.exe hazir. Tum klasoru birlikte tutun.
