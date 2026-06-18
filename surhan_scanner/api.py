
def _clean_frappe_kwargs(kwargs):
    kwargs.pop("cmd", None)
    kwargs.pop("__user", None)
    return kwargs

from surhan_scanner.core import require_scanner_access, get_rules, resolve_attach_field, resolve_barcode_required

def _clean_kwargs(kwargs):
    kwargs.pop("cmd", None)
    kwargs.pop("__user", None)
    return kwargs

from surhan_scanner.permission import require_scanner_access
import frappe

from frappe import _


def _has_any_role(roles):
    user_roles = set(frappe.get_roles(frappe.session.user))
    return bool(user_roles.intersection(set(roles)))


def _require_logged_in():
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


def _require_scanner_admin():
    _require_logged_in()
    if not _has_any_role(["Surhan Scanner Admin", "System Manager"]):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_scanner_manager():
    _require_logged_in()
    if not _has_any_role(["Surhan Scanner Manager", "Surhan Scanner Admin", "System Manager"]):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_scanner_user():
    _require_logged_in()
    if not _has_any_role(["Surhan Scanner User", "Surhan Scanner Manager", "Surhan Scanner Admin", "System Manager"]):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


from frappe.utils import now_datetime


def _get_doc_fieldnames(doctype):
    try:
        meta = frappe.get_meta(doctype)
        return {df.fieldname for df in meta.fields if df.fieldname}
    except Exception:
        return set()


def _get_value(doc, fieldname, default=None):
    try:
        value = doc.get(fieldname)
    except Exception:
        value = None

    if value in [None, ""]:
        return default

    return value


def _get_int_value(doc, fieldname, default=0):
    value = _get_value(doc, fieldname, default)

    try:
        return int(value)
    except Exception:
        return default


def _get_check_value(doc, fieldname, default=0):
    try:
        value = doc.get(fieldname)
    except Exception:
        value = default

    return 1 if value else 0


def _get_password_value(doc, fieldname):
    value = ""

    try:
        if doc.get(fieldname):
            value = doc.get_password(fieldname)
    except Exception:
        value = ""

    return value or ""


@frappe.whitelist()
def get_scanner_config(*args, **kwargs):
    require_scanner_access()
    kwargs = _clean_frappe_kwargs(kwargs)
    return _get_scanner_config(*args, **kwargs)

def _get_scanner_config(*args, **kwargs):
    require_scanner_access()
    kwargs = _clean_kwargs(kwargs)
    kwargs = _clean_frappe_kwargs(kwargs)
    return _get_scanner_config(*args, **kwargs)

