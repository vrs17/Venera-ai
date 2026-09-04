<#
.SYNOPSIS
    Manba kodni WSL papkasidan Windows diskiga ko'chiradi.

.DESCRIPTION
    Loyiha WSL ichida turadi, lekin venv va PyInstaller UNC yo'lda
    (\\wsl.localhost\...) ishonchsiz ishlaydi. Shu skript kodni C: ga
    ko'chiradi va u yerda venv yaratadi.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\sync_to_windows.ps1
#>
param(
    [string]$Source      = "\\wsl.localhost\Ubuntu-22.04\home\makhmud\Venera  Desktop AI Assistant",
    [string]$Destination = "C:\venera",
    [switch]$SkipVenv
)

$ErrorActionPreference = "Stop"

Write-Host "Manba : $Source"
Write-Host "Maqsad: $Destination`n"

if (-not (Test-Path $Source)) { throw "Manba papka topilmadi: $Source" }

robocopy $Source $Destination /MIR /NFL /NDL /NJH /NJS /NP `
    /XD .git .venv venv __pycache__ build dist .pytest_cache `
    /XF *.pyc *.log | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy xatosi: $LASTEXITCODE" }
Write-Host "Fayllar ko'chirildi."

if ($SkipVenv) { return }

Set-Location $Destination
if (-not (Test-Path ".venv")) {
    Write-Host "`nVirtual muhit yaratilmoqda..."
    py -3 -m venv .venv
}
Write-Host "Bog'liqliklar o'rnatilmoqda..."
& ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
& ".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt --quiet

Write-Host "`nTayyor. Ishga tushirish:"
Write-Host "    cd $Destination"
Write-Host "    .venv\Scripts\python.exe -m venera --check"
Write-Host "    .venv\Scripts\python.exe -m venera --console"
