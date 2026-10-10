<#
.SYNOPSIS
    Boshqa kompyuterlarga tarqatish uchun ZIP arxiv tayyorlaydi.

.DESCRIPTION
    Natija: dist\Venera-AI-Assistant-<versiya>.zip

    Arxiv ichida:
        Venera\      - ilova (exe + _internal, birga bo'lishi SHART)
        install.ps1            - o'rnatish
        uninstall.ps1          - o'chirish
        OQING.txt              - qisqa yo'riqnoma

    Maqsad kompyuterda Python ham, boshqa dastur ham kerak emas.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\package.ps1
#>
param([string]$Version = "0.1.0")

$ErrorActionPreference = "Stop"
# packaging/windows/ ichida turibmiz, shuning uchun ikki daraja yuqoriga.
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$appDir = Join-Path $root "dist\Venera"
if (-not (Test-Path (Join-Path $appDir "Venera.exe"))) {
    Write-Host "Build topilmadi: $appDir" -ForegroundColor Red
    Write-Host "Avval:  powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1"
    exit 1
}

$stage = Join-Path $root "dist\_package"
$zip   = Join-Path $root "dist\Venera-AI-Assistant-$Version.zip"

Write-Host "=== Tarqatma arxiv tayyorlanmoqda ===" -ForegroundColor Cyan

Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $stage | Out-Null

Write-Host "1/3  Fayllar yig'ilmoqda..."
Copy-Item $appDir (Join-Path $stage "Venera") -Recurse
Copy-Item (Join-Path $PSScriptRoot "install.ps1")   $stage
Copy-Item (Join-Path $PSScriptRoot "uninstall.ps1") $stage

$readme = @"
Barno AI Assistant $Version
==============================

O'RNATISH

  1. Ushbu arxivni istalgan papkaga to'liq chiqaring (masalan Ish stoliga).
     DIQQAT: Venera papkasini butunligicha oling.
     Faqat .exe faylini ko'chirish YETARLI EMAS - yonidagi _internal
     papkasi ishlash uchun shart.

  2. install.ps1 faylida sichqonchaning o'ng tugmasini bosing ->
     "Run with PowerShell".

     Yoki PowerShell'da:
         powershell -ExecutionPolicy Bypass -File install.ps1

  3. Tayyor. Ilova tray'da (soat yonida, ko'k "B" ikonkasi) paydo bo'ladi
     va kompyuter har yonganda o'zi ishga tushadi.

  Administrator huquqi KERAK EMAS.
  Ilova faqat joriy foydalanuvchi uchun o'rnatiladi.


FOYDALANISH

  Tray ikonkasini bosing yoki uyg'otish klavishasini bosing (Ctrl+Alt+Space).
  Agar bu kombinatsiya band bo'lsa, ilova avtomatik boshqasiga o'tadi va
  haqiqiy klavishani oynada ko'rsatadi.

  Buyruqni yozib Enter bosing. Masalan:
      chromeni och
      ovozni qirq besh foiz
      ekranni qulfla
      skrinshot ol
      soat necha
      googlda valyuta kursi qidir


TALABLAR

  Windows 10 (64-bit) yoki Windows 11.
  Python, .NET yoki boshqa dastur o'rnatish shart emas.


AGAR WINDOWS OGOHLANTIRSA

  Fayl raqamli imzolanmagani uchun SmartScreen "Windows protected your PC"
  degan oyna chiqarishi mumkin.
  "More info" -> "Run anyway" ni bosing.


QAYERGA O'RNATILADI

  Dastur     : %LOCALAPPDATA%\Programs\Venera\
  Sozlamalar : %APPDATA%\Venera\config.yaml
  Loglar     : %LOCALAPPDATA%\Venera\logs\assistant.log
  Avtostart  : Task Scheduler -> Venera\AI Assistant


O'CHIRISH

  powershell -ExecutionPolicy Bypass -File uninstall.ps1

  Sozlamalarni saqlab qolish uchun:
  powershell -ExecutionPolicy Bypass -File uninstall.ps1 -KeepSettings


MUAMMO BO'LSA

  Loglarni qarang: %LOCALAPPDATA%\Venera\logs\assistant.log
"@
$readme | Out-File -FilePath (Join-Path $stage "OQING.txt") -Encoding utf8

Write-Host "2/3  Arxivlanmoqda..."
Remove-Item $zip -Force -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $zip -CompressionLevel Optimal

Write-Host "3/3  Tozalanmoqda..."
Remove-Item $stage -Recurse -Force

$sizeMb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash

Write-Host "`nTayyor:" -ForegroundColor Green
Write-Host "  $zip"
Write-Host "  Hajmi : $sizeMb MB"
Write-Host "  SHA256: $hash"
Write-Host "`nShu ZIP faylni boshqa kompyuterga ko'chiring, chiqaring va install.ps1 ni ishga tushiring."
