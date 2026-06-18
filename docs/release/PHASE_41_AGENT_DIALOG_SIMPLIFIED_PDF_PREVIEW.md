# Phase 41: Agent Dialog Simplification and PDF Preview

## Summary
This phase simplifies the Surhan Scanner Agent dialog without changing scan, upload, save, rule, or agent API behavior.

## Changes
- Kept only the user-changeable dialog controls:
  - Scanner device
  - Refresh devices
  - Agent health check
  - Pixel type / colors
  - Duplex
- Hidden advanced scan controls from the UI while preserving their values from Surhan Scanner Rule.
- Forced hidden effective scan settings to be read from the rule only:
  - file_type
  - resolution
  - paper_source
  - use_feeder
  - multi_page
  - silent_scan
  - show_preview
  - scan_batch_mode
  - max_pages
  - upload_strategy
- Added larger PDF preview area inside the dialog.
- Added previous/next page navigation for PDF preview.
- Kept the dialog open after successful scan/upload.
- Hid scan session id from the visible scan report.

## Not Changed
- Agent API
- Upload logic
- Save logic
- Child table attachment logic
- Rule validation
- File naming
