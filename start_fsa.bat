@echo off
rem ==========================================================================
rem  Field Service AI - Ein-Klick-Start (Modul 1)
rem  Ablauf: SMax-Excel importieren -> Dashboard erzeugen -> lokalen Server
rem          starten -> Browser oeffnen.
rem
rem  Aufruf:
rem    start_fsa.bat                         (Excel: data\KI_gestuetzte_Planung.xlsx)
rem    start_fsa.bat "C:\Pfad\export.xlsx"   (andere Excel-Datei)
rem    start_fsa.bat --lan                   (zusaetzlich im WLAN erreichbar)
rem  Falls .bat blockiert ist: start_fsa.ps1 verwenden.
rem ==========================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

set "LAN="
set "XLSX=%~dp0data\KI_gestuetzte_Planung.xlsx"
for %%A in (%*) do (
  if /i "%%~A"=="--lan" (set "LAN=--lan") else (set "XLSX=%%~A")
)

echo.
echo === Field Service AI - Start ===
echo.

echo [1/5] Python-Umgebung pruefen ...
if exist "venv\Scripts\activate.bat" (
  call "venv\Scripts\activate.bat"
) else (
  echo FEHLER: Virtuelle Umgebung 'venv' nicht gefunden.
  echo   Einmalig einrichten:  python -m venv venv ^& venv\Scripts\pip install -r requirements.txt
  goto :fehler
)
python --version >nul 2>&1
if errorlevel 1 (
  echo FEHLER: Python ist nicht erreichbar. Bitte Python 3.12 installieren bzw. venv neu anlegen.
  goto :fehler
)
echo       OK

echo [2/5] Excel-Datei pruefen ...
if not exist "%XLSX%" (
  echo FEHLER: Excel-Datei nicht gefunden: %XLSX%
  echo   Bitte den SMax-Export als 'KI_gestuetzte_Planung.xlsx' in den Ordner
  echo   %~dp0data\
  echo   kopieren - oder den Pfad als Parameter angeben:  start_fsa.bat "C:\Pfad\datei.xlsx"
  goto :fehler
)
echo       OK: %XLSX%

echo [3/5] SMax-Excel importieren (Pruefung + Cache) ...
python -m api.smax_cache "%XLSX%"
if errorlevel 1 (
  echo.
  echo FEHLER im Import - es wird NICHT mit halben Daten weitergemacht.
  goto :fehler
)

echo.
echo [4/5] Dashboard erzeugen ...
python -m reporting.dashboard
if errorlevel 1 (
  echo.
  echo FEHLER bei der Dashboard-Erzeugung - Abbruch.
  goto :fehler
)

echo.
echo [5/5] Server starten und Browser oeffnen ...
start "" cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8000/dashboard.html"
python fsa_server.py %LAN%
if errorlevel 1 goto :fehler
goto :ende

:fehler
echo.
echo *** Start abgebrochen. Meldung oben lesen und beheben. ***
pause
exit /b 1

:ende
endlocal
