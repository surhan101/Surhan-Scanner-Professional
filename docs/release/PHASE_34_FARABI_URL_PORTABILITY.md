# Phase 34 - Farabi URL Portability

## Purpose

Prepare Surhan Scanner for installation on any Farabi/Frappe server without hardcoding the current development server IP address.

## Changes

This phase adds portable configuration fields to Surhan Scanner Settings:

- farabi_base_url
- agent_allowed_farabi_origins
- agent_config_note

It also changes the public Agent configuration template:

surhan_scanner/public/agent/surhan_agent_config.json

so that it no longer contains deployment-specific Farabi origins such as lab IP addresses.

## Important Scope Note

This phase does not rebuild the Windows EXE installer.

The currently active installer remains:

SurhanScannerAgentSetup-1.0.0.exe

Because the installer binary may contain its own packaged configuration, every Windows workstation must still be configured after installation using the dedicated configuration script introduced in the next phase.

## Expected Production Flow

1. Install the Frappe app on a Farabi server.
2. Configure Farabi Base URL in Surhan Scanner Settings.
3. Download and install SurhanScannerAgentSetup-1.0.0.exe on the Windows workstation.
4. Run Configure-SurhanScannerAgent.ps1 with the Farabi URL.
5. Verify the Agent health endpoint:
   http://127.0.0.1:8787/health

## Why allowed_farabi_origins is not hardcoded

The Windows Agent receives browser requests from the Farabi web page. Therefore, the allowed CORS origin must match the actual Farabi origin used by the user, for example:

- https://farabi.example.com
- http://192.168.1.50

This value is different for each deployment and must not be fixed in the GitHub source code.

## Result

The application metadata is now portable. The remaining deployment-specific Windows workstation configuration will be handled by Phase 35 scripts.
