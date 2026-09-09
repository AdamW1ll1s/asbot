[CmdletBinding()]
param(
    [string]$Config = "config/profile.yaml",
    [switch]$Cli,
    [switch]$Reinstall
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function New-ProjectVenv {
    param([string]$Target)

    $pyLauncher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        & $pyLauncher.Source -3.11 -m venv $Target
        if ($LASTEXITCODE -eq 0) { return }
        & $pyLauncher.Source -3 -m venv $Target
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "A usable Python was not available through py.exe; trying the default Python." -ForegroundColor Yellow
    }

    $pythonLauncher = Get-Command "python" -ErrorAction SilentlyContinue
    if ($null -eq $pythonLauncher) {
        throw "Python 3.11 or newer was not found. Install it from python.org and enable the Python Launcher."
    }
    & $pythonLauncher.Source -m venv $Target
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}

$venvPath = Join-Path $PWD ".venv"
$venvPython = Join-Path $venvPath "Scripts/python.exe"
$createdVenv = $false
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
    Write-Host "[Game Assist] Creating .venv ..." -ForegroundColor Cyan
    if (Test-Path $venvPath) { Remove-Item $venvPath -Recurse -Force }
    New-ProjectVenv -Target $venvPath
    $createdVenv = $true
}

$versionText = & $venvPython -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0) { throw "The Python interpreter in .venv cannot run." }
$versionParts = $versionText.Trim().Split(".")
if ([int]$versionParts[0] -lt 3 -or ([int]$versionParts[0] -eq 3 -and [int]$versionParts[1] -lt 11)) {
    throw ".venv uses Python $versionText, but this project requires Python 3.11 or newer. Delete .venv and run this script again."
}

$dependencyHash = (Get-FileHash "pyproject.toml" -Algorithm SHA256).Hash
$stampPath = Join-Path $venvPath ".game-assist-dependencies"
$installedHash = if (Test-Path $stampPath) { (Get-Content $stampPath -Raw).Trim() } else { "" }

if ($createdVenv -or $Reinstall -or $installedHash -ne $dependencyHash) {
    Write-Host "[Game Assist] Installing or updating dependencies ..." -ForegroundColor Cyan
    & $venvPython -m pip install --disable-pip-version-check -e .
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
    Set-Content -Path $stampPath -Value $dependencyHash -Encoding ASCII
} else {
    Write-Host "[Game Assist] Environment is ready; dependency installation skipped." -ForegroundColor DarkGray
}

if (-not (Test-Path $Config)) {
    $configDirectory = Split-Path -Parent $Config
    if ($configDirectory -and -not (Test-Path $configDirectory)) {
        New-Item -ItemType Directory -Path $configDirectory -Force | Out-Null
    }
    Copy-Item "config/profile.example.yaml" $Config
    Write-Host "[Game Assist] Created $Config from the example profile." -ForegroundColor Green
}

$arguments = @("-m", "game_assist.main", "--config", $Config)
if ($Cli) { $arguments += "--cli" }

Write-Host "[Game Assist] Starting ..." -ForegroundColor Green
& $venvPython @arguments
exit $LASTEXITCODE
