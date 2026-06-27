# Surhan Scanner Agent Release Policy

## Active Production Package

The active production package for Surhan Scanner Agent is:

SurhanScannerAgentSetup-1.0.0.exe

## Version

1.0.0

## Deployment Mode

windows_service

## Installer Type

windows_service_installer

## Package Details

- package_filename: SurhanScannerAgentSetup-1.0.0.exe
- package_url: /assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe
- package_sha256: 63a2427c0f4e03749d1399db984e15593d259db7a3ff825dd5109cd570f6ff18
- package_size_bytes: 4433369
- archive_format: exe
- installer_type: windows_service_installer
- deployment_mode: windows_service
- windows_service_installer: true
- requires_admin: true

## Windows Service Behavior

The installer creates a Windows Service with the following identity:

- Service Name: SurhanScannerAgent
- Display Name: Surhan Scanner Agent
- Startup Type: Automatic
- Log On As: LocalSystem
- Health URL: http://127.0.0.1:8787/health
- Devices URL: http://127.0.0.1:8787/devices

The service is expected to start automatically after Windows restart.

## Recovery Behavior

The installer configures Windows Service recovery so the service restarts automatically on failure.

## Current Server Manifest

The active update_manifest.json must point to:

SurhanScannerAgentSetup-1.0.0.exe

The active version.json must point to:

/assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe

## Previous Rollback Packages

The previous agent packages are retained only for rollback and reference:

- SurhanScannerAgent-v1.0.0.zip
- SurhanScannerAgent-v1.0.1.zip
- SurhanScannerAgent-v1.0.2.zip

They are not the active production download package after Phase 31.

## Notes

This service installer requires Administrator privileges on Windows because it creates a Windows Service under Program Files.

The Agent must still be tested with a real scanner device after installation. If /devices returns an empty list while no scanner is connected, that is expected behavior.
