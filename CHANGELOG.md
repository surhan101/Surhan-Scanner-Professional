# Changelog

## Unreleased

### Added

- GitHub portability hardening.
- Windows Service Agent metadata alignment.
- Portable Farabi URL configuration.
- Windows Agent operation scripts:
  - Configure-SurhanScannerAgent.ps1
  - Update-SurhanScannerAgent.ps1
  - Uninstall-SurhanScannerAgent.ps1
- Migration patch:
  - surhan_scanner.patches.v0_0_1.update_agent_service_installer_defaults
- Root documentation:
  - README.md
  - INSTALLATION.md
  - SECURITY.md
  - CHANGELOG.md

### Changed

- Agent metadata standardized to version 1.0.0.
- Agent deployment mode standardized to Windows Service.
- Farabi URL is not hardcoded in portable Agent configuration.
- New deployments use placeholders instead of private IP addresses.

### Verified

- Agent installer points to SurhanScannerAgentSetup-1.0.0.exe.
- Installer SHA256 verified.
- Migration patch registered in patches.txt.
- Migration patch executed successfully on the development site.
