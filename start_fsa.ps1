# Field Service AI - Ein-Klick-Start (PowerShell-Variante von start_fsa.bat)
#
#   .\start_fsa.ps1                          Excel: data\KI_gestuetzte_Planung.xlsx
#   .\start_fsa.ps1 -Xlsx "C:\Pfad\x.xlsx"   andere Excel-Datei
#   .\start_fsa.ps1 -Lan                     zusaetzlich im WLAN erreichbar
#
# Falls Skripte blockiert sind:
#   powershell -ExecutionPolicy Bypass -File .\start_fsa.ps1
param(
    [string]$Xlsx = "",
    [switch]$Lan
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
if ($Xlsx -eq "") { $Xlsx = Join-Path $PSScriptRoot "data\KI_gestuetzte_Planung.xlsx" }

function Stop-Mit-Fehler([string]$Text) {
    Write-Host ""
    Write-Host "FEHLER: $Text" -ForegroundColor Red
    Write-Host "*** Start abgebrochen. Meldung oben lesen und beheben. ***" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Field Service AI - Start ===" -ForegroundColor Cyan

Write-Host "[1/5] Python-Umgebung pruefen ..."
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Stop-Mit-Fehler "Virtuelle Umgebung 'venv' nicht gefunden. Einmalig: python -m venv venv; venv\Scripts\pip install -r requirements.txt"
}
& $py --version | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Mit-Fehler "Python in venv ist nicht lauffaehig. venv neu anlegen." }
Write-Host "      OK"

Write-Host "[2/5] Excel-Datei pruefen ..."
if (-not (Test-Path $Xlsx)) {
    Stop-Mit-Fehler ("Excel-Datei nicht gefunden: $Xlsx`n  Bitte den SMax-Export als 'KI_gestuetzte_Planung.xlsx' nach " +
        (Join-Path $PSScriptRoot "data\") + " kopieren oder den Pfad mit -Xlsx angeben.")
}
Write-Host "      OK: $Xlsx"

Write-Host "[3/5] SMax-Excel importieren (Pruefung + Cache) ..."
& $py -m api.smax_cache $Xlsx
if ($LASTEXITCODE -ne 0) { Stop-Mit-Fehler "Import fehlgeschlagen - es wird NICHT mit halben Daten weitergemacht." }

Write-Host "[4/5] Dashboard erzeugen (Echtdaten -> lokal/dashboard.html, nicht im Repo) ..."
& $py -m reporting.dashboard
if ($LASTEXITCODE -ne 0) { Stop-Mit-Fehler "Dashboard-Erzeugung fehlgeschlagen - Abbruch." }

Write-Host "[5/5] Server starten und Browser oeffnen ..."
Start-Job -ScriptBlock { Start-Sleep -Seconds 2; Start-Process "http://localhost:8000/dashboard.html" } | Out-Null
$serverArgs = @("fsa_server.py")
if ($Lan) { $serverArgs += "--lan" }
& $py @serverArgs
if ($LASTEXITCODE -ne 0) { Stop-Mit-Fehler "Server konnte nicht gestartet werden (Port 8000 belegt?)." }
