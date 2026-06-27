import frappe


SCANNER_ROLES = [
    {
        "role_name": "Surhan Scanner User",
        "desk_access": 1,
        "description": "Can use Surhan Scanner on permitted documents."
    },
    {
        "role_name": "Surhan Scanner Manager",
        "desk_access": 1,
        "description": "Can monitor Surhan Scanner Agents and scan activity."
    },
    {
        "role_name": "Surhan Scanner Admin",
        "desk_access": 1,
        "description": "Can administer Surhan Scanner settings, rules, and agents."
    },
]


def before_install():
    create_scanner_roles()


def after_install():
    create_scanner_roles()
    create_default_settings()


def create_scanner_roles():
    for role in SCANNER_ROLES:
        role_name = role["role_name"]
        if frappe.db.exists("Role", role_name):
            continue

        doc = frappe.get_doc({
            "doctype": "Role",
            "role_name": role_name,
            "desk_access": role.get("desk_access", 1),
            "description": role.get("description", ""),
        })
        doc.insert(ignore_permissions=True)

    frappe.db.commit()


def create_default_settings():
    if not frappe.db.exists("Surhan Scanner Settings", "Surhan Scanner Settings"):
        doc = frappe.get_doc({
            "doctype": "Surhan Scanner Settings",
            "enabled": 1,
            "dialog_title": "ماسح المستندات Document Scanner",
            "default_file_type": "PDF",
            "default_resolution": 200,
            "default_pixel_type": "Color",
            "is_private": 1,
            "folder": "Home/Attachments",
            "button_label": "اسكانر",
            "button_group": "مرفقات",
            "show_debug_button": 0,
            "auto_reload_after_upload": 1,
            "filename_template": "scan_{doctype}_{docname}_{timestamp}",
            "show_scanner_ui": 1,
            "scanner_engine": "Surhan Agent",
            "agent_url": "http://127.0.0.1:8787",
            "agent_token_expiry_seconds": 300,
            "agent_scan_timeout_seconds": 120,
            "agent_max_file_size_mb": 100,
            "agent_allowed_file_types": "pdf,jpg,jpeg,png,tif,tiff",
            "agent_download_url": "/assets/surhan_scanner/agent/releases/SurhanScannerAgentSetup-1.0.0.exe",
            "agent_latest_version": "1.0.0",
            "farabi_base_url": "",
            "agent_allowed_farabi_origins": "",
            "agent_version_check_url": "/assets/surhan_scanner/agent/version.json",
            "show_agent_install_dialog": 1,
            "max_upload_size_mb": 100,
            "rate_limit_window_seconds": 300,
            "create_scan_session_rate_limit": 60,
            "upload_scan_ip_rate_limit": 1000,
            "upload_scan_user_rate_limit": 120,
            "agent_heartbeat_ip_rate_limit": 1000,
            "agent_update_check_ip_rate_limit": 1000,
            "agent_update_status_ip_rate_limit": 1000,
            "attach_lock_timeout_seconds": 8,
        })
        doc.insert(ignore_permissions=True)
        frappe.db.commit()
