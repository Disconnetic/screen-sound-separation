$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Dist = Join-Path $ProjectRoot "dist"
$Icon = Join-Path $ProjectRoot "screen_sound_separation\assets\app-icon.ico"
$VersionInfo = Join-Path $ProjectRoot "packaging\version_info.txt"
$ExtensionSource = Join-Path $ProjectRoot "browser_extension"
$ExtensionZip = Join-Path $Dist "ScreenSoundSeparation-BrowserSupport-0.2.1.zip"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Create the project virtual environment before building."
}

Push-Location $ProjectRoot
try {
    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --console `
        --name ScreenSoundSeparationNativeHost `
        --icon $Icon `
        --specpath build `
        packaging\native_host_entry.py
    if ($LASTEXITCODE -ne 0) {
        throw "Native-host packaging failed with exit code $LASTEXITCODE."
    }

    & $Python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name ScreenSoundSeparation `
        --icon $Icon `
        --version-file $VersionInfo `
        --specpath build `
        --add-data "$Dist\ScreenSoundSeparationNativeHost.exe;native-host" `
        --add-data "$ExtensionSource;browser_extension" `
        packaging\app_entry.py
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop packaging failed with exit code $LASTEXITCODE."
    }

    if (Test-Path -LiteralPath $ExtensionZip) {
        Remove-Item -LiteralPath $ExtensionZip
    }
    Compress-Archive -Path "browser_extension\*" -DestinationPath $ExtensionZip
} finally {
    Pop-Location
}

Write-Host "Built $Dist\ScreenSoundSeparation.exe"
Write-Host "Built $ExtensionZip"
