# Phase 35 - Windows Agent Operations Scripts

## Purpose

This phase adds official Windows PowerShell scripts for operating Surhan Scanner Agent on user workstations.

## Location

The scripts are published under:

surhan_scanner/public/agent/scripts/

## Scripts

### Configure-SurhanScannerAgent.ps1

Purpose:

Configure the installed Windows Service Agent for the actual Farabi/Frappe server URL.

Example on Windows PowerShell running as Administrator:

PowerShell.exe -ExecutionPolicy Bypass -File .\Configure-SurhanScannerAgent.ps1 -FarabiUrl "https://farabi.example.com"

For an IP-based Farabi server:

PowerShell.exe -ExecutionPolicy Bypass -File .\Configure-SurhanScannerAgent.ps1 -FarabiUrl "http://FARABI-SERVER-IP"

What it does:

- Normalizes the Farabi URL to origin format.
- Writes allowed_farabi_origins.
- Writes config to:
  - C:\ProgramData\SurhanScannerAgent\surhan_agent_config.json
  - C:\Program Files\SurhanScannerAgent\surhan_agent_config.json
  - C:\SurhanScannerAgent\surhan_agent_config.json
- Writes JSON using UTF-8 without BOM.
- Restarts the SurhanScannerAgent service.
- Verifies http://127.0.0.1:8787/health.

### Update-SurhanScannerAgent.ps1

Purpose:

Download and install the active Agent EXE from the Farabi server.

Example on Windows PowerShell running as Administrator:

PowerShell.exe -ExecutionPolicy Bypass -File .\Update-SurhanScannerAgent.ps1 -FarabiUrl "https://farabi.example.com"

What it does:

- Downloads SurhanScannerAgentSetup-1.0.0.exe.
- Verifies SHA256:
  6792b3644e457ab031c234e3405e9d7d8ad7e22c2ba230a946f14de568c71f1d
- Stops the old service if it exists.
- Runs the installer silently by default.
- Runs Configure-SurhanScannerAgent.ps1 after installation if available.
- Verifies service and health endpoint.

### Uninstall-SurhanScannerAgent.ps1

Purpose:

Remove the Agent Windows Service and installed files.

Default example:

PowerShell.exe -ExecutionPolicy Bypass -File .\Uninstall-SurhanScannerAgent.ps1

Full removal example:

PowerShell.exe -ExecutionPolicy Bypass -File .\Uninstall-SurhanScannerAgent.ps1 -RemoveProgramData -RemoveLegacyFolders

Default behavior:

- Stops service.
- Runs Agent uninstall command if available.
- Runs Inno Setup uninstaller if available.
- Deletes the Windows service fallback.
- Removes Program Files directory.
- Preserves ProgramData unless -RemoveProgramData is used.

## Administrator Requirement

All scripts must be run from elevated PowerShell because the Agent runs as a Windows Service.

## Production Notes

These scripts make the app portable across Farabi servers because Farabi URL is passed at workstation setup time instead of being hardcoded in the GitHub source code.
