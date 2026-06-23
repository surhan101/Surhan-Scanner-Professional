import frappe

def require_scanner_access():
    roles = frappe.get_roles(frappe.session.user)

    if "System Manager" in roles:
        return

    if "Surhan Scanner Admin" in roles:
        return

    if "Surhan Scanner User" in roles:
        return

    frappe.throw("غير مصرح لك باستخدام نظام الاسكانر", frappe.PermissionError)
