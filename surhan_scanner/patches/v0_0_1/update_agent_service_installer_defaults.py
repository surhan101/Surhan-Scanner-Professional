# Copyright (c) 2026, Surhan
# License: MIT

"""
Align Surhan Scanner Settings with the Windows Service Agent installer.

This patch is idempotent and portable:
- It updates Agent package/version defaults to the active service installer.
- It does not hardcode a Farabi server URL.
- It does not overwrite deployment-specific Farabi URL/origin values when they already exist.
"""

from __future__ import annotations

import frappe


DOCTYPE = "Surhan Scanner Settings"

FORCED_DEFAULTS = {
    "agent_download_url": "/assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe",
    "agent_latest_version": "1.0.0",
    "agent_version_check_url": "/assets/surhan_scanner/agent/version.json",
    "agent_install_mode": "Windows Service",
    "agent_install_path": r"C:\Program Files\SurhanScannerAgent",
    "agent_spool_path": r"C:\ProgramData\SurhanScannerAgent\spool",
    "agent_log_path": r"C:\ProgramData\SurhanScannerAgent\logs",
    "enable_agent_health_check": 1,
    "show_agent_install_dialog": 1,
}

SET_IF_EMPTY_DEFAULTS = {
    "farabi_base_url": "",
    "agent_allowed_farabi_origins": "",
}


def _doctype_exists() -> bool:
    return bool(frappe.db.exists("DocType", DOCTYPE))


def _field_exists(meta, fieldname: str) -> bool:
    return bool(meta.get_field(fieldname))


def _get_single_value(fieldname: str):
    try:
        return frappe.db.get_single_value(DOCTYPE, fieldname)
    except Exception:
        return None


def _set_single_value(fieldname: str, value) -> bool:
    current = _get_single_value(fieldname)
    if current == value:
        return False

    frappe.db.set_single_value(DOCTYPE, fieldname, value)
    return True


def execute():
    if not _doctype_exists():
        return

    meta = frappe.get_meta(DOCTYPE)
    changed = False

    for fieldname, value in FORCED_DEFAULTS.items():
        if _field_exists(meta, fieldname):
            changed = _set_single_value(fieldname, value) or changed

    for fieldname, value in SET_IF_EMPTY_DEFAULTS.items():
        if not _field_exists(meta, fieldname):
            continue

        current = _get_single_value(fieldname)
        if current in (None, ""):
            changed = _set_single_value(fieldname, value) or changed

    if changed:
        frappe.clear_cache(doctype=DOCTYPE)
