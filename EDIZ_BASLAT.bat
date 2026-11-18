@echo off
setlocal
set "EDIZ_APP_HOME=%~dp0"
if not exist "%EDIZ_APP_HOME%dist\visual-stabilization-20261118\EdizGameTranslator\EdizGameTranslator.exe" (
  if exist "%~dp0..\..\GORSEL_STABILIZASYON_BASLAT.bat" set "EDIZ_APP_HOME=%~dp0..\..\"
)
if not exist "%EDIZ_APP_HOME%dist\visual-stabilization-20261118\EdizGameTranslator\EdizGameTranslator.exe" (
  echo Gorsel stabilizasyon EXE bulunamadi. PROJE_DURUMU.md dosyasina bakin.
  pause
  exit /b 1
)
if not exist "%EDIZ_APP_HOME%local-data\visual-stabilization-profile\settings.json" (
  echo Mevcut gorsel stabilizasyon profili bulunamadi. Ayarlar olusturulmadi.
  pause
  exit /b 1
)
echo Ediz Game Translator - Gorsel Stabilizasyon - a5572cb
echo PS5'te denenmis gorsel surum. Bilinen altyazi sorunlari devam ediyor.
echo Once acik ceviri uygulamasini kapatin. Ayrintilar: PROJE_DURUMU.md
set "EDIZ_CONFIG_DIR=%EDIZ_APP_HOME%local-data\visual-stabilization-profile"
set "PYTHONUTF8=1"
cd /d "%EDIZ_APP_HOME%"
"%EDIZ_APP_HOME%dist\visual-stabilization-20261118\EdizGameTranslator\EdizGameTranslator.exe"
endlocal