def _get_scanner_config(doctype=None):
    _require_scanner_user()
    settings = frappe.get_single("Surhan Scanner Settings")

    if not settings.enabled:
        return {
            "enabled": 0,
            "settings": {},
            "rules": []
        }

    rules = []

    if doctype:
        possible_fields = [
            "name",
            "rule_name",
            "enabled",
            "target_doctype",
            "placement_type",
            "target_field",
            "upload_mode",
            "attach_field",
            "button_label",
            "button_group",
            "file_type",
            "resolution",
            "pixel_type",
            "multi_page",
            "is_private",
            "folder",
            "auto_save",
            "sort_order",
            "filename_template",
            "show_scanner_ui",
            "use_feeder",
            "duplex",

            # Surhan Agent core fields
            "scanner_engine",
            "agent_scanner_name",
            "agent_profile",

            # Surhan Professional v0.3.0 rule fields
            "paper_source",
            "silent_scan",
            "show_preview",
            "allow_page_reorder",
            "allow_page_delete",
            "scan_batch_mode",
            "max_pages",
            "upload_strategy",

            # Barcode support
            "enable_barcode",
            "barcode_field",
            "barcode_required",
            "barcode_source",
            "barcode_placeholder"
        ]

        existing_fields = _get_doc_fieldnames("Surhan Scanner Rule")
        query_fields = []

        for field in possible_fields:
            if field == "name" or field in existing_fields:
                query_fields.append(field)

        rules = frappe.get_all(
            "Surhan Scanner Rule",
            filters={
                "enabled": 1,
                "target_doctype": doctype
            },
            fields=query_fields,
            order_by="sort_order asc, modified asc"
        )

    #license_key = _get_password_value(settings, "license_key")

    return {
        "enabled": 1,
        "settings": {
            # General / Dynamsoft backward compatibility
            #"license_key": license_key,
            "license_key_configured": 1 if _get_value(settings, "license_key") else 0,
            "dialog_title": _get_value(
                settings,
                "dialog_title",
                "ماسح المستندات Document Scanner"
            ),
            "default_file_type": _get_value(
                settings,
                "default_file_type",
                "PDF"
            ),
            "default_resolution": _get_int_value(
                settings,
                "default_resolution",
                200
            ),
            "default_pixel_type": _get_value(
                settings,
                "default_pixel_type",
                "Color"
            ),
            "is_private": _get_check_value(
                settings,
                "is_private",
                1
            ),
            "folder": _get_value(
                settings,
                "folder",
                "Home/Attachments"
            ),
            "button_label": _get_value(
                settings,
                "button_label",
                "اسكانر"
            ),
            "button_group": _get_value(
                settings,
                "button_group",
                "مرفقات"
            ),
            "show_debug_button": _get_check_value(
                settings,
                "show_debug_button",
                0
            ),
            "auto_reload_after_upload": _get_check_value(
                settings,
                "auto_reload_after_upload",
                0
            ),
            "filename_template": _get_value(
                settings,
                "filename_template",
                "scan_{doctype}_{docname}_{timestamp}"
            ),
            "show_scanner_ui": _get_check_value(
                settings,
                "show_scanner_ui",
                0
            ),

            # Surhan Agent core settings
            "scanner_engine": _get_value(
                settings,
                "scanner_engine",
                "Surhan Agent"
            ),
            "agent_url": _get_value(
                settings,
                "agent_url",
                "http://127.0.0.1:8787"
            ),
            "agent_token_expiry_seconds": _get_int_value(
                settings,
                "agent_token_expiry_seconds",
                300
            ),
            "agent_scan_timeout_seconds": _get_int_value(
                settings,
                "agent_scan_timeout_seconds",
                120
            ),
            "agent_max_file_size_mb": _get_int_value(
                settings,
                "agent_max_file_size_mb",
                25
            ),
            "agent_allowed_file_types": _get_value(
                settings,
                "agent_allowed_file_types",
                "pdf,jpg,jpeg,png,txt,doc,docx,xls,xlsx,csv"
            ),
            "enable_agent_health_check": _get_check_value(
                settings,
                "enable_agent_health_check",
                1
            ),

            # Agent installer/download settings
            "agent_download_url": _get_value(
                settings,
                "agent_download_url",
                "/assets/surhan_scanner/agent/SurhanScannerAgent.exe"
            ),
            "agent_latest_version": _get_value(
                settings,
                "agent_latest_version",
                "0.3.0"
            ),
            "agent_version_check_url": _get_value(
                settings,
                "agent_version_check_url",
                "/assets/surhan_scanner/agent/version.json"
            ),
            "show_agent_install_dialog": _get_check_value(
                settings,
                "show_agent_install_dialog",
                1
            ),

            # Surhan Professional v0.3.0 install/runtime settings
            "agent_install_mode": _get_value(
                settings,
                "agent_install_mode",
                "User Startup"
            ),
            "agent_install_path": _get_value(
                settings,
                "agent_install_path",
                r"C:\Program Files\Surhan Scanner Agent"
            ),
            "agent_spool_path": _get_value(
                settings,
                "agent_spool_path",
                r"C:\ProgramData\SurhanScannerAgent\spool"
            ),
            "agent_log_path": _get_value(
                settings,
                "agent_log_path",
                r"C:\ProgramData\SurhanScannerAgent\logs"
            ),
            "enable_silent_scan": _get_check_value(
                settings,
                "enable_silent_scan",
                1
            ),
            "enable_scan_queue": _get_check_value(
                settings,
                "enable_scan_queue",
                1
            ),
            "max_concurrent_scans_per_agent": _get_int_value(
                settings,
                "max_concurrent_scans_per_agent",
                1
            ),
            "enable_upload_retry": _get_check_value(
                settings,
                "enable_upload_retry",
                1
            ),
            "upload_retry_count": _get_int_value(
                settings,
                "upload_retry_count",
                3
            ),
            "upload_retry_delay_seconds": _get_int_value(
                settings,
                "upload_retry_delay_seconds",
                5
            ),
            "max_scan_batch_pages": _get_int_value(
                settings,
                "max_scan_batch_pages",
                1000
            ),
            "max_upload_size_mb": _get_int_value(
                settings,
                "max_upload_size_mb",
                200
            )
        },
        "rules": rules
    }


