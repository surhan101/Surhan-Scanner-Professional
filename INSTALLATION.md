# Installation Guide

## 1. Install the Frappe App

From the bench directory:

cd ~/frappe-bench
bench get-app surhan_scanner REPOSITORY_URL
bench --site SITE_NAME install-app surhan_scanner
bench --site SITE_NAME migrate
bench build --app surhan_scanner
bench restart

Replace:

- REPOSITORY_URL with the actual repository URL.
- SITE_NAME with the target Frappe site name.

## 2. Verify Agent Assets

Verify these assets are available from the Farabi/Frappe server:

- /assets/surhan_scanner/agent/update_manifest.json
- /assets/surhan_scanner/agent/version.json
- /assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe

## 3. Install Windows Agent

Run the installer as Administrator:

SurhanScannerAgentSetup-1.0.0.exe

Expected service name:

SurhanScannerAgent

Expected local health endpoint:

http://127.0.0.1:8787/health

## 4. Configure Agent URL

Run from Windows PowerShell as Administrator:

PowerShell.exe -ExecutionPolicy Bypass -File .\Configure-SurhanScannerAgent.ps1 -FarabiUrl "https://farabi.example.com"

For internal IP-based deployment:

PowerShell.exe -ExecutionPolicy Bypass -File .\Configure-SurhanScannerAgent.ps1 -FarabiUrl "http://FARABI-SERVER-IP"

## 5. Update Agent

PowerShell.exe -ExecutionPolicy Bypass -File .\Update-SurhanScannerAgent.ps1 -FarabiUrl "https://farabi.example.com"

## 6. Uninstall Agent

Default uninstall:

PowerShell.exe -ExecutionPolicy Bypass -File .\Uninstall-SurhanScannerAgent.ps1

Full uninstall:

PowerShell.exe -ExecutionPolicy Bypass -File .\Uninstall-SurhanScannerAgent.ps1 -RemoveProgramData -RemoveLegacyFolders

## 7. Migration Patch

This app includes the patch:

surhan_scanner.patches.v0_0_1.update_agent_service_installer_defaults

Expected settings after migration:

- agent_latest_version = 1.0.0
- agent_install_mode = Windows Service
- agent_download_url = /assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe
