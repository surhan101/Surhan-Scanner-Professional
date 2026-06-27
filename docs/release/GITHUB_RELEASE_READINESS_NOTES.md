# GitHub Release Readiness Notes

Generated: 2026-06-18T02:50:25

## Branch

testing/phase-32-github-portability-release-hardening

## Baseline

This branch extends the production-ready Windows Service installer baseline.

## Included Phases

- Phase 33: Agent service installer version metadata alignment.
- Phase 34: Farabi URL portability.
- Phase 35: Windows Agent operation scripts.
- Phase 36: Agent settings migration patch.
- Phase 37: GitHub deployment documentation.
- Phase 38: Repository hygiene and release readiness.

## Agent Release

- Version: 1.0.0
- Deployment mode: Windows Service
- Installer: SurhanScannerAgentSetup-1.0.0.exe
- Installer URL: /assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe
- SHA256: 63a2427c0f4e03749d1399db984e15593d259db7a3ff825dd5109cd570f6ff18

## Portability

The repository is prepared for multi-server deployment. Deployment-specific Farabi URLs must be configured at workstation setup time using:

Configure-SurhanScannerAgent.ps1

## Migration

The following patch aligns existing and new sites with the Windows Service Agent defaults:

surhan_scanner.patches.v0_0_1.update_agent_service_installer_defaults

## GitHub Safety Rules

The repository should not contain:

- private site files
- database backups
- real server IP addresses
- private hostnames
- passwords or tokens
- private audit exports
