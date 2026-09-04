<#
.SYNOPSIS
    Venera AI Assistant ni .exe ga yig'adi.

.DESCRIPTION
    Natija: dist\Venera\Venera.exe
    Shundan keyin packaging\windows\install.ps1 ni ishga tushiring.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
#>
# Toza yig'ish STANDART. `build\` keshi eski bayt-kodni saqlab qolishi mumkin:
# manba Linux'da yasalgan arxivdan chiqarilganda fayllarning mtime'i eski bo'ladi
# va PyInstaller ularni "o'zgarmagan" deb hisoblab, ESKI VERSIYANI qayta yig'adi.
# Natijada 0.2.8 deb nomlangan o'rnatuvchi ichida 0.2.5 ilovasi ketadi - bu
# jimgina sodir bo'ladi va faqat foydalanuvchi mashinasida bilinadi.
# Tez ishlab chiqish uchun -NoClean bering.
param([switch]$NoClean)

$ErrorActionPreference = "Stop"
# packaging/windows/ ichida turibmiz, shuning uchun ikki daraja yuqoriga.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

Write-Host "=== Venera AI Assistant - build ===" -ForegroundColor Cyan
Write-Host "Loyiha: $root`n"

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "py" }
Write-Host "Python: $python"

if (-not $NoClean) {
    Write-Host "Eski build tozalanmoqda (kesh eski versiyani saqlab qolmasligi uchun)..."
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
& $python -m PyInstaller packaging\windows\venera.spec --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller xatosi" }

$exe = Join-Path $root "dist\Venera\Venera.exe"
if (-not (Test-Path $exe)) { throw "exe topilmadi: $exe" }

# Yuqoridagi $version MANBADAN o'qilgan - u yig'ilgan fayl haqida hech narsa
# aytmaydi. Shuning uchun .exe ning O'ZIDAN so'raymiz. Bu tekshiruvsiz eski
# kesh bilan yig'ilgan ilova jimgina tarqatilib ketardi.
$built = (& $exe --version 2>&1 | Out-String).Trim()
if ($built -notmatch [regex]::Escape($version)) {
    throw @"
VERSIYA MOS KELMADI - build to'xtatildi.
  manbada          : $version
  yig'ilgan .exe da: $built
Sabab odatda eski build keshi. Qo'lda tozalang:
  Remove-Item -Recurse -Force build, dist
"@
}
Write-Host "     Yig'ilgan .exe tasdiqladi: $built" -ForegroundColor Green

$size = [math]::Round((Get-ChildItem "dist\Venera" -Recurse |
                       Measure-Object -Property Length -Sum).Sum / 1MB, 1)
Write-Host "`nTayyor:" -ForegroundColor Green
Write-Host "  $exe"
Write-Host "  Versiya: $version"
Write-Host "  Hajmi: $size MB"
Write-Host "`nO'rnatish uchun:"
Write-Host "  powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1" -ForegroundColor Yellow