@frappe.whitelist()
def get_doctype_fields(doctype=None, **kwargs):
    """Return fields for Surhan Scanner Rule UI.

    Frappe RPC may pass an internal "cmd" argument. This method accepts
    **kwargs intentionally and ignores unknown RPC keys.
    """
    require_scanner_access()

    kwargs.pop("cmd", None)

    doctype = doctype or kwargs.get("doctype")
    if not doctype:
        frappe.throw("doctype is required")

    return _get_doctype_fields(doctype)


def _build_field_item(df, fieldname=None, label=None, fieldtype=None, **extra):
    item = {
        "fieldname": fieldname or df.fieldname,
        "label": label or df.label or df.fieldname,
        "fieldtype": fieldtype or df.fieldtype,
    }

    if getattr(df, "options", None):
        item["options"] = df.options

    item.update(extra)
    return item


def _get_doctype_fields(doctype):
    _require_scanner_user()

    if not doctype:
        frappe.throw("doctype is required")

    meta = frappe.get_meta(doctype)

    all_fields = []
    attach_fields = []
    barcode_fields = []

    for df in meta.fields:
        if not df.fieldname:
            continue

        all_fields.append(_build_field_item(df))

        if df.fieldtype in ["Attach", "Attach Image"]:
            attach_fields.append(_build_field_item(df))

        elif df.fieldtype == "Table":
            table_item = _build_field_item(
                df,
                fieldtype="Table",
                is_child_table=1,
                child_doctype=df.options or "",
            )
            attach_fields.append(table_item)

            if df.options:
                try:
                    child_meta = frappe.get_meta(df.options)
                    for child_df in child_meta.fields:
                        if not child_df.fieldname:
                            continue

                        if child_df.fieldtype in ["Attach", "Attach Image"]:
                            child_label = "{0} → {1}".format(
                                df.label or df.fieldname,
                                child_df.label or child_df.fieldname,
                            )
                            attach_fields.append(
                                _build_field_item(
                                    child_df,
                                    fieldname="{0}.{1}".format(df.fieldname, child_df.fieldname),
                                    label=child_label,
                                    fieldtype=child_df.fieldtype,
                                    parent_fieldname=df.fieldname,
                                    child_doctype=df.options,
                                    child_fieldname=child_df.fieldname,
                                    is_child_table_attach=1,
                                )
                            )
                except Exception:
                    frappe.log_error(
                        frappe.get_traceback(),
                        "Surhan Scanner Child Table Field Discovery Failed",
                    )

        if df.fieldtype in ["Barcode", "Data", "Small Text"]:
            barcode_fields.append(_build_field_item(df))

    return {
        "all_fields": all_fields,
        "attach_fields": attach_fields,
        "barcode_fields": barcode_fields,
    }


@frappe.whitelist()
def create_scan_log(
    scanned_doctype=None,
    scanned_docname=None,
    file_url=None,
    file_name=None,
    rule=None,
    status="Success",
    message=None,
    scanner_engine=None,
    agent_machine_name=None,
    agent_version=None,
    agent_scanner_name=None,
    scan_session_id=None,
    file_size_bytes=None,
    barcode_value=None,
    barcode_field=None,
    barcode_source=None
):
    _require_scanner_manager()
    safe_rule = None

    if rule and frappe.db.exists("Surhan Scanner Rule", rule):
        safe_rule = rule

    data = {
        "doctype": "Surhan Scanner Log",
        "scanned_doctype": scanned_doctype,
        "scanned_docname": scanned_docname,
        "file_url": file_url,
        "file_name": file_name,
        "rule": safe_rule,
        "status": status,
        "message": message,
        "user": frappe.session.user,
        "scan_datetime": now_datetime()
    }

    log_fields = _get_doc_fieldnames("Surhan Scanner Log")

    optional_fields = {
        "scanner_engine": scanner_engine,
        "agent_machine_name": agent_machine_name,
        "agent_version": agent_version,
        "agent_scanner_name": agent_scanner_name,
        "scan_session_id": scan_session_id,
        "file_size_bytes": file_size_bytes,
        "barcode_value": barcode_value,
        "barcode_field": barcode_field,
        "barcode_source": barcode_source
    }

    for fieldname, value in optional_fields.items():
        if fieldname in log_fields:
            data[fieldname] = value

    doc = frappe.get_doc(data)
    doc.insert(ignore_permissions=True)

    return doc.name