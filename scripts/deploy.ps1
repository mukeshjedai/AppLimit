#Requires -Version 5.1
<#
.SYNOPSIS
  Deploy AppLimit to Azure Functions.

.DESCRIPTION
  Runs preflight checks, verifies the function entrypoint, then publishes with
  remote Oryx build (Linux-compatible wheels on Azure).

.EXAMPLE
  .\scripts\deploy.ps1
  .\scripts\deploy.ps1 -FunctionAppName "my-func-app"
#>
[CmdletBinding()]
param(
    [string] $FunctionAppName = "applimit-func-97195",
    [switch] $SkipImportCheck
)

$ErrorActionPreference = "Stop"

function Write-Step([string] $Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
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

function Assert-Command([string] $Name, [string] $InstallHint) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found on PATH.`n$InstallHint"
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

Write-Host "AppLimit Azure deploy" -ForegroundColor Green
Write-Host "Repo: $RepoRoot"
Write-Host "Function app: $FunctionAppName"

Write-Step "Checking prerequisites"
Assert-Command "func" "Install Azure Functions Core Tools v4: https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local"
Get-PythonCommand | Out-Null

if (Get-Command "az" -ErrorAction SilentlyContinue) {
    try {
        $account = az account show --query "name" -o tsv 2>$null
        if ($account) {
            Write-Host "Azure CLI account: $account"
        } else {
            Write-Warning "Azure CLI is installed but no account is logged in. Run: az login"
        }
    } catch {
        Write-Warning "Could not read Azure CLI account. Run: az login"
    }
} else {
    Write-Warning "Azure CLI (az) not found. Deploy may still work if func is already authenticated."
}

if (-not (Test-Path (Join-Path $RepoRoot "function_app.py"))) {
    throw "function_app.py not found. Run this script from the AppLimit repository."
}

if (-not $SkipImportCheck) {
    Write-Step "Verifying function entrypoint"
    Invoke-Python @("-c", "from function_app import app; print('function_app ok', type(app))")
}

Write-Step "Publishing to Azure (remote build)"
Write-Host "Command: func azure functionapp publish $FunctionAppName --python --build remote"
func azure functionapp publish $FunctionAppName --python --build remote
if ($LASTEXITCODE -ne 0) {
    throw "Deploy failed with exit code $LASTEXITCODE."
}

Write-Host ""
Write-Host "Deploy finished successfully." -ForegroundColor Green
Write-Host "Site: https://$FunctionAppName.azurewebsites.net"
