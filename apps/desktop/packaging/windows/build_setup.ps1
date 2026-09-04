<#
.SYNOPSIS
    Bitta faylli o'rnatuvchi yasaydi: Venera-AI-Assistant-Setup.exe

.DESCRIPTION
    Natija: dist\Venera-AI-Assistant-Setup.exe
    Shu bitta faylni boshqa kompyuterga ko'chirasiz va ikki marta bosasiz.
    Maqsad kompyuterda Python yoki boshqa dastur kerak emas.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\build_setup.ps1
#>
param(
    [switch]$SkipAppBuild,
    [string[]]$UpdateUrl = @()
)

$ErrorActionPreference = "Stop"
# packaging/windows/ ichida turibmiz, shuning uchun ikki daraja yuqoriga.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "py" }

Write-Host "=== O'rnatuvchi yig'ilmoqda ===" -ForegroundColor Cyan

if (-not $SkipAppBuild) {
    Write-Host "`n1/2  Ilova yig'ilmoqda..."
    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Ilova yig'ilmadi" }
} else {
    Write-Host "`n1/2  Ilova build'i o'tkazib yuborildi (-SkipAppBuild)"
    if (-not (Test-Path "dist\Venera\Venera.exe")) {
        throw "dist\Venera topilmadi - avval build.ps1 ni ishga tushiring"
    }
}

$urlFile = Join-Path $PSScriptRoot "update_url.txt"
if ($UpdateUrl.Count -gt 0) {
    # `powershell -File` orqali kelganda massiv bitta satrga aylanib qolishi
    # mumkin, shuning uchun vergul va nuqta-vergulni ham ajratamiz.
    $clean = $UpdateUrl |
        ForEach-Object { $_ -split '[,;]' } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
    Write-Host "`nYangilanish manzillari yopishtirilmoqda:"
    $clean | ForEach-Object { Write-Host "  $_" }
    [System.IO.File]::WriteAllLines($urlFile, [string[]]$clean)
} elseif (Test-Path $urlFile) {
    $existing = (Get-Content $urlFile) | Where-Object { $_.Trim() }
    if ($existing) { Write-Host "`nYopishtirilgan manzillar: $($existing -join ', ')" }
}

Write-Host "`n2/2  O'rnatuvchi yig'ilmoqda..."
& $python -m PyInstaller packaging\windows\setup.spec --noconfirm --log-level WARN
if ($LASTEXITCODE -ne 0) { throw "PyInstaller xatosi" }

$setup = Join-Path $root "dist\Venera-AI-Assistant-Setup.exe"
if (-not (Test-Path $setup)) { throw "Natija topilmadi: $setup" }

$sizeMb = [math]::Round((Get-Item $setup).Length / 1MB, 1)
$hash = (Get-FileHash $setup -Algorithm SHA256).Hash

Write-Host "`nTayyor:" -ForegroundColor Green
Write-Host "  $setup"
Write-Host "  Hajmi : $sizeMb MB"
Write-Host "  SHA256: $hash"
Write-Host "`nBoshqa kompyuterda: shu faylni ko'chiring va ikki marta bosing."
if (Test-Path $urlFile) {
    $baked = (Get-Content $urlFile) | Where-Object { $_.Trim() }
    if ($baked) {
        Write-Host "Yangilanish manzillari ichiga yozilgan:" -ForegroundColor Green
        $baked | ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
    }
}
Write-Host "Jim o'rnatish (IT uchun): Venera-AI-Assistant-Setup.exe /S"
