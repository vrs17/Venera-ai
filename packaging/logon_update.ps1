<#
.SYNOPSIS
    Kompyuterdagi Venera AI Assistant ni tarqatish joyidagi versiyaga tenglashtiradi.

.DESCRIPTION
    Bu skript ALLAQACHON o'rnatilgan (yoki umuman o'rnatilmagan) kompyuterlarga
    yangi versiyani yetkazish uchun. Uni domen siyosati (GPO) orqali logon skripti
    qilib qo'ying yoki har bir foydalanuvchi uchun rejalashtirilgan vazifa qiling.

    Ishlash tartibi:
      1. Tarqatish joyidagi version.json o'qiladi.
      2. Registrdan o'rnatilgan versiya olinadi.
      3. Nashr qilingani yangiroq bo'lsa - o'rnatuvchi jim rejimda ishlaydi.
      4. Aks holda hech narsa qilinmaydi (bir necha millisekund).

    MUHIM: skript foydalanuvchi nomidan ishlashi SHART. Ilova har bir foydalanuvchi
    profiliga o'rnatiladi (%LOCALAPPDATA%), shuning uchun uzoqdan SYSTEM nomidan
    ishga tushirish noto'g'ri profilga o'rnatadi. Logon skripti yoki foydalanuvchi
    kontekstidagi vazifa - to'g'ri yo'l.

    Skript hech qachon xato bilan tugamaydi (logonni to'xtatib qo'ymasligi uchun).

.PARAMETER Source
    Tarqatish papkasi, ichida version.json va Setup exe turadi.

.PARAMETER InstallIfMissing
    Ilova umuman o'rnatilmagan bo'lsa ham o'rnatsin (ommaviy tarqatish uchun).

.PARAMETER Force
    Versiya bir xil bo'lsa ham qayta o'rnatsin.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File logon_update.ps1 -Source "\\fileserver\venera\assistant"

.EXAMPLE
    # GPO: User Configuration > Policies > Windows Settings > Scripts > Logon
    #   Script: powershell.exe
    #   Params: -ExecutionPolicy Bypass -WindowStyle Hidden -File \\fileserver\venera\assistant\logon_update.ps1 -Source \\fileserver\venera\assistant -InstallIfMissing
#>
param(
    [Parameter(Mandatory = $true)][string]$Source,
    [switch]$InstallIfMissing,
    [switch]$Force,
    [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

$uninstallKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\Venera-AI-Assistant"
$logDir = Join-Path $env:LOCALAPPDATA "Venera\logs"
$logFile = Join-Path $logDir "deploy.log"

function Write-Log($message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $message
    if (-not $Quiet) { Write-Host $line }
    try {
        if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
        Add-Content -Path $logFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch { }
}

function Get-VersionTuple($text) {
    $parts = ($text -replace '^v', '') -split '[.\-+]'
    $numbers = @(0, 0, 0)
    for ($i = 0; $i -lt 3 -and $i -lt $parts.Count; $i++) {
        [int]$value = 0
        if ([int]::TryParse($parts[$i], [ref]$value)) { $numbers[$i] = $value }
    }
    return $numbers
}

function Compare-Version($left, $right) {
    $a = Get-VersionTuple $left
    $b = Get-VersionTuple $right
    for ($i = 0; $i -lt 3; $i++) {
        if ($a[$i] -gt $b[$i]) { return 1 }
        if ($a[$i] -lt $b[$i]) { return -1 }
    }
    return 0
}

try {
    $manifestPath = Join-Path $Source "version.json"
    if (-not (Test-Path $manifestPath)) {
        Write-Log "Manifest topilmadi: $manifestPath"
        exit 0
    }

    $manifest = Get-Content $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $published = [string]$manifest.version
    if (-not $published) { Write-Log "Manifestda versiya yo'q"; exit 0 }

    $installed = $null
    if (Test-Path $uninstallKey) {
        $installed = (Get-ItemProperty $uninstallKey -ErrorAction SilentlyContinue).DisplayVersion
    }

    if (-not $installed) {
        if (-not $InstallIfMissing) {
            Write-Log "Ilova o'rnatilmagan, -InstallIfMissing berilmagan - o'tkazib yuborildi"
            exit 0
        }
        Write-Log "Ilova o'rnatilmagan, $published o'rnatilmoqda"
    }
    elseif ((Compare-Version $published $installed) -le 0 -and -not $Force) {
        Write-Log "Yangilanish shart emas (o'rnatilgan $installed, nashr $published)"
        exit 0
    }
    else {
        Write-Log "Yangilanmoqda: $installed -> $published"
    }

    $setupName = [string]$manifest.setup.file
    $setupPath = Join-Path $Source $setupName
    if (-not (Test-Path $setupPath)) {
        Write-Log "O'rnatuvchi topilmadi: $setupPath"
        exit 0
    }

    # Nazorat yig'indisi tekshiruvi - tarmoq papkasidagi fayl almashtirilgan bo'lishi mumkin
    $expected = [string]$manifest.setup.sha256
    if ($expected) {
        $actual = (Get-FileHash $setupPath -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $expected.ToLower()) {
            Write-Log "XATO: nazorat yig'indisi mos kelmadi, o'rnatish bekor qilindi"
            exit 0
        }
    }

    # Tarmoqdan to'g'ridan-to'g'ri ishga tushirish SmartScreen'ga urilishi mumkin,
    # shuning uchun avval mahalliy papkaga ko'chiramiz.
    $temp = Join-Path $env:TEMP "venera-assistant-setup"
    if (-not (Test-Path $temp)) { New-Item -ItemType Directory -Force -Path $temp | Out-Null }
    $localSetup = Join-Path $temp $setupName
    Copy-Item $setupPath $localSetup -Force
    Unblock-File $localSetup -ErrorAction SilentlyContinue

    # DIQQAT: `Start-Process -Wait` ISHLATILMAYDI.
    # U jarayonning bolalarini ham kutadi, o'rnatuvchi esa oxirida ilovani
    # ishga tushiradi va u tray'da doim ishlab turadi - natijada skript
    # logonni cheksiz bloklab qo'yadi (sinovda aynan shunday bo'ldi).
    # Shuning uchun /NOLAUNCH beramiz va faqat o'rnatuvchining o'zini kutamiz.
    $arguments = @("/S", "/NOLAUNCH", "/URL=$manifestPath")
    $process = Start-Process -FilePath $localSetup -ArgumentList $arguments -PassThru -WindowStyle Hidden
    if (-not $process.WaitForExit(180000)) {
        Write-Log "O'rnatuvchi 3 daqiqada tugamadi - to'xtatilmoqda"
        try { $process.Kill() } catch { }
        exit 0
    }
    Write-Log "O'rnatuvchi tugadi, kod: $($process.ExitCode)"

    Start-Sleep -Seconds 2

    # Ilovani o'zimiz ishga tushiramiz (kutmasdan).
    $exe = Join-Path $env:LOCALAPPDATA "Programs\Venera\Venera.exe"
    if (Test-Path $exe) {
        Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe) -WindowStyle Hidden
        Write-Log "Ilova ishga tushirildi"
    }
    $now = (Get-ItemProperty $uninstallKey -ErrorAction SilentlyContinue).DisplayVersion
    Write-Log "Hozirgi versiya: $now"

    Remove-Item $localSetup -Force -ErrorAction SilentlyContinue
}
catch {
    Write-Log "Kutilmagan xato: $($_.Exception.Message)"
}

exit 0
