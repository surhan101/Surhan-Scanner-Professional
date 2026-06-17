# Phase 36 - Agent Settings Migration Patch

## Purpose

Add a Frappe migration patch that prepares existing and future Farabi servers for the Windows Service Agent installer.

## Patch

surhan_scanner.patches.v0_0_1.update_agent_service_installer_defaults

## What the patch updates

The patch aligns Surhan Scanner Settings with the active Windows Service installer:

- agent_download_url
- agent_latest_version
- agent_version_check_url
- agent_install_mode
- agent_install_path
- agent_spool_path
- agent_log_path
- enable_agent_health_check
- show_agent_install_dialog

## Portability Rule

The patch does not hardcode a Farabi server URL.

The following deployment-specific values are only initialized when empty:

- farabi_base_url
- agent_allowed_farabi_origins

Actual workstation configuration is handled by:

- Configure-SurhanScannerAgent.ps1

## Idempotency

The patch is safe to run multiple times.

## Expected migration command

bench --site SITE_NAME migrate

For the current development site:

bench --site ysmo migrate

## Verification

After migration, the active defaults should include:

- Agent version: 1.0.0
- Download URL: /assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe
- Install mode: Windows Service
