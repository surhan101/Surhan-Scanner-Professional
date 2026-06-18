# Phase 40 - Child Table Attach and File Naming Fix

Generated: 2026-06-18T03:48:54

## Problem

Opening Surhan Scanner Rule raised:

TypeError: _get_doctype_fields() got an unexpected keyword argument 'cmd'

Also, rules configured with "All Attach Fields" did not add a scanner button when the target document only had Attach fields inside a child table.

## Fixes

- Fixed get_doctype_fields to ignore Frappe RPC cmd.
- Removed the duplicate _get_doctype_fields implementation issue.
- Added direct Attach field discovery.
- Added child Table discovery.
- Added dotted child attach field options such as:
  table_field.attachment_file
- Added frontend scanner button support for Table fields.
- Fixed server-side Table routing so scans append a child row.
- Added default scan filename format:

Doctype_Docname_User_YYMMDD_HHMM.ext

## Notes

If a child table has mandatory Link fields without defaults, administrators may still need to configure those fields or provide defaults.
