#Requires -Version 5.1
<#
.SYNOPSIS
  Validate AppLimit, the Next.js frontend, and Singularity, then deploy Azure Functions.

.EXAMPLE
  .\scripts\check-and-deploy.ps1
  .\scripts\check-and-deploy.ps1 -FunctionAppName "applimit-func-97195"
  .\scripts\check-and-deploy.ps1 -SkipAzureDeploy
#>
[CmdletBinding()]
param(
    [string] $FunctionAppName = "applimit-func-97195",
    [switch] $SkipAzureDeploy
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$FrontendRoot = Join-Path $RepoRoot "frontend"
$ExtensionRoot = Join-Path $RepoRoot "singularity-extension"

function Write-Step([string] $Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Stop-OnExitCode([string] $Label) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE. Azure deployment was not started."
    }
}

function Assert-Command([string] $Name, [string] $Hint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found.`n$Hint"
    }
}

function Find-Python {
    $candidates = @()
    $venvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $candidates += ,@($venvPython)
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $candidates += ,@("python")
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += ,@("py", "-3")
    }

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $prefix = @($candidate | Select-Object -Skip 1)
        try {
            & $exe @prefix --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return @{ Exe = $exe; Prefix = $prefix }
            }
        } catch {
            # Try the next candidate.
        }
    }
    throw "A working Python 3 installation was not found. Install Python 3.10+ and then run: python -m pip install -r requirements.txt -r requirements-dev.txt"
}

function Invoke-Python([hashtable] $Python, [string[]] $Arguments) {
    & $Python.Exe @($Python.Prefix + $Arguments)
    Stop-OnExitCode "Python check"
}

Set-Location $RepoRoot
Write-Host "AppLimit validation and Azure deployment" -ForegroundColor Green
Write-Host "Repository: $RepoRoot"
Write-Host "Azure Function: $FunctionAppName"

Write-Step "1/4 Checking AppLimit middleware"
$python = Find-Python
Invoke-Python $python @("-m", "compileall", "-q", "function_app.py", "applimit")
Invoke-Python $python @("-c", "from function_app import app; print('Function entrypoint loaded:', type(app).__name__)")

# Production environments commonly omit test-only packages. Install the
# repository's pinned development requirements only when pytest is absent.
& $python.Exe @($python.Prefix + @("-c", "import pytest")) 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "pytest is not installed; installing development test requirements..." -ForegroundColor Yellow
    Invoke-Python $python @(
        "-m", "pip", "install", "--disable-pip-version-check",
        "-r", (Join-Path $RepoRoot "requirements-dev.txt")
    )
}
Invoke-Python $python @("-m", "pytest", "tests", "-q")
Write-Host "AppLimit middleware checks passed." -ForegroundColor Green

Write-Step "2/4 Checking Next.js frontend"
Assert-Command "npm" "Install the current Node.js LTS release from https://nodejs.org/."
Push-Location $FrontendRoot
try {
    if (-not (Test-Path (Join-Path $FrontendRoot "node_modules"))) {
        Write-Host "Installing locked frontend dependencies..."
        npm ci
        Stop-OnExitCode "npm ci"
    }
    npm run lint
    Stop-OnExitCode "Frontend lint"
    npm run build
    Stop-OnExitCode "Frontend production build"
} finally {
    Pop-Location
}
Write-Host "Frontend checks passed." -ForegroundColor Green

Write-Step "3/4 Checking Singularity Chrome extension"
Assert-Command "node" "Install the current Node.js LTS release from https://nodejs.org/."
$manifestPath = Join-Path $ExtensionRoot "manifest.json"
$manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
if ($manifest.manifest_version -ne 3) {
    throw "Singularity manifest must use Manifest V3."
}

$requiredFiles = @(
    $manifest.background.service_worker,
    $manifest.side_panel.default_path,
    $manifest.options_ui.page,
    "permissions.html",
    "permissions.js"
) + @($manifest.content_scripts | ForEach-Object { $_.js } | ForEach-Object { $_ })
foreach ($relativeFile in ($requiredFiles | Sort-Object -Unique)) {
    if (-not (Test-Path (Join-Path $ExtensionRoot $relativeFile))) {
        throw "Manifest references a missing extension file: $relativeFile"
    }
}

Get-ChildItem $ExtensionRoot -Filter "*.js" -File -Recurse | ForEach-Object {
    node --check $_.FullName
    Stop-OnExitCode "JavaScript syntax check: $($_.Name)"
}
Write-Host "Singularity $($manifest.version) checks passed." -ForegroundColor Green

Write-Step "4/4 Azure Functions deployment"
if ($SkipAzureDeploy) {
    Write-Host "Azure deployment skipped by request." -ForegroundColor Yellow
} else {
    & (Join-Path $PSScriptRoot "deploy.ps1") `
        -FunctionAppName $FunctionAppName `
        -SkipImportCheck
    Stop-OnExitCode "Azure Functions deployment"
}

Write-Host ""
Write-Host "All requested checks completed successfully." -ForegroundColor Green
if (-not $SkipAzureDeploy) {
    Write-Host "Deployed: https://$FunctionAppName.azurewebsites.net"
}
