# Phase 37 - GitHub Documentation Hardening

Generated: 2026-06-18T02:48:42

## Purpose

Prepare repository documentation for GitHub and multi-server deployment.

## Files Added or Updated

- README.md
- INSTALLATION.md
- SECURITY.md
- CHANGELOG.md

## Rules

- No private deployment IPs.
- No internal server hostnames.
- No private paths.
- No database backups.
- No secrets.
- Use placeholders only.

## Placeholders

- REPOSITORY_URL
- SITE_NAME
- FARABI-SERVER-IP
- https://farabi.example.com

## Related Phases

- Phase 33: Agent version metadata alignment.
- Phase 34: Farabi URL portability.
- Phase 35: Windows Agent operation scripts.
- Phase 36: Agent settings migration patch.
