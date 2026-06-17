# Uninstall-SurhanScannerAgent.ps1
# Uninstall Surhan Scanner Agent Windows Service.
# Run this script from elevated PowerShell on the Windows workstation.

[CmdletBinding()]
param(
    [string]$ServiceName = "SurhanScannerAgent",

    [switch]$RemoveProgramData,

    [switch]$RemoveLegacyFolders
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "This script must be run as Administrator."
    }
}

Assert-Administrator

$programFilesDir = "$env:ProgramFiles\SurhanScannerAgent"
$agentExe = Join-Path $programFilesDir "SurhanScannerAgent.exe"
$uninstaller = Join-Path $programFilesDir "unins000.exe"

Write-Host "Stopping service if it exists..."
$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($service) {
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

if (Test-Path $agentExe) {
    Write-Host "Trying Agent service uninstall command..."
    try {
        & $agentExe stop
    } catch {
        Write-Warning "Agent stop command failed or is unsupported."
    }

    try {
        & $agentExe uninstall
    } catch {
        Write-Warning "Agent uninstall command failed or is unsupported."
    }
}

if (Test-Path $uninstaller) {
    Write-Host "Running Inno Setup uninstaller..."
    $process = Start-Process -FilePath $uninstaller -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait -PassThru
    Write-Host "UNINSTALLER_EXIT_CODE=$($process.ExitCode)"
}

Write-Host "Deleting Windows service fallback..."
try {
    sc.exe delete $ServiceName | Out-Host
} catch {
    Write-Warning "sc.exe delete failed or service already removed."
}

Start-Sleep -Seconds 2

Write-Host "Removing Program Files directory..."
Remove-Item $programFilesDir -Recurse -Force -ErrorAction SilentlyContinue

if ($RemoveProgramData) {
    Write-Host "Removing ProgramData directory..."
    Remove-Item "$env:ProgramData\SurhanScannerAgent" -Recurse -Force -ErrorAction SilentlyContinue
} else {
    Write-Host "ProgramData preserved. Use -RemoveProgramData to delete logs, sessions, spool and config."
}

if ($RemoveLegacyFolders) {
    Write-Host "Removing legacy folders..."
    Remove-Item "C:\SurhanScannerAgent" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "C:\SurhanScannerAgentInstaller" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item "C:\SurhanScannerAgentSource" -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Verifying service removal..."
$remaining = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($remaining) {
    Write-Warning "Service still exists: $ServiceName"
    $remaining | Format-List *
} else {
    Write-Host "SERVICE_REMOVED"
}

Write-Host "UNINSTALL_DONE"
