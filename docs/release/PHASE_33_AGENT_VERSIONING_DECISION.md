# Phase 33 - Agent Service Installer Versioning Decision

## Decision

The active Windows Service installer remains:

SurhanScannerAgentSetup-1.0.0.exe

The official active Agent version remains:

1.0.0

## Reason

The current tested Windows Service installer installs an Agent that reports version 1.0.0 through:

http://127.0.0.1:8787/health

Therefore, the app must not advertise this installer as 1.0.2, 1.0.3, or 1.1.0 unless the Agent binary and installer are rebuilt to report the same new version.

## Current Active Metadata

- package_filename: SurhanScannerAgentSetup-1.0.0.exe
- latest_version: 1.0.0
- installer_type: windows_service_installer
- deployment_mode: windows_service
- requires_admin: true
- service_name: SurhanScannerAgent

## Next Proper Agent Release

The next actual rebuilt Agent release should use a higher version, for example:

SurhanScannerAgentSetup-1.0.3.exe

or:

SurhanScannerAgentSetup-1.1.0.exe

Only after the Agent binary, installer config, manifest, version.json, and documentation all use that same version should the release be advertised as the latest update.

## GitHub Portability Impact

This prevents false update loops where Farabi advertises a version higher than the version reported by the installed Windows Agent.
