# Phase 42: Silent Permission Handling and Safe Global JavaScript

## Summary
This phase fixes the production issue where the scanner JavaScript was loaded globally and caused repeated permission messages and UI freezing for users who did not have scanner roles.

## Changes
- `get_scanner_config` now returns a disabled scanner configuration silently for users without scanner roles.
- Non-scanner users no longer receive visible permission dialogs from scanner configuration checks.
- Scanner execution APIs remain protected by server-side permissions.
- Client-side scanner initialization now checks scanner roles before calling scanner configuration APIs.
- Failed or unauthorized scanner config checks are cached as disabled for that form.
- Added `__surhan_scanner_checked` guard to prevent repeated config calls.
- Removed duplicate JavaScript form initializer.
- Preserved real scanner operation permissions for authorized scanner users only.

## Security Result
- Guest users receive disabled config silently.
- Normal users without scanner role receive disabled config silently.
- Scanner session creation still requires scanner role.
- Upload without token is rejected.
- Invalid or expired upload token is rejected.
- Monitoring APIs remain manager-protected.

## Test Result
- PASS: 20
- WARN: 1
- FAIL: 0
- Remaining warning is expected when Surhan Scanner Settings is disabled.
