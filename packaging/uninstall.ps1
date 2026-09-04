<#
.SYNOPSIS
    Venera AI Assistant ni o'chiradi.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging\uninstall.ps1
    powershell -ExecutionPolicy Bypass -File packaging\uninstall.ps1 -KeepSettings
#>
param([switch]$KeepSettings)

$ErrorActionPreference = "Continue"

$appName   = "Venera AI Assistant"
$installTo = Join-Path $env:LOCALAPPDATA "Programs\Venera"
$taskName  = "Venera\AI Assistant"

Write-Host "=== $appName - o'chirish ===" -ForegroundColor Cyan

Write-Host "1/4  Avtostart vazifasi o'chirilmoqda..."
cmd /c "schtasks /Delete /TN ""$taskName"" /F" 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-Host "     O'chirildi" } else { Write-Host "     Vazifa yo'q edi" }

Write-Host "2/4  Jarayon to'xtatilmoqda..."
Get-Process Venera -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 700

Write-Host "3/4  Yorliq va fayllar..."
Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\$appName.lnk") -Force -ErrorAction SilentlyContinue
Remove-Item $installTo -Recurse -Force -ErrorAction SilentlyContinue

if ($KeepSettings) {
    Write-Host "4/4  Sozlamalar va loglar saqlandi (-KeepSettings)"
} else {
    Write-Host "4/4  Sozlamalar va loglar o'chirilmoqda..."
    Remove-Item (Join-Path $env:APPDATA "Venera") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:LOCALAPPDATA "Venera") -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "`nTekshiruv:" -ForegroundColor Cyan
cmd /c "schtasks /Query /TN ""$taskName""" 2>&1 | Out-Null
Write-Host ("  Vazifa   : " + $(if ($LASTEXITCODE -eq 0) { "HALI BOR (!)" } else { "yo'q" }))
Write-Host ("  Papka    : " + $(if (Test-Path $installTo) { "HALI BOR (!)" } else { "yo'q" }))
Write-Host ("  Jarayon  : " + $(if (Get-Process Venera -ErrorAction SilentlyContinue) { "HALI ISHLAYAPTI (!)" } else { "yo'q" }))
Write-Host "`nO'chirildi." -ForegroundColor Green
