import frappe
from frappe.utils import now_datetime


def _doctype_exists(doctype):
    return frappe.db.exists("DocType", doctype)


def _has_field(doctype, fieldname):
    return frappe.get_meta(doctype).has_field(fieldname)


def mark_stale_agents_offline_task():
    try:
        from surhan_scanner.agent_api import mark_stale_agents_offline
        return mark_stale_agents_offline()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Surhan Scanner: mark stale agents failed")
        return {"success": False}


def expire_scan_sessions_task():
    candidates = [
        "Surhan Scanner Scan Session",
        "Surhan Scanner Session",
        "Surhan Scan Session",
    ]

    expired_count = 0

    for doctype in candidates:
        if not _doctype_exists(doctype):
            continue

        if not _has_field(doctype, "status"):
            continue

        date_field = None
        for field in ["expires_at", "expiry_time", "valid_until", "expire_at"]:
            if _has_field(doctype, field):
                date_field = field
                break

        if not date_field:
            continue

        names = frappe.get_all(
            doctype,
            filters={
                date_field: ["<", now_datetime()],
                "status": ["not in", ["Expired", "Cancelled", "Completed"]],
            },
            pluck="name",
            limit_page_length=500,
        )

        for name in names:
            frappe.db.set_value(doctype, name, "status", "Expired", update_modified=False)
            expired_count += 1

    frappe.db.commit()
    return {"success": True, "expired_count": expired_count}


def hourly():
    results = {
        "mark_stale_agents_offline": mark_stale_agents_offline_task(),
        "expire_scan_sessions": expire_scan_sessions_task(),
    }
    frappe.logger("surhan_scanner").info(f"Hourly cleanup completed: {results}")
    return results


def daily():
    results = {
        "mark_stale_agents_offline": mark_stale_agents_offline_task(),
        "expire_scan_sessions": expire_scan_sessions_task(),
    }
    frappe.logger("surhan_scanner").info(f"Daily cleanup completed: {results}")
    return results


def weekly():
    return {"success": True, "message": "No destructive weekly cleanup configured."}


def monthly():
    return {"success": True, "message": "No destructive monthly cleanup configured."}
