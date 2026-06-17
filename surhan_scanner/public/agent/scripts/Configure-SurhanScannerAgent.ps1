# Configure-SurhanScannerAgent.ps1
# Configure Surhan Scanner Agent Windows Service for a specific Farabi/Frappe server.
# Run this script from elevated PowerShell on the Windows workstation.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$FarabiUrl,

    [string[]]$AdditionalOrigins = @(),

    [string]$ServiceName = "SurhanScannerAgent",

    [int]$AgentPort = 8787,

    [switch]$NoRestart
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

    try {
        $uri = [Uri]$value
    } catch {
        throw "Invalid URL: $value"
    }

    if ($uri.Scheme -notin @("http", "https")) {
        throw "Only http and https URLs are supported: $value"
    }

    $portPart = ""
    if (-not $uri.IsDefaultPort -and $uri.Port -gt 0) {
        $portPart = ":$($uri.Port)"
    }

    return "$($uri.Scheme)://$($uri.Host)$portPart".TrimEnd("/")
}

function Ensure-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        $Value
    )

    if ($null -eq $Object.PSObject.Properties[$Name]) {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    } else {
        $Object.$Name = $Value
    }
}

function Read-AgentConfig {
    param([Parameter(Mandatory = $true)][string]$Path)

    $raw = Get-Content -Path $Path -Raw -Encoding UTF8
    return $raw | ConvertFrom-Json
}

function Write-AgentConfigUtf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Config
    )

    $dir = Split-Path -Parent $Path
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }

    $json = $Config | ConvertTo-Json -Depth 50
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $json + [Environment]::NewLine, $utf8NoBom)
}

Assert-Administrator

$primaryOrigin = Normalize-Origin -Url $FarabiUrl
$origins = New-Object System.Collections.Generic.List[string]
$origins.Add($primaryOrigin)

foreach ($origin in $AdditionalOrigins) {
    if (-not [string]::IsNullOrWhiteSpace($origin)) {
        $normalized = Normalize-Origin -Url $origin
        if (-not $origins.Contains($normalized)) {
            $origins.Add($normalized)
        }
    }
}

$standardConfigPaths = @(
    "$env:ProgramData\SurhanScannerAgent\surhan_agent_config.json",
    "$env:ProgramFiles\SurhanScannerAgent\surhan_agent_config.json",
    "C:\SurhanScannerAgent\surhan_agent_config.json"
)

$existingConfigPaths = @($standardConfigPaths | Where-Object { Test-Path $_ })

if ($existingConfigPaths.Count -gt 0) {
    $sourceConfigPath = $existingConfigPaths[0]
    Write-Host "Using existing config: $sourceConfigPath"
    $config = Read-AgentConfig -Path $sourceConfigPath
} else {
    Write-Host "No existing config found. Creating new base config in ProgramData."
    $config = [pscustomobject]@{
        agent = [pscustomobject]@{
            name = "Surhan Scanner Agent"
            edition = "Enterprise"
            version = "1.0.0"
        }
        server = [pscustomobject]@{}
        enterprise = [pscustomobject]@{}
        paths = [pscustomobject]@{}
        deployment_mode = "windows_service"
    }
}

if ($null -eq $config.PSObject.Properties["server"]) {
    $config | Add-Member -MemberType NoteProperty -Name "server" -Value ([pscustomobject]@{})
}
if ($null -eq $config.PSObject.Properties["enterprise"]) {
    $config | Add-Member -MemberType NoteProperty -Name "enterprise" -Value ([pscustomobject]@{})
}
if ($null -eq $config.PSObject.Properties["paths"]) {
    $config | Add-Member -MemberType NoteProperty -Name "paths" -Value ([pscustomobject]@{})
}

Ensure-ObjectProperty -Object $config -Name "deployment_mode" -Value "windows_service"

Ensure-ObjectProperty -Object $config.server -Name "farabi_base_url" -Value $primaryOrigin
Ensure-ObjectProperty -Object $config.server -Name "allowed_farabi_origins" -Value @($origins.ToArray())
Ensure-ObjectProperty -Object $config.server -Name "allowed_farabi_origins_source" -Value "Configure-SurhanScannerAgent.ps1"
Ensure-ObjectProperty -Object $config.server -Name "cors_note" -Value "Configured for this workstation deployment."

Ensure-ObjectProperty -Object $config.enterprise -Name "deployment_mode" -Value "windows_service"
Ensure-ObjectProperty -Object $config.enterprise -Name "silent_install_supported" -Value $true
Ensure-ObjectProperty -Object $config.enterprise -Name "auto_upgrade_supported" -Value $true
Ensure-ObjectProperty -Object $config.enterprise -Name "required_agent_version" -Value "1.0.0"
Ensure-ObjectProperty -Object $config.enterprise -Name "compatible_agent_versions" -Value @("1.0.0")

Ensure-ObjectProperty -Object $config.paths -Name "program_data_dir" -Value "$env:ProgramData\SurhanScannerAgent"
Ensure-ObjectProperty -Object $config.paths -Name "sessions_dir" -Value "$env:ProgramData\SurhanScannerAgent\sessions"
Ensure-ObjectProperty -Object $config.paths -Name "spool_dir" -Value "$env:ProgramData\SurhanScannerAgent\spool"
Ensure-ObjectProperty -Object $config.paths -Name "temp_dir" -Value "$env:ProgramData\SurhanScannerAgent\temp"
Ensure-ObjectProperty -Object $config.paths -Name "logs_dir" -Value "$env:ProgramData\SurhanScannerAgent\logs"
Ensure-ObjectProperty -Object $config.paths -Name "archive_dir" -Value "$env:ProgramData\SurhanScannerAgent\archive"

foreach ($dir in @(
    "$env:ProgramData\SurhanScannerAgent",
    "$env:ProgramData\SurhanScannerAgent\sessions",
    "$env:ProgramData\SurhanScannerAgent\spool",
    "$env:ProgramData\SurhanScannerAgent\temp",
    "$env:ProgramData\SurhanScannerAgent\logs",
    "$env:ProgramData\SurhanScannerAgent\archive"
)) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

foreach ($path in $standardConfigPaths) {
    if (Test-Path $path) {
        Copy-Item $path "$path.bak.$timestamp" -Force
    }

    Write-AgentConfigUtf8NoBom -Path $path -Config $config
    Write-Host "Wrote config: $path"
}

foreach ($path in $standardConfigPaths) {
    $null = Read-AgentConfig -Path $path
}
Write-Host "JSON_PARSE_OK"

if (-not $NoRestart) {
    $service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($service) {
        Write-Host "Restarting service: $ServiceName"
        Restart-Service -Name $ServiceName -Force
        Start-Sleep -Seconds 3
    } else {
        Write-Warning "Service not found: $ServiceName"
    }
}

$healthUrl = "http://127.0.0.1:$AgentPort/health"
try {
    $health = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 10
    Write-Host "HEALTH_STATUS=$($health.StatusCode)"
    Write-Host $health.Content
} catch {
    Write-Warning "Health check failed: $healthUrl"
    Write-Warning $_.Exception.Message
}

Write-Host "CONFIGURED_ORIGINS=$($origins -join ',')"
Write-Host "DONE"
