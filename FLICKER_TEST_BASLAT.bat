@echo off
setlocal
set "EDIZ_FLICKER_HOME=%~dp0"
if not exist "%EDIZ_FLICKER_HOME%dist\subtitle-flicker-fix-20261117\EdizGameTranslator\EdizGameTranslator.exe" set "EDIZ_FLICKER_HOME=%~dp0..\..\"
if not exist "%EDIZ_FLICKER_HOME%dist\subtitle-flicker-fix-20261117\EdizGameTranslator\EdizGameTranslator.exe" (
  echo Flicker test EXE bulunamadi. docs/reports/ALTYAZI_FLICKER.md dosyasina bakin.
  pause
  exit /b 1
)
set "EDIZ_CONFIG_DIR=%EDIZ_FLICKER_HOME%local-data\subtitle-flicker-fix-profile"
cd /d "%EDIZ_FLICKER_HOME%"
"%EDIZ_FLICKER_HOME%dist\subtitle-flicker-fix-20261117\EdizGameTranslator\EdizGameTranslator.exe"
endlocal
