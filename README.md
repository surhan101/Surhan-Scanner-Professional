# Surhan Scanner

Surhan Scanner is a Frappe/ERPNext application for workstation-based document scanning through a local Windows Agent.

## Current Production Model

- Agent version: 1.0.0
- Deployment mode: Windows Service
- Installer: SurhanScannerAgentSetup-1.0.0.exe
- Installer URL: /assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe
- SHA256: 6792b3644e457ab031c234e3405e9d7d8ad7e22c2ba230a946f14de568c71f1d
- Local health endpoint: http://127.0.0.1:8787/health

## Main Features

- Frappe/ERPNext integration.
- Windows Service Agent.
- Scanner workstation support.
- Agent health checks.
- Portable Farabi server URL configuration.
- PowerShell scripts for configure, update, and uninstall.
- Migration patch for Agent settings.

## Portability Rule

This repository must not contain deployment-specific server IP addresses.

Each deployment must configure its own Farabi server URL using:

PowerShell.exe -ExecutionPolicy Bypass -File .\Configure-SurhanScannerAgent.ps1 -FarabiUrl "https://farabi.example.com"

For internal IP-based deployments:

PowerShell.exe -ExecutionPolicy Bypass -File .\Configure-SurhanScannerAgent.ps1 -FarabiUrl "http://FARABI-SERVER-IP"

## Documentation

- INSTALLATION.md
- SECURITY.md
- CHANGELOG.md
