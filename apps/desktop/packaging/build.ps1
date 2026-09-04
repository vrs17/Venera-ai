<#
.SYNOPSIS
    Venera AI Assistant ni .exe ga yig'adi.

.DESCRIPTION
    Natija: dist\Venera\Venera.exe
    Shundan keyin packaging\install.ps1 ni ishga tushiring.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#>
param([switch]$Clean)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "=== Venera AI Assistant - build ===" -ForegroundColor Cyan
Write-Host "Loyiha: $root`n"

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "py" }
Write-Host "Python: $python"

if ($Clean) {
    Write-Host "Eski build tozalanmoqda..."
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
}

Write-Host "`n1/4  Bog'liqliklar..."
& $python -m pip install -r requirements-dev.txt --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install xatosi" }

Write-Host "2/4  Versiya va ikonka..."
$version = (& $python tools\sync_version.py).Trim()
Write-Host "     Versiya: $version"
& $python tools\make_icon.py

Write-Host "3/4  Testlar..."
& $python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw "Testlar o'tmadi - build to'xtatildi" }

Write-Host "4/4  PyInstaller..."
& $python -m PyInstaller packaging\venera.spec --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller xatosi" }

$exe = Join-Path $root "dist\Venera\Venera.exe"
if (-not (Test-Path $exe)) { throw "exe topilmadi: $exe" }

$size = [math]::Round((Get-ChildItem "dist\Venera" -Recurse |
                       Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "`nTayyor:" -ForegroundColor Green
Write-Host "  $exe"
Write-Host "  Versiya: $version"
Write-Host "  Hajmi: $size MB"
Write-Host "`nO'rnatish uchun:"
Write-Host "  powershell -ExecutionPolicy Bypass -File packaging\install.ps1" -ForegroundColor Yellow
