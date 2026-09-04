<#
.SYNOPSIS
    Yangi versiyani nashr qiladi: Setup.exe + version.json ni tarqatish joyiga qo'yadi.

.DESCRIPTION
    O'rnatilgan ilovalar shu joydagi version.json ni o'qib, yangi versiya
    borligini biladi va foydalanuvchi tasdiqlasa o'zini yangilaydi.

    Tarqatish joyi uch xil bo'lishi mumkin:
      \\fileserver\venera\assistant   tarmoq papkasi (bankda eng oson)
      C:\inetpub\updates\venera            ichki HTTP serverning papkasi
      C:\updates\venera                    lokal papka (sinov uchun)

    Foydalanuvchi kompyuterlaridagi config.yaml da shu manzil ko'rsatiladi:
      update:
        url: "\\fileserver\venera\assistant\version.json"

.PARAMETER Target
    Fayllar qo'yiladigan papka.

.PARAMETER Notes
    Foydalanuvchiga ko'rinadigan qisqa izoh ("Nima o'zgardi").

.PARAMETER Mandatory
    Majburiy yangilanish belgisi.

.PARAMETER MinVersion
    Shu versiyadan eskisi to'g'ridan-to'g'ri yangilana olmaydi (qo'lda o'rnatish kerak).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\publish.ps1 `
        -Target "\\fileserver\venera\assistant" -Notes "On-prem STT ulandi"
#>
param(
    [Parameter(Mandatory = $true)][string]$Target,
    [string]$Notes = "",
    [switch]$Mandatory,
    [string]$MinVersion = "",
    [string[]]$UpdateUrl = @(),
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
# packaging/windows/ ichida turibmiz, shuning uchun ikki daraja yuqoriga.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$python = if (Test-Path ".venv\Scripts\python.exe") { ".venv\Scripts\python.exe" } else { "py" }

Write-Host "=== Nashr qilinmoqda ===" -ForegroundColor Cyan

$version = (& $python tools\sync_version.py).Trim()
if (-not $version) { throw "Versiya aniqlanmadi" }
Write-Host "Versiya: $version"

if (-not $SkipBuild) {
    Write-Host "`n1/4  O'rnatuvchi yig'ilmoqda..."
    # Manzil berilmasa - tarqatish joyidan o'zi yasaladi, shunda shu
    # o'rnatuvchidan o'rnatilgan har bir kompyuter yangilanishni o'zi topadi.
    $bakedUrl = if ($UpdateUrl.Count -gt 0) { $UpdateUrl } else { @(Join-Path $Target "version.json") }

    # Manzillarni faylga O'ZIMIZ yozamiz. `powershell -File` bilan chaqirilganda
    # massiv argument matnga aylanib qoladi va ikkita manzil bitta qatorga
    # qo'shilib ketadi - sinovda aynan shunday bo'ldi.
    # Manzillar massiv sifatida ham, vergul bilan ajratilgan bitta satr sifatida
    # ham kelishi mumkin (chaqiruv usuliga bog'liq) - ikkalasini ham qabul qilamiz.
    $clean = $bakedUrl |
        ForEach-Object { $_ -split '[,;]' } |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
    Write-Host "     Yangilanish manzillari:"
    $clean | ForEach-Object { Write-Host "       $_" }
    [System.IO.File]::WriteAllLines((Join-Path $PSScriptRoot "update_url.txt"), [string[]]$clean)

    & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "build_setup.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Build xatosi" }
} else {
    Write-Host "`n1/4  Build o'tkazib yuborildi (-SkipBuild)"
}

$setup = Join-Path $root "dist\Venera-AI-Assistant-Setup.exe"
if (-not (Test-Path $setup)) { throw "O'rnatuvchi topilmadi: $setup" }

Write-Host "2/4  Nomlanmoqda..."
$named = "Venera-AI-Assistant-Setup-$version.exe"
$stagedSetup = Join-Path $root "dist\$named"
Copy-Item $setup $stagedSetup -Force

$item = Get-Item $stagedSetup
$hash = (Get-FileHash $stagedSetup -Algorithm SHA256).Hash.ToLower()
Write-Host "     $named  ($([math]::Round($item.Length/1MB,1)) MB)"
Write-Host "     sha256: $hash"

Write-Host "3/4  version.json tayyorlanmoqda..."
$manifest = [ordered]@{
    version     = $version
    released    = (Get-Date -Format "yyyy-MM-dd")
    notes       = $Notes
    mandatory   = [bool]$Mandatory
    min_version = $MinVersion
    setup       = [ordered]@{
        file   = $named
        sha256 = $hash
        size   = $item.Length
    }
}
$manifestPath = Join-Path $root "dist\version.json"
$manifest | ConvertTo-Json -Depth 5 | Out-File -FilePath $manifestPath -Encoding utf8

Write-Host "4/4  Nusxalanmoqda -> $Target"
if (-not (Test-Path $Target)) { New-Item -ItemType Directory -Force -Path $Target | Out-Null }

# Avval setup, keyin manifest: manifest paydo bo'lgan zahoti mijozlar yuklashni
# boshlaydi, shuning uchun fayl allaqachon joyida turishi kerak.
Copy-Item $stagedSetup (Join-Path $Target $named) -Force
Copy-Item $manifestPath (Join-Path $Target "version.json") -Force

# Ommaviy tarqatish skripti ham shu yerda tursin - GPO uni to'g'ridan-to'g'ri chaqiradi
Copy-Item (Join-Path $PSScriptRoot "logon_update.ps1") (Join-Path $Target "logon_update.ps1") -Force

Write-Host "`nNashr qilindi:" -ForegroundColor Green
Write-Host "  $Target\version.json"
Write-Host "  $Target\$named"
Write-Host "  $Target\logon_update.ps1"

Write-Host "`nYangi kompyuterga o'rnatish:" -ForegroundColor Cyan
Write-Host "  $Target\$named            (ikki marta bosish yetarli)"
Write-Host "  yoki jim:  $named /S"

Write-Host "`nAllaqachon o'rnatilgan kompyuterlarni yangilash:" -ForegroundColor Cyan
Write-Host "  GPO logon skripti yoki rejalashtirilgan vazifa sifatida:" -ForegroundColor Yellow
Write-Host "    powershell.exe -ExecutionPolicy Bypass -WindowStyle Hidden ``" -ForegroundColor Yellow
Write-Host "      -File `"$Target\logon_update.ps1`" -Source `"$Target`" -InstallIfMissing -Quiet" -ForegroundColor Yellow

Write-Host "`nEski versiyalarni qo'lda tozalash mumkin (oxirgi 2-3 tasi qolsin)."
