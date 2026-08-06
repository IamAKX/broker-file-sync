<#
.SYNOPSIS
  Local Windows build — same steps as .github/workflows/ci.yml's
  build-windows job, run manually instead of on GitHub Actions (see
  docs/ for why: the CI minutes quota ran out). Run this on a Windows
  machine, in PowerShell, from anywhere — it cd's to its own folder.

.PARAMETER Version
  Written into version.py as APP_VERSION before building (e.g. "0.5.0").
  Omit to leave version.py as whatever is already committed.

.EXAMPLE
  .\build_windows.ps1
  .\build_windows.ps1 -Version 0.5.0
#>
param(
    [string]$Version
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}
& ".venv\Scripts\Activate.ps1"

Write-Host "Installing dependencies..."
python -m pip install --upgrade pip | Out-Null
pip install -r requirements.txt
pip install openpyxl xlrd pyinstaller pywin32

if ($Version) {
    Write-Host "Writing version.py (APP_VERSION = `"$Version`")..."
    Set-Content -Path version.py -Value "APP_VERSION = `"$Version`""
}

Write-Host "Building (PyInstaller)..."
pyinstaller --windowed --onedir --name "BrokerFileSync" `
    --icon "assets\icons\app_logo.ico" `
    --add-data "assets;assets" `
    --add-data "screens;screens" `
    --add-data "services;services" `
    --add-data "components;components" `
    --add-data "font_scale.py;." `
    --collect-data openpyxl `
    --collect-all win32com `
    --collect-all pythoncom `
    --hidden-import win32com `
    --hidden-import win32com.client `
    --hidden-import win32com.server `
    --hidden-import pythoncom `
    --hidden-import pywintypes `
    --hidden-import win32api `
    --hidden-import win32con `
    --manifest "windows_dpi.manifest" `
    main.py

Write-Host "Zipping build..."
$zipPath = "dist\BrokerFileSync-windows.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath }
Compress-Archive -Path "dist\BrokerFileSync\*" -DestinationPath $zipPath

Write-Host "Copying to Desktop..."
$Desktop = [Environment]::GetFolderPath("Desktop")
$DestFolder = Join-Path $Desktop "BrokerFileSync"
if (Test-Path $DestFolder) { Remove-Item -Recurse -Force $DestFolder }
Copy-Item -Recurse "dist\BrokerFileSync" $DestFolder
Copy-Item $zipPath (Join-Path $Desktop "BrokerFileSync-windows.zip") -Force

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  App folder: $DestFolder"
Write-Host "  Exe:        $DestFolder\BrokerFileSync.exe"
Write-Host "  Zip:        $Desktop\BrokerFileSync-windows.zip"
