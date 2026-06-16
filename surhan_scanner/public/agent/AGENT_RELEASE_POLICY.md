# Surhan Scanner Agent Release Policy

## Official Agent Name

Surhan Scanner Agent Enterprise

## Current Latest Runtime

The latest supported runtime package is:

SurhanScannerAgent-v1.0.2.zip

Version:

1.0.2

## Deployment Mode

The latest runtime package uses:

user_startup_watchdog

It is a Runtime ZIP package.

## Important Windows Service Note

SurhanScannerAgent-v1.0.2.zip is not a Windows Service installer.

It does not include:

- service installer
- sc create script
- NSSM
- WinSW
- setup executable

Therefore, the update manifest must not describe version 1.0.2 as a Windows Service installer.

## Legacy Service Installer

The repository still contains:

SurhanScannerAgentSetup-1.0.0.exe

This file is a legacy service installer for version 1.0.0.

It must not be used as the latest update package while latest_version is 1.0.2.

## Current Manifest Policy

The update manifest must use:

- latest_version: 1.0.2
- package_filename: SurhanScannerAgent-v1.0.2.zip
- archive_format: zip
- installer_type: runtime_zip
- deployment_mode: user_startup_watchdog
- windows_service_installer: false
- requires_admin: false

## Future Work

If Windows Service deployment is required for the latest Agent, a new installer must be built separately, for example:

SurhanScannerAgentSetup-1.0.2.exe

Only after that should the manifest be changed to service installer mode.
