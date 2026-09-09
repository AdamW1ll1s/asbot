[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$Reinstall
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$venvPath = Join-Path $PWD ".venv"
$venvPython = Join-Path $venvPath "Scripts/python.exe"
$needsVenv = -not (Test-Path $venvPython)
if (-not $needsVenv) {
    $existingVersion = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $needsVenv = $true
    } else {
        $existingParts = $existingVersion.Trim().Split(".")
        $needsVenv = [int]$existingParts[0] -lt 3 -or ([int]$existingParts[0] -eq 3 -and [int]$existingParts[1] -lt 11)
    }
}
if ($needsVenv) {
    if (Test-Path $venvPath) { Remove-Item $venvPath -Recurse -Force }
    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        & $pyLauncher.Source -3.11 -m venv $venvPath
        if ($LASTEXITCODE -ne 0) {
            & $pyLauncher.Source -3 -m venv $venvPath
        }
    }
    if (-not (Test-Path $venvPython)) {
        $pythonLauncher = Get-Command "python" -ErrorAction SilentlyContinue
        if ($null -eq $pythonLauncher) {
            throw "Python 3.11 or newer was not found. Install it from python.org first."
        }
        & $pythonLauncher.Source -m venv $venvPath
    }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}

$versionText = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) { throw "The Python interpreter in .venv cannot run." }
$versionParts = $versionText.Trim().Split(".")
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 11)) {
    throw ".venv uses Python $versionText, but this project requires Python 3.11 or newer. Delete .venv and run this script again."
}

$buildRequirements = @("pyproject.toml", "requirements-dev.txt")
$hashInput = foreach ($file in $buildRequirements) { (Get-FileHash $file -Algorithm SHA256).Hash }
$dependencyHash = $hashInput -join "-"
$stampPath = Join-Path $venvPath ".game-assist-build-dependencies"
$installedHash = if (Test-Path $stampPath) { (Get-Content $stampPath -Raw).Trim() } else { "" }

if ($Reinstall -or $installedHash -ne $dependencyHash) {
    Write-Host "[Game Assist] Installing build dependencies ..." -ForegroundColor Cyan
    & $venvPython -m pip install --disable-pip-version-check -r requirements-dev.txt nuitka
    if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed." }
    Set-Content -Path $stampPath -Value $dependencyHash -Encoding ASCII
}

if (-not $SkipTests) {
    Write-Host "[Game Assist] Running tests ..." -ForegroundColor Cyan
    & $venvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Tests failed; executable was not built." }
}

$nuitkaOutput = Join-Path $PWD "build/nuitka"
$packageDirectory = Join-Path $PWD "dist/GameAssist"
$zipPath = Join-Path $PWD "dist/GameAssist-Windows.zip"

if (Test-Path $nuitkaOutput) { Remove-Item $nuitkaOutput -Recurse -Force }
if (Test-Path $packageDirectory) { Remove-Item $packageDirectory -Recurse -Force }
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
New-Item -ItemType Directory -Path $nuitkaOutput -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $packageDirectory "config") -Force | Out-Null

Write-Host "[Game Assist] Building Windows executable ..." -ForegroundColor Cyan
& $venvPython -m nuitka `
    --onefile `
    --assume-yes-for-downloads `
    --enable-plugin=tk-inter `
    --include-package=game_assist `
    --windows-console-mode=disable `
    --product-name="Game Assist" `
    --file-description="Visual automation controller for authorized local testing" `
    --file-version="0.1.0.0" `
    --output-dir=$nuitkaOutput `
    --output-filename="game-assist.exe" `
    run.py
if ($LASTEXITCODE -ne 0) { throw "Nuitka packaging failed." }

Copy-Item (Join-Path $nuitkaOutput "game-assist.exe") (Join-Path $packageDirectory "game-assist.exe")
Copy-Item "config/profile.example.yaml" (Join-Path $packageDirectory "config/profile.example.yaml")
Copy-Item "README.md" (Join-Path $packageDirectory "README.md")

$quickStart = @"
Game Assist - Windows

1. Double-click game-assist.exe.
2. On first start, config/profile.yaml is created automatically.
3. Select the authorized target window in the application.
4. F8 starts/stops automation; F12 is the emergency stop.

Keep the config directory next to the executable.
"@
Set-Content -Path (Join-Path $packageDirectory "START-HERE.txt") -Value $quickStart -Encoding UTF8
Compress-Archive -Path $packageDirectory -DestinationPath $zipPath -CompressionLevel Optimal

Write-Host "[Game Assist] Package ready: $zipPath" -ForegroundColor Green
