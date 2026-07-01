# Update-SurhanScannerAgent.ps1
# Download and install the active Surhan Scanner Agent Windows Service installer from a Farabi server.
# Run this script from elevated PowerShell on the Windows workstation.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FarabiUrl,

    [string]$InstallerUrl = "",

    [string]$InstallerPath = "$env:TEMP\SurhanScannerAgentSetup-1.0.2.exe",

    [string]$ExpectedSha256 = "63a2427c0f4e03749d1399db984e15593d259db7a3ff825dd5109cd570f6ff18",

    [string]$ServiceName = "SurhanScannerAgent",

    [switch]$Interactive
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

function Normalize-Origin {
    param([Parameter(Mandatory = $true)][string]$Url)

    $value = ($Url -as [string]).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "FarabiUrl cannot be empty."
    }

    $uri = [Uri]$value
    if ($uri.Scheme -notin @("http", "https")) {
        throw "Only http and https URLs are supported: $value"
    }

    $portPart = ""
    if (-not $uri.IsDefaultPort -and $uri.Port -gt 0) {
        $portPart = ":$($uri.Port)"
    }

    return "$($uri.Scheme)://$($uri.Host)$portPart".TrimEnd("/")
}

Assert-Administrator

$origin = Normalize-Origin -Url $FarabiUrl

if ([string]::IsNullOrWhiteSpace($InstallerUrl)) {
    $InstallerUrl = "$origin/assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.2.exe"
} elseif ($InstallerUrl.StartsWith("/")) {
    $InstallerUrl = "$origin$InstallerUrl"
}

Write-Host "FARABI_ORIGIN=$origin"
Write-Host "INSTALLER_URL=$InstallerUrl"
Write-Host "INSTALLER_PATH=$InstallerPath"

$installerDir = Split-Path -Parent $InstallerPath
if (-not (Test-Path $installerDir)) {
    New-Item -ItemType Directory -Path $installerDir -Force | Out-Null
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
} catch {
    Write-Verbose "TLS setting skipped."
}

Write-Host "Downloading installer..."
Invoke-WebRequest -Uri $InstallerUrl -OutFile $InstallerPath -UseBasicParsing

if (-not (Test-Path $InstallerPath)) {
    throw "Installer download failed: $InstallerPath"
}

$actualHash = (Get-FileHash -Path $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "SHA256=$actualHash"

if (-not [string]::IsNullOrWhiteSpace($ExpectedSha256)) {
    $expected = $ExpectedSha256.ToLowerInvariant()
    if ($actualHash -ne $expected) {
        throw "SHA256 mismatch. Expected $expected but got $actualHash"
    }
    Write-Host "SHA256_OK"
}

$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($service) {
    Write-Host "Stopping service before update: $ServiceName"
    Stop-Service -Name $ServiceName -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

$args = ""
if (-not $Interactive) {
    $args = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
}

Write-Host "Running installer..."
if ([string]::IsNullOrWhiteSpace($args)) {
    $process = Start-Process -FilePath $InstallerPath -Wait -PassThru
} else {
    $process = Start-Process -FilePath $InstallerPath -ArgumentList $args -Wait -PassThru
}

Write-Host "INSTALLER_EXIT_CODE=$($process.ExitCode)"
if ($process.ExitCode -ne 0) {
    throw "Installer failed with exit code $($process.ExitCode)"
}

Start-Sleep -Seconds 3

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$configScript = Join-Path $scriptDir "Configure-SurhanScannerAgent.ps1"

if (Test-Path $configScript) {
    Write-Host "Running configuration script..."
    & $configScript -FarabiUrl $origin
} else {
    Write-Warning "Configure-SurhanScannerAgent.ps1 not found in $scriptDir"
    Write-Warning "Run Configure-SurhanScannerAgent.ps1 manually to set allowed_farabi_origins."
}

Write-Host "Verifying service..."
Get-CimInstance Win32_Service -Filter "Name='$ServiceName'" |
    Select-Object Name, DisplayName, State, StartMode, StartName, PathName |
    Format-List

try {
    $health = Invoke-WebRequest -Uri "http://127.0.0.1:8787/health" -UseBasicParsing -TimeoutSec 10
    Write-Host "HEALTH_STATUS=$($health.StatusCode)"
    Write-Host $health.Content
} catch {
    Write-Warning "Health check failed after update."
    Write-Warning $_.Exception.Message
}

Write-Host "UPDATE_DONE"
