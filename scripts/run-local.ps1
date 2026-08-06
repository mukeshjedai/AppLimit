#Requires -Version 5.1
<#
.SYNOPSIS
  Run AppLimit locally on Windows via Azure Functions Core Tools.

.DESCRIPTION
  Creates/uses a .venv, installs requirements, ensures local.settings.json exists,
  then starts `func start` (typically http://localhost:7071).

.EXAMPLE
  .\scripts\run-local.ps1
  .\scripts\run-local.ps1 -SkipInstall
#>
[CmdletBinding()]
param(
    [switch] $SkipInstall,
    [switch] $RecreateVenv
)

$ErrorActionPreference = "Stop"

function Write-Step([string] $Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Assert-Command([string] $Name, [string] $InstallHint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found on PATH.`n$InstallHint"
    }
}

function Get-PythonCommand {
    if (Get-Command "python" -ErrorAction SilentlyContinue) {
        return @{ Exe = "python"; Args = @() }
    }
    if (Get-Command "py" -ErrorAction SilentlyContinue) {
        return @{ Exe = "py"; Args = @("-3") }
    }
    throw "Python was not found on PATH.`nInstall Python 3.10+ from https://www.python.org/downloads/ or use the py launcher."
}

function Invoke-Python([string[]] $PythonArgs) {
    $py = Get-PythonCommand
    & $py.Exe @($py.Args + $PythonArgs)
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE."
    }
}

function Get-PythonExe {
    $py = Get-PythonCommand
    if ($py.Exe -eq "python") {
        return (Get-Command python).Source
    }
    $resolved = & py -3 -c "import sys; print(sys.executable)"
    if ($LASTEXITCODE -ne 0 -or -not $resolved) {
        throw "Could not resolve Python executable via py launcher."
    }
    return $resolved.Trim()
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "AppLimit local run (Windows)" -ForegroundColor Green
Write-Host "Repo: $RepoRoot"

Write-Step "Checking prerequisites"
Assert-Command "func" "Install Azure Functions Core Tools v4: https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local"
$PythonExe = Get-PythonExe
Invoke-Python @("-c", "import sys; v=sys.version_info; assert v.major==3 and v.minor>=10, f'Python 3.10+ required, found {v.major}.{v.minor}'")
Write-Host "Python: $PythonExe"

$VenvPath = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$VenvPip = Join-Path $VenvPath "Scripts\pip.exe"

if ($RecreateVenv -and (Test-Path $VenvPath)) {
    Write-Step "Removing existing virtual environment"
    Remove-Item -Recurse -Force $VenvPath
}

if (-not (Test-Path $VenvPython)) {
    Write-Step "Creating virtual environment (.venv)"
    & $PythonExe -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create virtual environment."
    }
}

$LocalSettings = Join-Path $RepoRoot "local.settings.json"
$LocalSettingsExample = Join-Path $RepoRoot "local.settings.json.example"
if (-not (Test-Path $LocalSettings)) {
    if (-not (Test-Path $LocalSettingsExample)) {
        throw "Missing local.settings.json and local.settings.json.example."
    }
    Write-Step "Creating local.settings.json from example"
    Copy-Item $LocalSettingsExample $LocalSettings
    Write-Warning "Edit local.settings.json to set AzureWebJobsStorage and APPLIMIT_AZURE_STORAGE_CONNECTION_STRING if needed."
}

if (-not $SkipInstall) {
    Write-Step "Installing Python dependencies"
    & $VenvPip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        throw "pip upgrade failed."
    }
    & $VenvPip install -r (Join-Path $RepoRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed."
    }
}

Write-Step "Verifying function entrypoint"
& $VenvPython -c "from function_app import app; print('function_app ok', type(app))"
if ($LASTEXITCODE -ne 0) {
    throw "function_app import check failed."
}

Write-Step "Starting Azure Functions host"
Write-Host "Press Ctrl+C to stop."
Write-Host "Expected URL: http://localhost:7071"
Write-Host ""

$env:VIRTUAL_ENV = $VenvPath
$env:PATH = "$(Join-Path $VenvPath 'Scripts');$env:PATH"

func start
