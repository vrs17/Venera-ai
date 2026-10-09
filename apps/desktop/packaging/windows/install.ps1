<#
.SYNOPSIS
    Venera AI Assistant ni o'rnatadi va avtostartni yoqadi.

.DESCRIPTION
    * Fayllarni %LOCALAPPDATA%\Programs\Venera ga ko'chiradi (admin kerak emas)
    * Task Scheduler'da "logon" vazifasini yaratadi - kompyuter yonganda o'zi ishga tushadi
    * Boshlash menyusiga yorliq qo'shadi
    * Ilovani darhol ishga tushiradi

    Admin huquqi TALAB QILINMAYDI.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\windows\install.ps1
#>
param(
    [string]$Source,
    [switch]$NoAutostart,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
# Ilova papkasi ikki xil joyda bo'lishi mumkin:
#   1) tarqatma arxiv ichida  - install.ps1 yonida Venera\
#   2) ishlab chiqish paytida - <loyiha>\dist\Venera\
if (-not $Source) {
    $candidates = @(
        (Join-Path $PSScriptRoot "Venera"),
        (Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) "dist\Venera")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path (Join-Path $candidate "Venera.exe")) { $Source = $candidate; break }
    }
    if (-not $Source) { $Source = $candidates[0] }
}

$appName   = "Barno AI Assistant"
$installTo = Join-Path $env:LOCALAPPDATA "Programs\Venera"
$exePath   = Join-Path $installTo "Venera.exe"
$taskName  = "Venera\AI Assistant"

Write-Host "=== $appName - o'rnatish ===" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $Source "Venera.exe"))) {
    Write-Host "Build topilmadi: $Source" -ForegroundColor Red
    Write-Host "Kutilgan joylar:" -ForegroundColor Yellow
    Write-Host "  $PSScriptRoot\Venera\  (tarqatma arxiv)"
    Write-Host "  ..\dist\Venera\        (build natijasi)"
    Write-Host "Build qilish:  powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1"
    exit 1
}

Write-Host "1/4  Ishlayotgan nusxa to'xtatilmoqda..."
Get-Process Venera -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 700

Write-Host "2/4  Fayllar ko'chirilmoqda -> $installTo"
New-Item -ItemType Directory -Force -Path $installTo | Out-Null
robocopy $Source $installTo /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "Fayllar ko'chirilmadi (robocopy $LASTEXITCODE)" }

Write-Host "3/4  Boshlash menyusiga yorliq..."
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shortcut  = Join-Path $startMenu "$appName.lnk"
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($shortcut)
$link.TargetPath       = $exePath
$link.WorkingDirectory = $installTo
$link.IconLocation     = $exePath
$link.Description      = "$appName - ovozli yordamchi"
$link.Save()
# Qayta nomlashdan oldingi yorliq dublikat bo'lib qolmasin.
Remove-Item (Join-Path $startMenu "Venera AI Assistant.lnk") -Force -ErrorAction SilentlyContinue

if ($NoAutostart) {
    Write-Host "4/4  Avtostart o'tkazib yuborildi (-NoAutostart)"
} else {
    Write-Host "4/4  Avtostart yoqilmoqda (Task Scheduler)..."
    & $exePath --install-autostart | Out-Null
    Start-Sleep -Milliseconds 500
    # schtasks vazifa topilmasa stderr'ga yozadi; ErrorActionPreference="Stop"
    # bilan bu skriptni to'xtatib qo'yadi, shuning uchun vaqtincha yumshatamiz.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    cmd /c "schtasks /Query /TN ""$taskName""" 2>&1 | Out-Null
    $taskFound = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $previous
    if ($taskFound) {
        Write-Host "     Vazifa yaratildi: $taskName" -ForegroundColor Green
    } else {
        Write-Host "     Ogohlantirish: vazifa yaratilmadi." -ForegroundColor Yellow
        Write-Host "     Tray menyusidan 'Windows bilan ishga tushsin' ni yoqib ko'ring."
    }
}

Write-Host "`nO'rnatildi:" -ForegroundColor Green
Write-Host "  Dastur    : $exePath"
Write-Host "  Sozlamalar: $env:APPDATA\Venera\config.yaml"
Write-Host "  Loglar    : $env:LOCALAPPDATA\Venera\logs"

if (-not $NoLaunch) {
    Write-Host "`nIshga tushirilmoqda..."
    Start-Process -FilePath $exePath -WorkingDirectory $installTo
    Start-Sleep -Seconds 2
    if (Get-Process Venera -ErrorAction SilentlyContinue) {
        Write-Host "Ishlayapti. Tray ikonkasini (soat yonida) qarang." -ForegroundColor Green
        # Sozlamadagi klavisha band bo'lsa ilova zaxiraga o'tadi, shuning uchun
        # haqiqiy kombinatsiyani logdan o'qiymiz.
        $log = Join-Path $env:LOCALAPPDATA "Venera\logs\assistant.log"
        $line = Select-String -Path $log -Pattern "Global hotkey yoqildi: (.+)$" -ErrorAction SilentlyContinue |
                Select-Object -Last 1
        if ($line) {
            Write-Host ("Uyg'otish klavishasi: " + $line.Matches[0].Groups[1].Value.Trim())
        } else {
            Write-Host "Uyg'otish klavishasi tray menyusida ko'rsatilgan."
        }
    } else {
        Write-Host "Ishga tushmadi. Loglarni qarang: $env:LOCALAPPDATA\Venera\logs" -ForegroundColor Red
    }
}