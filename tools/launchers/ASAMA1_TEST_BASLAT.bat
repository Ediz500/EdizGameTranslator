@echo off
setlocal
rem Asama 1 (tek replik, tek ceviri) TEST surumu.
rem EDIZ_BASLAT.bat ve dist\visual-stabilization-20261118 DEGISTIRILMEZ.
rem Ayri EXE ve ayri profil kullanir; eski profil/veritabani kullanilmaz.
set "EDIZ_APP_HOME=%~dp0..\..\..\..\"
set "EDIZ_TEST_EXE=%EDIZ_APP_HOME%dist\stage1-single-translation-20261117\EdizGameTranslator\EdizGameTranslator.exe"
set "EDIZ_TEST_PROFILE=%EDIZ_APP_HOME%local-data\stage1-single-translation-profile"
if not exist "%EDIZ_TEST_EXE%" (
  echo Asama 1 test EXE bulunamadi: %EDIZ_TEST_EXE%
  pause
  exit /b 1
)
if not exist "%EDIZ_TEST_PROFILE%\settings.json" (
  echo Asama 1 test profili bulunamadi: %EDIZ_TEST_PROFILE%
  pause
  exit /b 1
)
echo Ediz Game Translator - ASAMA 1 TEST SURUMU
echo Once acik olan diger Ediz Game Translator penceresini kapatin.
echo Uygulama acildiktan sonra Ceviriyi Baslat; OBS Browser Source otomatik yenilenir.
set "EDIZ_CONFIG_DIR=%EDIZ_TEST_PROFILE%"
set "PYTHONUTF8=1"
cd /d "%EDIZ_APP_HOME%"
"%EDIZ_TEST_EXE%"
endlocal
