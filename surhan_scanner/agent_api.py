import os
import re
import time
import json
import uuid
import secrets
import hashlib
import base64
import binascii
import tempfile

import frappe
from frappe import _
from frappe.utils import now_datetime, add_to_date, get_url, cint, get_datetime
from frappe.utils.file_manager import save_file
from frappe.utils.data import now


def _has_any_scanner_role(roles):
    """يتحقق هل المستخدم الحالي يملك أحد الأدوار المطلوبة."""
    user_roles = set(frappe.get_roles(frappe.session.user))
    return bool(user_roles.intersection(set(roles)))


def _require_logged_in_api():
    """يمنع الضيف من استدعاء API داخلي."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"), frappe.PermissionError)


def _require_scanner_user_api():
    """يسمح لمستخدمين Surhan Scanner الأساسيين."""
    _require_logged_in_api()
    if not _has_any_scanner_role([
        "Surhan Scanner User",
        "Surhan Scanner Manager",
        "Surhan Scanner Admin",
        "System Manager",
    ]):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_scanner_manager_api():
    """يسمح لمديري Surhan Scanner ولوحة المراقبة."""
    _require_logged_in_api()
    if not _has_any_scanner_role([
        "Surhan Scanner Manager",
        "Surhan Scanner Admin",
        "System Manager",
    ]):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def _require_scanner_admin_api():
    """يسمح للمشرفين فقط في العمليات الحساسة."""
    _require_logged_in_api()
    if not _has_any_scanner_role([
        "Surhan Scanner Admin",
        "System Manager",
    ]):
        frappe.throw(_("Not permitted"), frappe.PermissionError)


CACHE_PREFIX = "surhan_scanner:scan_session:"

CHUNK_SIZE = 1024 * 1024
MAGIC_READ_SIZE = 8192

RATE_LIMIT_WINDOW_SECONDS = 300
CREATE_SCAN_SESSION_LIMIT = 60
UPLOAD_SCAN_IP_LIMIT = 1000
UPLOAD_SCAN_USER_LIMIT = 120
AGENT_HEARTBEAT_IP_LIMIT = 1000

AGENT_UPDATE_CHECK_IP_LIMIT = 1000
AGENT_UPDATE_STATUS_IP_LIMIT = 1000
AGENT_MANIFEST_FILENAME = "update_manifest.json"

AGENT_OFFLINE_AFTER_SECONDS = 300
AGENT_DEVICE_DOCTYPE = "Surhan Scanner Agent Device"

SCANNER_ALLOWED_ROLES = {
    "Surhan Scanner User",
    "Surhan Scanner Manager",
    "Surhan Scanner Admin",
    "System Manager",
}

SCANNER_MANAGER_ROLES = {
    "Surhan Scanner Manager",
    "Surhan Scanner Admin",
    "System Manager",
}

SAFE_SCAN_EXTENSIONS = {
    "pdf", "jpg", "jpeg", "png", "tif", "tiff"
}

BLOCKED_DOCUMENT_EXTENSIONS = {
    "txt", "csv", "rtf",
    "doc", "docx", "docm",
    "xls", "xlsx", "xlsm",
    "ppt", "pptx", "pptm",
    "odt", "ods", "odp",
}

DANGEROUS_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "scr", "ps1", "vbs", "js",
    "html", "htm", "php", "asp", "aspx", "jsp", "jar",
    "dll", "msi", "sh", "svg",
}

MAGIC_BYTES = {
    "pdf": [b"%PDF"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "tif": [b"II*\x00", b"MM\x00*"],
    "tiff": [b"II*\x00", b"MM\x00*"],
}

MIME_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tif": "image/tiff",
    "tiff": "image/tiff",
}


def _user_has_scanner_role(user):
    """يتحقق أن المستخدم يملك أحد أدوار Surhan Scanner."""
    if not user or user == "Guest":
        return False

    if user == "Administrator":
        return True

    try:
        user_roles = set(frappe.get_roles(user))
    except Exception:
        user_roles = set()

    return bool(user_roles.intersection(SCANNER_ALLOWED_ROLES))


def _enforce_scanner_role(user=None):
    """يمنع استخدام Surhan Scanner إلا لمن لديه دور Scanner."""
    user = user or frappe.session.user

    if not _user_has_scanner_role(user):
        frappe.local.response.http_status_code = 403
        frappe.throw(
            _("You do not have a Surhan Scanner role. Please contact the system administrator.")
        )


def _user_has_scanner_manager_role(user):
    """يتحقق أن المستخدم يملك صلاحية مراقبة وإدارة Agents."""
    if not user or user == "Guest":
        return False

    if user == "Administrator":
        return True

    try:
        user_roles = set(frappe.get_roles(user))
    except Exception:
        user_roles = set()

    return bool(user_roles.intersection(SCANNER_MANAGER_ROLES))


def _enforce_scanner_manager_role(user=None):
    """يسمح بعرض Monitoring للمديرين فقط."""
    user = user or frappe.session.user

    if not _user_has_scanner_manager_role(user):
        frappe.local.response.http_status_code = 403
        frappe.throw(
            _("You do not have permission to monitor Surhan Scanner Agents.")
        )


def _agent_device_doctype_exists():
    """يتحقق من وجود DocType الخاص بمراقبة أجهزة Agent."""
    return frappe.db.exists("DocType", AGENT_DEVICE_DOCTYPE)


def _safe_agent_text(value, max_length=140):
    """ينظف النصوص القادمة من Agent ويقصها لطول آمن."""
    value = str(value or "").strip()
    value = value.replace("\x00", "")
    return value[:max_length]


def _make_agent_id(agent_id=None, machine_name=None, windows_user=None, ip_address=None):
    """ينشئ Agent ID ثابت."""
    if agent_id:
        clean_agent_id = _safe_agent_text(agent_id, 120)
        clean_agent_id = clean_agent_id.replace("/", "_").replace("\\", "_")
        return clean_agent_id

    raw = "{0}:{1}:{2}".format(
        machine_name or "unknown-machine",
        windows_user or "unknown-user",
        ip_address or "unknown-ip",
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return "AGENT-" + digest


def _doc_has_field(doc, fieldname):
    """يتحقق أن الحقل موجود داخل DocType قبل الكتابة عليه."""
    try:
        return bool(doc.meta.get_field(fieldname))
    except Exception:
        return False


def _set_doc_value_if_field(doc, fieldname, value):
    """يضبط قيمة الحقل فقط إذا كان الحقل موجودًا."""
    if _doc_has_field(doc, fieldname):
        doc.set(fieldname, value)


def _get_scan_token_remaining_seconds(session_data):
    """يحسِب الوقت المتبقي لانتهاء scan_token."""
    try:
        expires_at = session_data.get("expires_at")

        if not expires_at:
            return cint(session_data.get("expires_in") or 300)

        remaining = int((get_datetime(expires_at) - now_datetime()).total_seconds())
        if remaining <= 0:
            return 0

        return min(remaining, cint(session_data.get("expires_in") or 300))
    except Exception:
        return 300


def _get_request_ip():
    """يجلب IP الطلب الحالي من Headers أو من الطلب مباشرة."""
    try:
        request = getattr(frappe.local, "request", None)

        if request:
            forwarded_for = request.headers.get("X-Forwarded-For")
            if forwarded_for:
                return forwarded_for.split(",")[0].strip()

            real_ip = request.headers.get("X-Real-IP")
            if real_ip:
                return real_ip.strip()

            if request.remote_addr:
                return request.remote_addr

        request_ip = getattr(frappe.local, "request_ip", None)
        if request_ip:
            return request_ip

    except Exception:
        pass

    return "unknown"


def _make_rate_limit_identity(value):
    """يحولهة المستخدم أو IP إلى hash مختصر."""
    value = str(value or "unknown")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _rate_limit_cache_key(action, identity, window_seconds):
    """ينشئ مفتاح rate limit داخل الكاش."""
    bucket = int(time.time() // window_seconds)
    safe_identity = _make_rate_limit_identity(identity)

    return "surhan_scanner:rate_limit:{0}:{1}:{2}".format(
        action,
        safe_identity,
        bucket,
    )


def _consume_rate_limit(action, identity, limit, window_seconds=RATE_LIMIT_WINDOW_SECONDS):
    """يستهلك محاولة واحدة من الحد المسموح."""
    if not limit or limit <= 0:
        return {"allowed": True, "remaining": None, "retry_after": 0}

    key = _rate_limit_cache_key(action, identity, window_seconds)

    try:
        current = frappe.cache().get_value(key)
        current = cint(current or 0)
    except Exception:
        current = 0

    if current >= limit:
        elapsed = int(time.time() % window_seconds)
        retry_after = max(window_seconds - elapsed, 1)
        return {"allowed": False, "remaining": 0, "retry_after": retry_after}

    current += 1

    try:
        frappe.cache().set_value(key, current, expires_in_sec=window_seconds + 5)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Surhan Scanner Rate Limit Cache Failed")

    return {"allowed": True, "remaining": max(limit - current, 0), "retry_after": 0}


def _rate_limit_response(result):
    """يرجع 429 عند تجاوز الحد."""
    retry_after = cint(result.get("retry_after") or RATE_LIMIT_WINDOW_SECONDS)
    return _response(
        429,
        False,
        "Too many requests. Please try again later.",
        {"retry_after_seconds": retry_after},
    )



def _enforce_create_scan_session_rate_limit():
    """يطبق rate limit على إنشاء جلسات المسح."""
    user = frappe.session.user or "Guest"
    ip_address = _get_request_ip()

    identity = "create_scan_session:user:{0}:ip:{1}".format(user, ip_address)
    rate_limits = _get_rate_limit_settings()

    result = _consume_rate_limit(
        action="create_scan_session",
        identity=identity,
        limit=rate_limits["create_scan_session_limit"],
        window_seconds=rate_limits["window_seconds"],
    )

    if not result.get("allowed"):
        frappe.local.response.http_status_code = 429
        frappe.throw(
            _("Too many scan session requests. Please try again after {0} seconds.").format(
                result.get("retry_after")
            )
        )


def _check_upload_ip_rate_limit():
    """يطبق rate limit على رفع الملفات حسب IP."""
    ip_address = _get_request_ip()
    identity = "upload_agent_scan:ip:{0}".format(ip_address)
    rate_limits = _get_rate_limit_settings()

    return _consume_rate_limit(
        action="upload_agent_scan_ip",
        identity=identity,
        limit=rate_limits["upload_scan_ip_limit"],
        window_seconds=rate_limits["window_seconds"],
    )


def _check_upload_user_rate_limit(session_user):
    """يطبق rate limit على رفع الملفات حسب المستخدم صاحب الجلسة."""
    identity = "upload_agent_scan:user:{0}".format(session_user or "unknown")
    rate_limits = _get_rate_limit_settings()

    return _consume_rate_limit(
        action="upload_agent_scan_user",
        identity=identity,
        limit=rate_limits["upload_scan_user_limit"],
        window_seconds=rate_limits["window_seconds"],
    )


def _check_agent_heartbeat_rate_limit():
    """يطبق rate limit على agent heartbeat حسب IP."""
    ip_address = _get_request_ip()
    identity = "agent_heartbeat:ip:{0}".format(ip_address)
    rate_limits = _get_rate_limit_settings()

    return _consume_rate_limit(
        action="agent_heartbeat_ip",
        identity=identity,
        limit=rate_limits["agent_heartbeat_ip_limit"],
        window_seconds=rate_limits["window_seconds"],
    )


def _check_agent_update_rate_limit(action_name):
    """يطبق rate limit على طلبات تحديث Agent حسب IP."""
    ip_address = _get_request_ip()
    identity = "{0}:ip:{1}".format(action_name, ip_address)

    if action_name == "agent_update_status":
        limit_key = "agent_update_status_ip_limit"
    else:
        limit_key = "agent_update_check_ip_limit"

    rate_limits = _get_rate_limit_settings()

    return _consume_rate_limit(
        action=action_name,
        identity=identity,
        limit=rate_limits[limit_key],
        window_seconds=rate_limits["window_seconds"],
    )

def _get_settings():
    """يجلب إعدادات Surhan Scanner."""
    return frappe.get_single("Surhan Scanner Settings")


def _get_value(doc, fieldname, default=None):
    """يجلب قيمة حقل مع قيمة افتراضية عند الفراغ."""
    try:
        value = doc.get(fieldname)
    except Exception:
        value = None
    return default if value in [None, ""] else value


def _get_rule_value(rule_doc, fieldname, default=None):
    """يجلب قيمة من Rule مع تجاهل Default والفارغ."""
    value = _get_value(rule_doc, fieldname, default)
    if value in [None, "", "Default"]:
        return default
    return value


def _get_int_value(doc, fieldname, default=0):
    """يجلب قيمة رقمية من مستند."""
    try:
        return int(_get_value(doc, fieldname, default))
    except Exception:
        return default


def _get_check_value(doc, fieldname, default=0):
    """يجلب قيمة Checkbox كـ 1 أو 0."""
    try:
        value = doc.get(fieldname)
    except Exception:
        value = default
    return 1 if value else 0


def _get_bounded_int_setting(settings, fieldname, default, minimum, maximum):
    """Read an integer setting with safe fallback bounds."""
    value = _get_int_value(settings, fieldname, default)

    if value < minimum or value > maximum:
        return default

    return value


def _get_rate_limit_settings(settings=None):
    """Read rate-limit settings from Surhan Scanner Settings with safe defaults."""
    settings = settings or _get_settings()

    return {
        "window_seconds": _get_bounded_int_setting(
            settings, "rate_limit_window_seconds", RATE_LIMIT_WINDOW_SECONDS, 60, 3600
        ),
        "create_scan_session_limit": _get_bounded_int_setting(
            settings, "create_scan_session_rate_limit", CREATE_SCAN_SESSION_LIMIT, 1, 1000
        ),
        "upload_scan_ip_limit": _get_bounded_int_setting(
            settings, "upload_scan_ip_rate_limit", UPLOAD_SCAN_IP_LIMIT, 1, 10000
        ),
        "upload_scan_user_limit": _get_bounded_int_setting(
            settings, "upload_scan_user_rate_limit", UPLOAD_SCAN_USER_LIMIT, 1, 1000
        ),
        "agent_heartbeat_ip_limit": _get_bounded_int_setting(
            settings, "agent_heartbeat_ip_rate_limit", AGENT_HEARTBEAT_IP_LIMIT, 1, 10000
        ),
        "agent_update_check_ip_limit": _get_bounded_int_setting(
            settings, "agent_update_check_ip_rate_limit", AGENT_UPDATE_CHECK_IP_LIMIT, 1, 10000
        ),
        "agent_update_status_ip_limit": _get_bounded_int_setting(
            settings, "agent_update_status_ip_rate_limit", AGENT_UPDATE_STATUS_IP_LIMIT, 1, 10000
        ),
    }


def _get_attach_lock_timeout_seconds(settings=None):
    """Read attachment lock wait timeout from settings with safe bounds."""
    settings = settings or _get_settings()
    return _get_bounded_int_setting(
        settings, "attach_lock_timeout_seconds", 8, 1, 60
    )


def _split_allowed_file_types(value):
    """يحولهة الامتدادات من نص إلى list."""
    if not value:
        return []
    return [
        item.strip().lower().lstrip(".")
        for item in str(value).replace("\n", ",").split(",")
        if item.strip()
    ]


def _safe_filename(filename):
    """ينظف اسم الملف من المسارات والرموز الخطرة."""
    filename = os.path.basename(filename or "scan_file")
    filename = filename.replace("\\", "_").replace("/", "_").replace("\x00", "_")
    return filename


def _get_extension(filename):
    """يستخرج امتداد الملف."""
    if not filename or "." not in filename:
        return ""
    return filename.rsplit(".", 1)[-1].lower().strip()


def _make_scan_session_id():
    """ينشئ رقم جلسة مسح فريد."""
    return "SCAN-" + now_datetime().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(8)


def _make_scan_token(scan_session_id):
    """ينشئ scan token آمن."""
    random_part = secrets.token_hex(32)
    raw = f"{scan_session_id}:{random_part}:{now()}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _cache_key(scan_token):
    """ينشئ مفتاح كاش لجلسة المسح."""
    return CACHE_PREFIX + scan_token


def _cache_set(scan_token, data, expires_in_seconds):
    """يخزن جلسة المسح مؤقتًا."""
    frappe.cache().set_value(
        _cache_key(scan_token),
        frappe.as_json(data),
        expires_in_sec=expires_in_seconds,
    )


def _cache_get(scan_token):
    """يجلب جلسة المسح من الكاش."""
    value = frappe.cache().get_value(_cache_key(scan_token))
    if not value:
        return None
    if isinstance(value, dict):
        return value
    return frappe.parse_json(value)


def _cache_delete(scan_token):
    """يحذف جلسة المسح من الكاش."""
    frappe.cache().delete_value(_cache_key(scan_token))


def _delete_temp_file(path):
    """يحذف الملف المؤقت."""
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Surhan Scanner Temp File Delete Failed")


def _read_uploaded_stream_to_temp(uploaded_file, max_bytes):
    """يقرأ ملف multipart على أجزاء ويحفظه مؤقتًا."""
    temp_path = None
    total_size = 0
    head = b""

    temp_file = tempfile.NamedTemporaryFile(
        prefix="surhan_scan_",
        suffix=".upload",
        delete=False,
    )
    temp_path = temp_file.name

    try:
        while True:
            chunk = uploaded_file.stream.read(CHUNK_SIZE)
            if not chunk:
                break

            total_size += len(chunk)

            if total_size > max_bytes:
                temp_file.close()
                _delete_temp_file(temp_path)
                frappe.throw(_("Uploaded file exceeds maximum allowed size"))

            if len(head) < MAGIC_READ_SIZE:
                remaining = MAGIC_READ_SIZE - len(head)
                head += chunk[:remaining]

            temp_file.write(chunk)

        temp_file.flush()
        temp_file.close()

        return {"temp_path": temp_path, "file_size": total_size, "head": head}

    except Exception:
        try:
            temp_file.close()
        except Exception:
            pass
        _delete_temp_file(temp_path)
        raise


def _write_bytes_to_temp(content, max_bytes):
    """يحفظ محتوى base64 المفكوك في ملف مؤقت."""
    if not content:
        frappe.throw(_("Uploaded file is empty"))

    file_size = len(content)

    if file_size > max_bytes:
        frappe.throw(_("Uploaded file exceeds maximum allowed size"))

    temp_file = tempfile.NamedTemporaryFile(
        prefix="surhan_scan_",
        suffix=".upload",
        delete=False,
    )
    temp_path = temp_file.name

    try:
        temp_file.write(content)
        temp_file.flush()
        temp_file.close()

        return {"temp_path": temp_path, "file_size": file_size, "head": content[:MAGIC_READ_SIZE]}

    except Exception:
        try:
            temp_file.close()
        except Exception:
            pass
        _delete_temp_file(temp_path)
        raise


def _read_temp_file_content(temp_path):
    """يقرأ الملف المؤقت قبل الحفظ في Frappe File."""
    with open(temp_path, "rb") as file:
        return file.read()


def _ensure_binary_file_content(content):
    """يضمن أن محتوى الملف bytes قبل تمريره إلى Frappe save_file."""
    if content is None:
        return b""

    if isinstance(content, bytes):
        return content

    if isinstance(content, bytearray):
        return bytes(content)

    if isinstance(content, memoryview):
        return content.tobytes()

    if isinstance(content, str):
        try:
            return content.encode("latin-1")
        except Exception:
            return content.encode("utf-8", errors="ignore")

    try:
        return bytes(content)
    except Exception:
        frappe.throw(_("Invalid uploaded file content"))


def _validate_scan_file_content_before_save(filename, content, extension=None):
    """
    يفحص PDF والصور قبل save_file حتى لا تتحول الملفات التالفة إلى HTTP 500.
    """
    content = _ensure_binary_file_content(content)
    extension = (extension or _get_extension(filename) or "").lower().strip()

    if not content:
        frappe.throw(_("Uploaded file is empty"))

    if extension == "pdf":
        try:
            from io import BytesIO
            from pypdf import PdfReader

            PdfReader(BytesIO(content))
        except Exception:
            frappe.throw(_("Invalid or corrupted PDF file"))

    elif extension in {"jpg", "jpeg", "png", "tif", "tiff"}:
        try:
            from io import BytesIO
            from PIL import Image

            image = Image.open(BytesIO(content))
            image.verify()
        except Exception:
            frappe.throw(_("Invalid or corrupted image file"))

    return content


def _validate_target_doc(doctype, docname, permission_type="write"):
    """يتحقق من وجود المستند وصلاحية المستخدم عليه."""
    if not doctype or not docname:
        frappe.throw(_("Doctype and Docname are required"))

    if not frappe.db.exists(doctype, docname):
        frappe.throw(_("Target document does not exist"))

    doc = frappe.get_doc(doctype, docname)

    if not frappe.has_permission(doctype, "read", doc=doc):
        frappe.throw(_("You do not have permission to access this document"))

    if permission_type and not frappe.has_permission(doctype, permission_type, doc=doc):
        frappe.throw(_("You do not have permission to attach scanned files to this document"))

    return doc


def _split_child_attach_field(attach_field):
    value = str(attach_field or "").strip()
    if "." not in value:
        return value, ""

    table_field, child_field = value.split(".", 1)
    return table_field.strip(), child_field.strip()


def _first_child_attach_field(child_meta):
    if child_meta.get_field("attachment_file") and child_meta.get_field("attachment_file").fieldtype in ["Attach", "Attach Image"]:
        return "attachment_file"

    for child_df in child_meta.fields:
        if child_df.fieldname and child_df.fieldtype in ["Attach", "Attach Image"]:
            return child_df.fieldname

    return ""


def _resolve_attach_target(doctype, attach_field):
    """Resolve a direct Attach field or a child-table Attach target.

    Supported values:
    - direct_attach_field
    - child_table_field
    - child_table_field.child_attach_field
    """
    if not attach_field:
        return None

    meta = frappe.get_meta(doctype)
    table_field, child_attach_field = _split_child_attach_field(attach_field)

    df = meta.get_field(table_field)
    if not df:
        frappe.throw(_("Attach field does not exist: {0}").format(attach_field))

    if df.fieldtype in ["Attach", "Attach Image"] and not child_attach_field:
        return {
            "mode": "direct",
            "attach_field": table_field,
            "df": df,
        }

    if df.fieldtype != "Table":
        frappe.throw(_("Target field must be Attach, Attach Image, or Table"))

    child_doctype = df.options
    if not child_doctype:
        frappe.throw(_("Table field has no child doctype: {0}").format(table_field))

    child_meta = frappe.get_meta(child_doctype)

    if child_attach_field:
        child_df = child_meta.get_field(child_attach_field)
        if not child_df:
            frappe.throw(_("Child attach field does not exist: {0}").format(attach_field))
        if child_df.fieldtype not in ["Attach", "Attach Image"]:
            frappe.throw(_("Child field must be Attach or Attach Image: {0}").format(attach_field))
    else:
        child_attach_field = _first_child_attach_field(child_meta)
        if not child_attach_field:
            frappe.throw(_("No Attach field found inside child table: {0}").format(child_doctype))
        child_df = child_meta.get_field(child_attach_field)

    return {
        "mode": "child_table",
        "table_field": table_field,
        "child_doctype": child_doctype,
        "child_attach_field": child_attach_field,
        "df": df,
        "child_df": child_df,
    }


def _validate_attach_field(doctype, attach_field):
    """Validate direct Attach fields and child-table Attach targets."""
    if not attach_field:
        return

    _resolve_attach_target(doctype, attach_field)


def _get_file_doc_attach_field_for_save(doctype, attach_field):
    """Return df value suitable for Frappe save_file.

    For child table targets we return None because the actual child row is
    appended after the File document is created.
    """
    if not attach_field:
        return None

    try:
        target = _resolve_attach_target(doctype, attach_field)
    except Exception:
        return None

    if target and target.get("mode") == "direct":
        return target.get("attach_field")

    return None



def _validate_barcode_field(doctype, barcode_field):
    """يتحقق أن حقل الباركود موجود ومناسب للتعبئة من قارئ USB أو إدخال يدوي."""
    if not barcode_field:
        return None

    meta = frappe.get_meta(doctype)
    df = meta.get_field(barcode_field)

    if not df:
        frappe.throw(_("Barcode field does not exist: {0}").format(barcode_field))

    if df.fieldtype not in ["Barcode", "Data", "Small Text"]:
        frappe.throw(_("Barcode field must be Barcode, Data, or Small Text"))

    if cint(getattr(df, "read_only", 0)):
        frappe.throw(_("Barcode field is read only: {0}").format(barcode_field))

    return df


def _normalize_barcode_value(value, max_length=255):
    """ينظف قيمة الباركود القادمة من قارئ USB/الكاميرا قبل حفظها."""
    value = str(value or "").strip()
    value = value.replace("\x00", "")
    value = value.replace("\r", "").replace("\n", "")
    return value[:max_length]


def _resolve_barcode_payload(rule_doc, doctype, barcode_field=None, barcode_value=None, barcode_source=None):
    """يحدد إعدادات الباركود من Rule ثم يتحقق من القيمة والحقل."""
    enabled = cint(rule_doc.get("enable_barcode") or 0)

    if not enabled and not barcode_field and not barcode_value:
        return {"barcode_field": "", "barcode_value": "", "barcode_source": ""}

    resolved_field = barcode_field or rule_doc.get("barcode_field") or ""
    resolved_source = barcode_source or rule_doc.get("barcode_source") or "USB Keyboard Scanner"
    resolved_value = _normalize_barcode_value(barcode_value, 255)

    if resolved_field:
        _validate_barcode_field(doctype, resolved_field)

    if cint(rule_doc.get("barcode_required") or 0) and not resolved_value:
        frappe.throw(_("Barcode value is required for this scanner rule"))

    if resolved_value and not resolved_field:
        frappe.throw(_("Barcode field is required when barcode value is provided"))

    return {
        "barcode_field": resolved_field,
        "barcode_value": resolved_value,
        "barcode_source": _safe_agent_text(resolved_source, 50),
    }


def _normalize_upload_mode(upload_mode):
    """يضبط وضع الرفع إلى قيمة معروفة."""
    if upload_mode not in ["Attachment Only", "Set Attach Field", "Both"]:
        return "Attachment Only"
    return upload_mode


def _validate_scanner_rule(rule, doctype):
    """يتحقق أن Rule موجودة ومفعلة ومطابقة للـ DocType."""
    if not rule:
        frappe.throw(_("Scanner rule is required"))

    if not frappe.db.exists("Surhan Scanner Rule", rule):
        frappe.throw(_("Invalid scanner rule"))

    rule_doc = frappe.get_doc("Surhan Scanner Rule", rule)

    if not cint(rule_doc.get("enabled")):
        frappe.throw(_("Scanner rule is disabled"))

    if rule_doc.get("target_doctype") != doctype:
        frappe.throw(_("Scanner rule does not match target DocType"))

    return rule_doc


def _resolve_rule_upload_target(rule_doc, doctype, requested_attach_field=None):
    """يحدد upload_mode و attach_field من Rule وليس من العميل."""
    upload_mode = _normalize_upload_mode(rule_doc.get("upload_mode") or "Attachment Only")
    attach_field = ""

    if upload_mode in ["Set Attach Field", "Both"]:
        if rule_doc.get("placement_type") == "All Attach Fields":
            attach_field = requested_attach_field or rule_doc.get("attach_field")
        else:
            attach_field = rule_doc.get("attach_field") or rule_doc.get("target_field") or ""

        if not attach_field:
            frappe.throw(_("Attach field is required for this scanner rule"))

        _validate_attach_field(doctype, attach_field)

    return upload_mode, attach_field


def _user_can_customize_scan_filename(user=None):
    """يتحقق هل المستخدم يملك صلاحية تخصيص اسم الملف."""
    return _user_has_scanner_manager_role(user or frappe.session.user)


def _normalize_custom_scan_filename(file_name):
    """
    ينظف الاسم المخصص للملف بحيث يبقى صالحًا كاسم ملف.
    """
    file_name = _safe_filename(file_name)
    file_name = file_name.replace("\n", " ").replace("\r", " ").strip()
    return file_name[:140]


def _safe_scan_filename_part(value, default="item", max_length=60):
    value = _safe_filename(str(value or default))
    value = value.replace(" ", "-").replace("/", "-").replace("\\", "-")
    value = value.strip("._-")
    return (value or default)[:max_length]


def _build_default_scan_filename(original_filename, session_data=None):
    session_data = session_data or {}

    extension = _get_extension(original_filename) or "pdf"

    doctype_part = _safe_scan_filename_part(
        session_data.get("doctype"),
        "Doctype",
        40,
    )
    docname_part = _safe_scan_filename_part(
        session_data.get("docname"),
        "Document",
        70,
    )
    user_part = _safe_scan_filename_part(
        session_data.get("user") or frappe.session.user,
        "user",
        50,
    )
    date_part = now_datetime().strftime("%y%m%d_%H%M")

    return "{0}_{1}_{2}_{3}.{4}".format(
        doctype_part,
        docname_part,
        user_part,
        date_part,
        extension,
    )


def _build_scan_filename(original_filename, custom_file_name=None, session_data=None):
    """Build the final scan file name.

    Default format:
    Doctype_Docname_User_YYMMDD_HHMM.ext

    If custom_file_name is provided by an authorized manager, it is used as
    the base name while preserving the detected/original extension.
    """
    original_filename = _safe_filename(original_filename)

    if not custom_file_name:
        return _build_default_scan_filename(original_filename, session_data=session_data)

    custom_file_name = _normalize_custom_scan_filename(custom_file_name)
    if not custom_file_name:
        return _build_default_scan_filename(original_filename, session_data=session_data)

    original_ext = _get_extension(original_filename)
    custom_base = custom_file_name.rsplit(".", 1)[0] if "." in custom_file_name else custom_file_name

    if original_ext:
        return "{0}.{1}".format(custom_base, original_ext)

    return custom_base

def _detect_file_type_from_magic_bytes(content):
    """يكتشف نوع الملف الحقيقي من magic bytes."""
    if not content:
        return None, None

    for extension, signatures in MAGIC_BYTES.items():
        for signature in signatures:
            if content.startswith(signature):
                return extension, MIME_TYPES.get(extension)

    return None, None


def _validate_uploaded_file(filename, content, allowed_file_types):
    """يتحقق من امتداد ومحتوى الملف ويمنع Office/TXT والملفات الخطرة."""
    extension = _get_extension(filename)

    if not extension:
        frappe.throw(_("Uploaded file must have an extension"))

    if extension in DANGEROUS_EXTENSIONS:
        frappe.throw(_("File type .{0} is not allowed").format(extension))

    if extension in BLOCKED_DOCUMENT_EXTENSIONS:
        frappe.throw(_("Office and text files are not allowed: .{0}").format(extension))

    if extension not in SAFE_SCAN_EXTENSIONS:
        frappe.throw(_("Only scanned document/image files are allowed"))

    allowed_file_types = allowed_file_types or sorted(SAFE_SCAN_EXTENSIONS)
    allowed_file_types = [
        item.lower().strip().lstrip(".")
        for item in allowed_file_types
        if item
        and item.lower().strip().lstrip(".") in SAFE_SCAN_EXTENSIONS
        and item.lower().strip().lstrip(".") not in DANGEROUS_EXTENSIONS
        and item.lower().strip().lstrip(".") not in BLOCKED_DOCUMENT_EXTENSIONS
    ]

    if not allowed_file_types:
        allowed_file_types = sorted(SAFE_SCAN_EXTENSIONS)

    if extension not in allowed_file_types:
        frappe.throw(
            _("File type .{0} is not allowed. Allowed types: {1}").format(
                extension,
                ", ".join(allowed_file_types),
            )
        )

    detected_extension, detected_mime_type = _detect_file_type_from_magic_bytes(content)

    if not detected_extension:
        frappe.throw(_("Could not detect uploaded file type from content"))

    normalized_extension = extension
    normalized_detected_extension = detected_extension

    if normalized_extension == "jpeg":
        normalized_extension = "jpg"
    if normalized_detected_extension == "jpeg":
        normalized_detected_extension = "jpg"

    if normalized_extension != normalized_detected_extension:
        frappe.throw(
            _("File extension .{0} does not match actual file content .{1}").format(
                extension,
                detected_extension,
            )
        )

    if detected_extension not in allowed_file_types and normalized_detected_extension not in allowed_file_types:
        frappe.throw(_("Detected file type .{0} is not allowed").format(detected_extension))

    return {
        "extension": extension,
        "detected_extension": detected_extension,
        "mime_type": detected_mime_type,
    }


def _response(status_code, success, message, extra=None):
    """يبني استجابة موحدة للـ API."""
    frappe.local.response.http_status_code = status_code

    data = {"success": success, "message": message}
    if extra:
        data.update(extra)

    return data


def _create_agent_log(
    session_data,
    file_doc=None,
    status="Success",
    message=None,
    file_size_bytes=None,
):
    """ينشئ سجل Scan Log بعد الرفع."""
    try:
        frappe.call(
            "surhan_scanner.api.create_scan_log",
            scanned_doctype=session_data.get("doctype"),
            scanned_docname=session_data.get("docname"),
            file_url=file_doc.file_url if file_doc else "",
            file_name=file_doc.file_name if file_doc else "",
            rule=session_data.get("rule"),
            status=status,
            message=message or "",
            scanner_engine="Surhan Agent",
            agent_machine_name=session_data.get("agent_machine_name"),
            agent_version=session_data.get("agent_version"),
            agent_scanner_name=session_data.get("agent_scanner_name") or session_data.get("scanner_name"),
            scan_session_id=session_data.get("scan_session_id"),
            file_size_bytes=file_size_bytes,
            barcode_value=session_data.get("barcode_value"),
            barcode_field=session_data.get("barcode_field"),
            barcode_source=session_data.get("barcode_source"),
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Surhan Scanner Agent Log Failed")


def _upsert_agent_device(
    agent_id=None,
    machine_name=None,
    windows_user=None,
    agent_version=None,
    config_version=None,
    scanner_name=None,
    scanner_driver=None,
    os_version=None,
    agent_port=None,
    health_url=None,
    status="Online",
    last_error=None,
    last_user=None,
    last_upload_status=None,
    increment_heartbeat=True,
    increment_scan=False,
):
    """ينشئ أو يحدث سجل جهاز Agent."""
    if not _agent_device_doctype_exists():
        return None

    ip_address = _get_request_ip()

    resolved_agent_id = _make_agent_id(
        agent_id=agent_id,
        machine_name=machine_name,
        windows_user=windows_user,
        ip_address=ip_address,
    )

    now_value = now_datetime()

    if frappe.db.exists(AGENT_DEVICE_DOCTYPE, resolved_agent_id):
        doc = frappe.get_doc(AGENT_DEVICE_DOCTYPE, resolved_agent_id)
    else:
        doc = frappe.new_doc(AGENT_DEVICE_DOCTYPE)
        _set_doc_value_if_field(doc, "agent_id", resolved_agent_id)
        _set_doc_value_if_field(doc, "first_seen", now_value)
        _set_doc_value_if_field(doc, "enabled", 1)
        _set_doc_value_if_field(doc, "allow_upload", 1)

    _set_doc_value_if_field(doc, "machine_name", _safe_agent_text(machine_name))
    _set_doc_value_if_field(doc, "windows_user", _safe_agent_text(windows_user))
    _set_doc_value_if_field(doc, "ip_address", _safe_agent_text(ip_address))
    _set_doc_value_if_field(doc, "site", _safe_agent_text(frappe.local.site))
    _set_doc_value_if_field(doc, "status", status or "Online")
    _set_doc_value_if_field(doc, "last_seen", now_value)

    if agent_version:
        _set_doc_value_if_field(doc, "agent_version", _safe_agent_text(agent_version, 50))
    if config_version:
        _set_doc_value_if_field(doc, "config_version", _safe_agent_text(config_version, 50))
    if scanner_name:
        _set_doc_value_if_field(doc, "scanner_name", _safe_agent_text(scanner_name))
    if scanner_driver:
        _set_doc_value_if_field(doc, "scanner_driver", _safe_agent_text(scanner_driver))
    if os_version:
        _set_doc_value_if_field(doc, "os_version", _safe_agent_text(os_version))
    if agent_port:
        _set_doc_value_if_field(doc, "agent_port", cint(agent_port))
    if health_url:
        _set_doc_value_if_field(doc, "health_url", _safe_agent_text(health_url, 200))
    if last_error:
        _set_doc_value_if_field(doc, "last_error", _safe_agent_text(last_error, 500))
    if last_user:
        _set_doc_value_if_field(doc, "last_user", _safe_agent_text(last_user, 140))
    if last_upload_status:
        _set_doc_value_if_field(doc, "last_upload_status", last_upload_status)

    if increment_heartbeat and _doc_has_field(doc, "total_heartbeats"):
        doc.total_heartbeats = cint(doc.get("total_heartbeats") or 0) + 1

    if increment_scan:
        if _doc_has_field(doc, "total_scans"):
            doc.total_scans = cint(doc.get("total_scans") or 0) + 1
        _set_doc_value_if_field(doc, "last_scan_at", now_value)

    doc.save(ignore_permissions=True)
    return doc


def _normalize_agent_binding_value(value, max_length=140):
    """Normalize Agent identity values used for scan-token binding."""
    return _safe_agent_text(value, max_length).strip()


def _make_scan_session_agent_binding(agent_id=None, machine_name=None, windows_user=None):
    """Build normalized Agent identity values for binding a scan_token to one Agent."""
    binding = {}

    if agent_id:
        binding["agent_id"] = _normalize_agent_binding_value(
            _make_agent_id(agent_id=agent_id),
            140,
        )

    if machine_name:
        binding["agent_machine_name"] = _normalize_agent_binding_value(
            machine_name,
            140,
        )

    if windows_user:
        binding["agent_windows_user"] = _normalize_agent_binding_value(
            windows_user,
            140,
        )

    return {key: value for key, value in binding.items() if value}


def _validate_scan_session_agent_binding(
    scan_token,
    session_data,
    agent_id=None,
    machine_name=None,
    windows_user=None,
):
    """
    Bind a scan_token to the first Agent identity that uses it.

    This prevents the same scan_token from being reused by a different Agent
    identity for heartbeat, update manifest checks, or update status reports.
    """
    if not scan_token or not session_data:
        return True, ""

    incoming = _make_scan_session_agent_binding(
        agent_id=agent_id,
        machine_name=machine_name,
        windows_user=windows_user,
    )

    if not incoming:
        return True, ""

    remaining_seconds = _get_scan_token_remaining_seconds(session_data)
    if remaining_seconds <= 0:
        return False, "Invalid or expired scan token"

    for key, incoming_value in incoming.items():
        existing_value = _normalize_agent_binding_value(session_data.get(key), 140)

        if (
            existing_value
            and incoming_value
            and existing_value.casefold() != incoming_value.casefold()
        ):
            _cache_delete(scan_token)
            return False, "Scan token is already bound to a different Agent device"

    changed = False
    for key, incoming_value in incoming.items():
        if incoming_value and not session_data.get(key):
            session_data[key] = incoming_value
            changed = True

    if changed:
        _cache_set(scan_token, session_data, remaining_seconds)

    return True, ""


def _update_scan_session_agent_info(scan_token, session_data, agent_info):
    """يحدث بيانات جلسة المسح بمعلومات Agent."""
    if not scan_token or not session_data:
        return

    remaining_seconds = _get_scan_token_remaining_seconds(session_data)
    if remaining_seconds <= 0:
        return

    allowed_keys = {
        "agent_id",
        "agent_machine_name",
        "agent_windows_user",
        "agent_version",
        "agent_config_version",
        "agent_scanner_name",
        "agent_scanner_driver",
        "agent_os_version",
        "agent_health_url",
    }

    for key, value in agent_info.items():
        if key in allowed_keys:
            session_data[key] = value

    _cache_set(scan_token, session_data, remaining_seconds)


def _mark_stale_agents_offline_internal(offline_after_seconds=AGENT_OFFLINE_AFTER_SECONDS):
    """يحول الأجهزة القديمة إلى Offline إذا لم ترسل heartbeat."""
    if not _agent_device_doctype_exists():
        return 0

    cutoff = add_to_date(now_datetime(), seconds=-1 * cint(offline_after_seconds))

    agents = frappe.get_all(
        AGENT_DEVICE_DOCTYPE,
        filters={"status": ["!=", "Offline"], "last_seen": ["<", cutoff]},
        fields=["name"],
        limit_page_length=500,
    )

    count = 0
    for row in agents:
        doc = frappe.get_doc(AGENT_DEVICE_DOCTYPE, row.name)
        _set_doc_value_if_field(doc, "status", "Offline")
        doc.save(ignore_permissions=True)
        count += 1

    if count:
        frappe.db.commit()

    return count


def _get_agent_public_dir():
    """يرجع مسار public/agent داخل التطبيق."""
    return frappe.get_app_path("surhan_scanner", "public", "agent")


def _get_agent_manifest_path():
    """يرجع مسار ملف update_manifest.json."""
    return os.path.join(_get_agent_public_dir(), AGENT_MANIFEST_FILENAME)


def _read_agent_update_manifest():
    """يقرأ Manifest الخاص بتحديث Agent من public/agent."""
    manifest_path = _get_agent_manifest_path()

    if not os.path.exists(manifest_path):
        frappe.throw(_("Agent update manifest is missing"))

    with open(manifest_path, "r", encoding="utf-8") as file:
        manifest = json.load(file)

    for fieldname in ["latest_version", "package_url", "package_sha256", "package_size_bytes"]:
        if not manifest.get(fieldname):
            frappe.throw(_("Agent update manifest is invalid. Missing field: {0}").format(fieldname))

    return manifest


def _version_tuple(version):
    """يحوّل رقم الإصدار إلى tuple للمقارنة."""
    version = str(version or "0.0.0").strip()
    parts = []

    for item in version.split("."):
        try:
            parts.append(int(item))
        except Exception:
            parts.append(0)

    while len(parts) < 3:
        parts.append(0)

    return tuple(parts[:3])


def _is_newer_version(latest_version, current_version):
    """يتحقق هل الإصدار المتوفر أحدث من الإصدار الحالي."""
    return _version_tuple(latest_version) > _version_tuple(current_version)


def _update_agent_device_update_check(
    agent_id=None,
    current_version=None,
    manifest=None,
    update_available=False,
    status=None,
    error=None,
):
    """يحدث بيانات فحص التحديث داخل سجل Agent Device."""
    if not agent_id:
        return
    if not _agent_device_doctype_exists():
        return

    resolved_agent_id = _make_agent_id(agent_id=agent_id)
    if not frappe.db.exists(AGENT_DEVICE_DOCTYPE, resolved_agent_id):
        return

    doc = frappe.get_doc(AGENT_DEVICE_DOCTYPE, resolved_agent_id)

    _set_doc_value_if_field(doc, "last_update_check", now_datetime())
    _set_doc_value_if_field(doc, "update_available", 1 if update_available else 0)

    if current_version:
        _set_doc_value_if_field(doc, "agent_version", _safe_agent_text(current_version, 50))

    if manifest:
        _set_doc_value_if_field(doc, "available_version", _safe_agent_text(manifest.get("latest_version"), 50))
        _set_doc_value_if_field(doc, "update_package_url", _safe_agent_text(manifest.get("package_url"), 200))
        _set_doc_value_if_field(doc, "update_package_sha256", _safe_agent_text(manifest.get("package_sha256"), 140))

    if status:
        _set_doc_value_if_field(doc, "last_update_status", status)
    if error:
        _set_doc_value_if_field(doc, "last_update_error", _safe_agent_text(error, 500))

    doc.save(ignore_permissions=True)


def _update_agent_device_update_status(
    agent_id=None,
    installed_version=None,
    status=None,
    error=None,
):
    """يحدث نتيجة التحديث: Downloaded / Installed / Failed."""
    if not agent_id:
        return
    if not _agent_device_doctype_exists():
        return

    resolved_agent_id = _make_agent_id(agent_id=agent_id)
    if not frappe.db.exists(AGENT_DEVICE_DOCTYPE, resolved_agent_id):
        return

    doc = frappe.get_doc(AGENT_DEVICE_DOCTYPE, resolved_agent_id)

    if installed_version:
        _set_doc_value_if_field(doc, "agent_version", _safe_agent_text(installed_version, 50))
    if status:
        _set_doc_value_if_field(doc, "last_update_status", status)

    _set_doc_value_if_field(doc, "last_update_at", now_datetime())

    if error:
        _set_doc_value_if_field(doc, "last_update_error", _safe_agent_text(error, 500))
        _set_doc_value_if_field(doc, "status", "Warning")

    if status == "Installed":
        _set_doc_value_if_field(doc, "update_available", 0)
        _set_doc_value_if_field(doc, "status", "Online")

    doc.save(ignore_permissions=True)


def _get_password_value(doc, fieldname):
    """يجلب قيمة Password field بطريقة آمنة."""
    try:
        return doc.get_password(fieldname)
    except Exception:
        return doc.get(fieldname)


def _get_storage_backend(settings=None):
    """يرجع نوع التخزين المستخدم: Local أو S3/MinIO."""
    settings = settings or _get_settings()
    backend = _get_value(settings, "scanner_storage_backend", "Local")
    if backend not in ["Local", "S3/MinIO"]:
        return "Local"
    return backend


def _is_s3_storage_enabled(settings=None):
    """يتحقق هل التخزين الخارجي S3/MinIO مفعل."""
    return _get_storage_backend(settings) == "S3/MinIO"


def _get_s3_config(settings=None):
    """يجمع إعدادات S3/MinIO من Surhan Scanner Settings."""
    settings = settings or _get_settings()

    config = {
        "endpoint_url": _get_value(settings, "s3_endpoint_url", ""),
        "region_name": _get_value(settings, "s3_region_name", "us-east-1"),
        "bucket": _get_value(settings, "s3_bucket", ""),
        "access_key_id": _get_value(settings, "s3_access_key_id", ""),
        "secret_access_key": _get_password_value(settings, "s3_secret_access_key"),
        "key_prefix": _get_value(settings, "s3_key_prefix", "surhan-scanner"),
        "force_path_style": cint(_get_value(settings, "s3_force_path_style", 1)),
        "presigned_expiry_seconds": cint(_get_value(settings, "s3_presigned_expiry_seconds", 300)),
    }

    if config["presigned_expiry_seconds"] <= 0:
        config["presigned_expiry_seconds"] = 300
    if config["presigned_expiry_seconds"] > 3600:
        config["presigned_expiry_seconds"] = 3600

    return config


def _validate_s3_config(config):
    """يتحقق أن إعدادات S3/MinIO الأساسية مكتملة."""
    required = ["bucket", "access_key_id", "secret_access_key"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        frappe.throw(_("S3/MinIO configuration is incomplete. Missing: {0}").format(", ".join(missing)))


def _get_s3_client(config):
    """ينشئ S3 client باستخدام boto3."""
    try:
        import boto3
        from botocore.config import Config
    except Exception:
        frappe.throw(_("boto3 is required for S3/MinIO storage"))

    addressing_style = "path" if cint(config.get("force_path_style")) else "auto"
    boto_config = Config(signature_version="s3v4", s3={"addressing_style": addressing_style})

    kwargs = {
        "aws_access_key_id": config.get("access_key_id"),
        "aws_secret_access_key": config.get("secret_access_key"),
        "region_name": config.get("region_name") or "us-east-1",
        "config": boto_config,
    }

    if config.get("endpoint_url"):
        kwargs["endpoint_url"] = config.get("endpoint_url")

    return boto3.client("s3", **kwargs)


def _safe_s3_key_part(value, default="item"):
    """ينظف جزء من S3 key حتى لا يحتوي رموز مزعجة."""
    value = str(value or default).strip()
    value = value.replace("\\", "_").replace("/", "_").replace("\x00", "_")
    value = value.replace(" ", "_")

    allowed = []
    for ch in value:
        if ch.isalnum() or ch in ["-", "_", ".", "@"]:
            allowed.append(ch)
        else:
            allowed.append("_")

    cleaned = "".join(allowed).strip("._")
    return cleaned or default


def _make_s3_object_key(config, doctype, docname, filename):
    """ينشئ S3 object key منظم حسب الموقع والمستند والتاريخ."""
    prefix = _safe_s3_key_part(config.get("key_prefix"), "surhan-scanner")
    site = _safe_s3_key_part(frappe.local.site, "site")
    safe_doctype = _safe_s3_key_part(doctype, "doctype")
    safe_docname = _safe_s3_key_part(docname, "doc")
    safe_filename = _safe_s3_key_part(filename, "scan_file")

    date_part = now_datetime().strftime("%Y/%m/%d")
    unique_part = uuid.uuid4().hex

    return "{0}/{1}/{2}/{3}/{4}/{5}-{6}".format(
        prefix, site, safe_doctype, safe_docname, date_part, unique_part, safe_filename
    )


def _sha256_file(temp_path):
    """يحسِب SHA256 لملف موجود على القرص."""
    sha256 = hashlib.sha256()
    with open(temp_path, "rb") as file:
        for chunk in iter(lambda: file.read(CHUNK_SIZE), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def _guess_content_type(extension, mime_type=None):
    """يرجع Content-Type المناسب للملف."""
    if mime_type:
        return mime_type
    return MIME_TYPES.get(extension) or "application/octet-stream"


def _set_file_doc_field_if_exists(file_doc, fieldname, value):
    """يضبط قيمة داخل File فقط إذا كان الحقل موجودًا."""
    try:
        if file_doc.meta.get_field(fieldname):
            file_doc.set(fieldname, value)
    except Exception:
        pass


def _create_s3_file_doc(
    file_name,
    doctype,
    docname,
    attach_field,
    folder,
    is_private,
    bucket,
    s3_key,
    file_size,
    file_sha256,
):
    """ينشئ سجل File داخل Frappe لملف محفوظ في S3/MinIO."""
    file_doc = frappe.new_doc("File")
    file_doc.file_name = file_name
    file_doc.attached_to_doctype = doctype
    file_doc.attached_to_name = docname

    if attach_field:
        file_doc.attached_to_field = attach_field

    if folder:
        file_doc.folder = folder

    file_doc.is_private = cint(is_private)
    file_doc.file_size = cint(file_size)
    file_doc.file_url = "s3://{0}/{1}".format(bucket, s3_key)

    _set_file_doc_field_if_exists(file_doc, "surhan_storage_backend", "S3/MinIO")
    _set_file_doc_field_if_exists(file_doc, "surhan_s3_bucket", bucket)
    _set_file_doc_field_if_exists(file_doc, "surhan_s3_key", s3_key)
    _set_file_doc_field_if_exists(file_doc, "surhan_s3_sha256", file_sha256)
    _set_file_doc_field_if_exists(file_doc, "surhan_s3_size_bytes", cint(file_size))

    file_doc.insert(ignore_permissions=True)

    secure_file_url = "/api/method/surhan_scanner.agent_api.download_s3_scan_file?file_name={0}".format(file_doc.name)
    file_doc.db_set("file_url", secure_file_url, update_modified=False)

    return file_doc


def _save_scan_file_to_s3(
    temp_path,
    file_name,
    doctype,
    docname,
    attach_field,
    folder,
    is_private,
    extension,
    mime_type,
    file_size,
):
    """يرفع الملف إلى S3/MinIO ثم ينشئ سجل File داخل Frappe."""
    settings = _get_settings()
    config = _get_s3_config(settings)
    _validate_s3_config(config)

    bucket = config.get("bucket")
    s3_key = _make_s3_object_key(config, doctype, docname, file_name)
    file_sha256 = _sha256_file(temp_path)
    content_type = _guess_content_type(extension, mime_type)

    client = _get_s3_client(config)
    extra_args = {
        "ContentType": content_type,
        "Metadata": {
            "doctype": str(doctype or ""),
            "docname": str(docname or ""),
            "filename": str(file_name or ""),
            "sha256": file_sha256,
            "site": str(frappe.local.site or ""),
        },
    }

    client.upload_file(
        Filename=temp_path,
        Bucket=bucket,
        Key=s3_key,
        ExtraArgs=extra_args,
    )

    return _create_s3_file_doc(
        file_name=file_name,
        doctype=doctype,
        docname=docname,
        attach_field=attach_field if attach_field else None,
        folder=folder,
        is_private=is_private,
        bucket=bucket,
        s3_key=s3_key,
        file_size=file_size,
        file_sha256=file_sha256,
    )


def _get_s3_info_from_file(file_doc):
    """يستخرج bucket و key من حقول File الخاصة بـ S3."""
    bucket = file_doc.get("surhan_s3_bucket")
    s3_key = file_doc.get("surhan_s3_key")

    if not bucket or not s3_key:
        frappe.throw(_("This file is not stored in S3/MinIO"))

    return bucket, s3_key


def _check_file_read_permission(file_doc):
    """يتحقق من صلاحية قراءة الملف حسب المستند المرتبط."""
    if frappe.session.user == "Guest":
        frappe.throw(_("Login required"))

    attached_doctype = file_doc.get("attached_to_doctype")
    attached_name = file_doc.get("attached_to_name")

    if attached_doctype and attached_name and frappe.db.exists(attached_doctype, attached_name):
        target_doc = frappe.get_doc(attached_doctype, attached_name)
        if not frappe.has_permission(attached_doctype, "read", doc=target_doc):
            frappe.throw(_("You do not have permission to read this file"))
        return

    try:
        file_doc.check_permission("read")
    except Exception:
        frappe.throw(_("You do not have permission to read this file"))


@frappe.whitelist()
def download_s3_scan_file(file_name=None):
    _require_scanner_user_api()
    """يرجع Redirect إلى Presigned URL لتحميل ملف محفوظ في S3/MinIO."""
    if not file_name:
        frappe.throw(_("file_name is required"))

    if not frappe.db.exists("File", file_name):
        frappe.throw(_("File not found"))

    file_doc = frappe.get_doc("File", file_name)
    _check_file_read_permission(file_doc)

    bucket, s3_key = _get_s3_info_from_file(file_doc)
    settings = _get_settings()
    config = _get_s3_config(settings)
    _validate_s3_config(config)

    client = _get_s3_client(config)
    presigned_url = client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": bucket, "Key": s3_key},
        ExpiresIn=cint(config.get("presigned_expiry_seconds") or 300),
    )

    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = presigned_url


@frappe.whitelist(allow_guest=True)
def get_agent_update_manifest(
    current_version=None,
    agent_id=None,
    scan_token=None,
    machine_name=None,
    windows_user=None,
):
    """يرجع Manifest التحديث للـ Agent."""
    rate_limit = _check_agent_update_rate_limit("agent_update_check")
    if not rate_limit.get("allowed"):
        return _rate_limit_response(rate_limit)

    scan_token = scan_token or frappe.form_dict.get("scan_token")
    authenticated_for_device_update = False

    if scan_token:
        session_data = _cache_get(scan_token)
        if not session_data:
            return _response(403, False, "Invalid or expired scan token")

        session_user = session_data.get("user")
        if not session_user or session_user == "Guest":
            return _response(403, False, "Invalid scan session user")

        if not frappe.db.exists("User", session_user):
            return _response(403, False, "Scan session user does not exist")

        if not _user_has_scanner_role(session_user):
            return _response(403, False, "Scan session user does not have a Surhan Scanner role")

        frappe.set_user(session_user)

        bind_ok, bind_message = _validate_scan_session_agent_binding(
            scan_token=scan_token,
            session_data=session_data,
            agent_id=agent_id,
            machine_name=machine_name,
            windows_user=windows_user,
        )
        if not bind_ok:
            return _response(403, False, bind_message)

        authenticated_for_device_update = True

    elif frappe.session.user and frappe.session.user != "Guest":
        _enforce_scanner_role(frappe.session.user)
        authenticated_for_device_update = True

    else:
        return _response(403, False, "scan_token is required for guest update check")

    manifest = _read_agent_update_manifest()
    latest_version = manifest.get("latest_version")
    current_version = _safe_agent_text(current_version or "0.0.0", 50)

    update_available = _is_newer_version(latest_version=latest_version, current_version=current_version)
    status = "Available" if update_available else "No Update"

    if agent_id and _agent_device_doctype_exists() and authenticated_for_device_update:
        try:
            resolved_agent_id = _make_agent_id(agent_id=agent_id)

            if frappe.db.exists(AGENT_DEVICE_DOCTYPE, resolved_agent_id):
                frappe.db.set_value(
                    AGENT_DEVICE_DOCTYPE,
                    resolved_agent_id,
                    {
                        "last_update_check": now_datetime(),
                        "update_available": 1 if update_available else 0,
                        "available_version": _safe_agent_text(manifest.get("latest_version"), 50),
                        "last_update_status": status,
                        "update_package_url": _safe_agent_text(manifest.get("package_url"), 200),
                        "update_package_sha256": _safe_agent_text(manifest.get("package_sha256"), 140),
                        "agent_version": current_version,
                    },
                    update_modified=True,
                )
            else:
                _upsert_agent_device(
                    agent_id=agent_id,
                    machine_name=machine_name,
                    windows_user=windows_user,
                    agent_version=current_version,
                    status="Online",
                    increment_heartbeat=False,
                    increment_scan=False,
                )
                frappe.db.set_value(
                    AGENT_DEVICE_DOCTYPE,
                    resolved_agent_id,
                    {
                        "last_update_check": now_datetime(),
                        "update_available": 1 if update_available else 0,
                        "available_version": _safe_agent_text(manifest.get("latest_version"), 50),
                        "last_update_status": status,
                        "update_package_url": _safe_agent_text(manifest.get("package_url"), 200),
                        "update_package_sha256": _safe_agent_text(manifest.get("package_sha256"), 140),
                    },
                    update_modified=True,
                )

            frappe.db.commit()

        except Exception:
            frappe.log_error(frappe.get_traceback(), "Surhan Scanner Auto Update Check Log Failed")

    response_manifest = dict(manifest)
    response_manifest.update(
        {
            "success": True,
            "current_version": current_version,
            "update_available": update_available,
            "status": status,
            "security": {
                "must_verify_sha256": True,
                "hash_algorithm": manifest.get("hash_algorithm", "sha256"),
                "expected_sha256": manifest.get("package_sha256"),
                "code_signing_required": manifest.get("code_signing", {}).get("required", False),
            },
        }
    )

    return response_manifest


@frappe.whitelist(allow_guest=True)
def report_agent_update_status(
    agent_id=None,
    installed_version=None,
    status=None,
    error=None,
    scan_token=None,
):
    """يستقبل نتيجة محاولة التحديث من Agent."""
    rate_limit = _check_agent_update_rate_limit("agent_update_status")
    if not rate_limit.get("allowed"):
        return _rate_limit_response(rate_limit)

    allowed_statuses = {"Downloaded", "Installed", "Failed"}
    if status not in allowed_statuses:
        return _response(400, False, "Invalid update status")

    scan_token = scan_token or frappe.form_dict.get("scan_token")

    if scan_token:
        session_data = _cache_get(scan_token)
        if not session_data:
            return _response(403, False, "Invalid or expired scan token")

        session_user = session_data.get("user")
        if not session_user or session_user == "Guest":
            return _response(403, False, "Invalid scan session user")

        if not _user_has_scanner_role(session_user):
            return _response(403, False, "Scan session user does not have a Surhan Scanner role")

        frappe.set_user(session_user)

        bind_ok, bind_message = _validate_scan_session_agent_binding(
            scan_token=scan_token,
            session_data=session_data,
            agent_id=agent_id,
        )
        if not bind_ok:
            return _response(403, False, bind_message)

    else:
        if frappe.session.user == "Guest":
            return _response(403, False, "scan_token is required for guest update status")
        _enforce_scanner_role(frappe.session.user)

    if not agent_id:
        return _response(400, False, "agent_id is required")

    try:
        _update_agent_device_update_status(
            agent_id=agent_id,
            installed_version=installed_version,
            status=status,
            error=error,
        )
        frappe.db.commit()
    except Exception:
        frappe.log_error(frappe.get_traceback(), "Surhan Scanner Auto Update Status Failed")
        return _response(500, False, "Could not save update status")

    return {
        "success": True,
        "message": "Agent update status received",
        "agent_id": agent_id,
        "installed_version": installed_version,
        "status": status,
    }


@frappe.whitelist(allow_guest=True)
def agent_heartbeat(
    scan_token=None,
    agent_id=None,
    machine_name=None,
    windows_user=None,
    agent_version=None,
    config_version=None,
    scanner_name=None,
    scanner_driver=None,
    os_version=None,
    agent_port=None,
    health_url=None,
    status="Online",
    last_error=None,
):
    """يستقبل heartbeat من Agent ويحدث سجل الجهاز."""
    ip_rate_limit = _check_agent_heartbeat_rate_limit()
    if not ip_rate_limit.get("allowed"):
        return _rate_limit_response(ip_rate_limit)

    scan_token = scan_token or frappe.form_dict.get("scan_token")
    session_data = None
    session_user = None

    if scan_token:
        session_data = _cache_get(scan_token)
        if not session_data:
            return _response(403, False, "Invalid or expired scan token")

        session_user = session_data.get("user")
        if not session_user or session_user == "Guest":
            return _response(403, False, "Invalid scan session user")

        if not frappe.db.exists("User", session_user):
            return _response(403, False, "Scan session user does not exist")

        if not _user_has_scanner_role(session_user):
            return _response(403, False, "Scan session user does not have a Surhan Scanner role")

        frappe.set_user(session_user)

        bind_ok, bind_message = _validate_scan_session_agent_binding(
            scan_token=scan_token,
            session_data=session_data,
            agent_id=agent_id,
            machine_name=machine_name,
            windows_user=windows_user,
        )
        if not bind_ok:
            return _response(403, False, bind_message)

    else:
        if frappe.session.user == "Guest":
            return _response(403, False, "scan_token is required for guest heartbeat")
        _enforce_scanner_role(frappe.session.user)
        session_user = frappe.session.user

    if not _agent_device_doctype_exists():
        return _response(500, False, "Agent monitoring DocType is not installed")

    doc = _upsert_agent_device(
        agent_id=agent_id,
        machine_name=machine_name,
        windows_user=windows_user,
        agent_version=agent_version,
        config_version=config_version,
        scanner_name=scanner_name,
        scanner_driver=scanner_driver,
        os_version=os_version,
        agent_port=agent_port,
        health_url=health_url,
        status=status or "Online",
        last_error=last_error,
        last_user=session_user,
        increment_heartbeat=True,
        increment_scan=False,
    )

    if not doc:
        return _response(500, False, "Could not update agent monitoring record")

    agent_info = {
        "agent_id": doc.get("agent_id"),
        "agent_machine_name": doc.get("machine_name"),
        "agent_windows_user": doc.get("windows_user"),
        "agent_version": doc.get("agent_version"),
        "agent_config_version": doc.get("config_version"),
        "agent_scanner_name": doc.get("scanner_name"),
        "agent_scanner_driver": doc.get("scanner_driver"),
        "agent_os_version": doc.get("os_version"),
        "agent_health_url": doc.get("health_url"),
    }

    if scan_token and session_data:
        _update_scan_session_agent_info(
            scan_token=scan_token,
            session_data=session_data,
            agent_info=agent_info,
        )

    frappe.db.commit()

    return {
        "success": True,
        "message": "Agent heartbeat received",
        "agent": {
            "name": doc.name,
            "agent_id": doc.get("agent_id"),
            "machine_name": doc.get("machine_name"),
            "windows_user": doc.get("windows_user"),
            "ip_address": doc.get("ip_address"),
            "status": doc.get("status"),
            "last_seen": str(doc.get("last_seen")),
            "agent_version": doc.get("agent_version"),
            "scanner_name": doc.get("scanner_name"),
            "total_heartbeats": doc.get("total_heartbeats"),
        },
    }


@frappe.whitelist()
def get_agent_monitoring_status(offline_after_seconds=AGENT_OFFLINE_AFTER_SECONDS):
    _require_scanner_manager_api()
    """يرجع قائمة Agents وحالتها الحالية للمديرين."""
    _enforce_scanner_manager_role(frappe.session.user)

    if not _agent_device_doctype_exists():
        frappe.throw(_("Agent monitoring DocType is not installed"))

    _mark_stale_agents_offline_internal(offline_after_seconds=cint(offline_after_seconds))

    agents = frappe.get_all(
        AGENT_DEVICE_DOCTYPE,
        fields=[
            "name",
            "agent_id",
            "machine_name",
            "windows_user",
            "ip_address",
            "site",
            "status",
            "enabled",
            "allow_upload",
            "first_seen",
            "last_seen",
            "last_scan_at",
            "agent_version",
            "config_version",
            "scanner_name",
            "scanner_driver",
            "os_version",
            "agent_port",
            "health_url",
            "last_upload_status",
            "total_heartbeats",
            "total_scans",
            "last_error",
            "last_user",
            "last_update_check",
            "update_available",
            "available_version",
            "last_update_status",
            "last_update_at",
            "update_package_url",
            "update_package_sha256",
            "last_update_error",
        ],
        order_by="last_seen desc",
        limit_page_length=500,
    )

    return {
        "success": True,
        "offline_after_seconds": cint(offline_after_seconds),
        "total_agents": len(agents),
        "agents": agents,
    }


@frappe.whitelist()
def mark_stale_agents_offline(offline_after_seconds=AGENT_OFFLINE_AFTER_SECONDS):
    _require_scanner_manager_api()
    """يحول الأجهزة القديمة إلى Offline يدويًا."""
    _enforce_scanner_manager_role(frappe.session.user)

    count = _mark_stale_agents_offline_internal(offline_after_seconds=cint(offline_after_seconds))

    return {
        "success": True,
        "message": "Stale agents marked offline",
        "updated": count,
    }
@frappe.whitelist()
def get_agent_dashboard_data(
    search=None,
    status=None,
    agent_version=None,
    update_available=None,
    allow_upload=None,
    limit_start=0,
    limit_page_length=20,
    offline_after_seconds=AGENT_OFFLINE_AFTER_SECONDS,
):
    _require_scanner_manager_api()
    """
    يرجع بيانات لوحة التحكم الخاصة بالأجهزة:
    - Summary
    - قائمة الأجهزة
    - Pagination
    - Filters
    """
    _enforce_scanner_manager_role(frappe.session.user)

    if not _agent_device_doctype_exists():
        frappe.throw(_("Agent monitoring DocType is not installed"))

    _mark_stale_agents_offline_internal(
        offline_after_seconds=cint(offline_after_seconds)
    )

    limit_start = max(cint(limit_start), 0)
    limit_page_length = min(max(cint(limit_page_length), 1), 100)

    base_filters = {}

    if status and status != "All":
        base_filters["status"] = status

    if agent_version:
        base_filters["agent_version"] = agent_version

    if update_available in [0, 1, "0", "1", False, True]:
        base_filters["update_available"] = cint(update_available)

    if allow_upload in [0, 1, "0", "1", False, True]:
        base_filters["allow_upload"] = cint(allow_upload)

    or_filters = []
    if search:
        search = _safe_agent_text(search, 140)
        or_filters = [
            ["agent_id", "like", f"%{search}%"],
            ["machine_name", "like", f"%{search}%"],
            ["windows_user", "like", f"%{search}%"],
            ["scanner_name", "like", f"%{search}%"],
            ["scanner_driver", "like", f"%{search}%"],
            ["os_version", "like", f"%{search}%"],
            ["ip_address", "like", f"%{search}%"],
            ["last_error", "like", f"%{search}%"],
        ]

    fields = [
        "name",
        "agent_id",
        "machine_name",
        "windows_user",
        "ip_address",
        "site",
        "status",
        "enabled",
        "allow_upload",
        "first_seen",
        "last_seen",
        "last_scan_at",
        "agent_version",
        "config_version",
        "scanner_name",
        "scanner_driver",
        "os_version",
        "agent_port",
        "health_url",
        "last_upload_status",
        "total_heartbeats",
        "total_scans",
        "last_error",
        "last_user",
        "last_update_check",
        "update_available",
        "available_version",
        "last_update_status",
        "last_update_at",
        "update_package_url",
        "update_package_sha256",
        "last_update_error",
    ]

    agents = frappe.get_all(
        AGENT_DEVICE_DOCTYPE,
        filters=base_filters,
        or_filters=or_filters,
        fields=fields,
        order_by="last_seen desc",
        limit_start=limit_start,
        limit_page_length=limit_page_length,
    )

    # count آمن مع or_filters
    all_rows = frappe.get_all(
        AGENT_DEVICE_DOCTYPE,
        filters=base_filters,
        or_filters=or_filters,
        fields=["name"],
        limit_page_length=100000,
    )
    total_count = len(all_rows)

    def _count_status(extra_filters=None):
        flt = dict(base_filters)
        if extra_filters:
            flt.update(extra_filters)

        rows = frappe.get_all(
            AGENT_DEVICE_DOCTYPE,
            filters=flt,
            or_filters=or_filters,
            fields=["name"],
            limit_page_length=100000,
        )
        return len(rows)

    summary = {
        "total": total_count,
        "online": _count_status({"status": "Online"}),
        "offline": _count_status({"status": "Offline"}),
        "warning": _count_status({"status": "Warning"}),
        "blocked": _count_status({"status": "Blocked"}),
        "update_available": _count_status({"update_available": 1}),
        "allow_upload": _count_status({"allow_upload": 1}),
    }

    return {
        "success": True,
        "summary": summary,
        "agents": agents,
        "pagination": {
            "limit_start": limit_start,
            "limit_page_length": limit_page_length,
            "total_count": total_count,
            "has_more": (limit_start + limit_page_length) < total_count,
        },
        "filters": {
            "search": search or "",
            "status": status or "All",
            "agent_version": agent_version or "",
            "update_available": update_available,
            "allow_upload": allow_upload,
        },
    }

@frappe.whitelist()
def set_agent_device_status(agent_id=None, status=None, last_error=None, allow_upload=None):
    _require_scanner_admin_api()
    """
    يغير حالة الجهاز يدويًا من لوحة التحكم.
    """
    _enforce_scanner_manager_role(frappe.session.user)

    if not agent_id:
        frappe.throw(_("agent_id is required"))

    if status not in ["Online", "Offline", "Warning", "Blocked"]:
        frappe.throw(_("Invalid status"))

    resolved_agent_id = _make_agent_id(agent_id=agent_id)

    if not frappe.db.exists(AGENT_DEVICE_DOCTYPE, resolved_agent_id):
        frappe.throw(_("Agent device not found"))

    doc = frappe.get_doc(AGENT_DEVICE_DOCTYPE, resolved_agent_id)

    _set_doc_value_if_field(doc, "status", status)
    _set_doc_value_if_field(doc, "last_seen", now_datetime())

    if last_error is not None:
        _set_doc_value_if_field(doc, "last_error", _safe_agent_text(last_error, 500))

    if allow_upload in [0, 1, "0", "1", False, True]:
        _set_doc_value_if_field(doc, "allow_upload", cint(allow_upload))

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "success": True,
        "message": "Agent status updated",
        "agent_id": resolved_agent_id,
        "status": status,
    }


@frappe.whitelist()
def get_agent_device_detail(agent_id=None):
    _require_scanner_manager_api()
    """
    يرجع تفاصيل جهاز واحد للوحة التحكم.
    """
    _enforce_scanner_manager_role(frappe.session.user)

    if not agent_id:
        frappe.throw(_("agent_id is required"))

    resolved_agent_id = _make_agent_id(agent_id=agent_id)

    if not frappe.db.exists(AGENT_DEVICE_DOCTYPE, resolved_agent_id):
        frappe.throw(_("Agent device not found"))

    return {
        "success": True,
        "agent": frappe.get_doc(AGENT_DEVICE_DOCTYPE, resolved_agent_id).as_dict()
    }

@frappe.whitelist()
def create_scan_session(
    doctype=None,
    docname=None,
    attach_field=None,
    upload_mode="Both",
    rule=None,
    is_private=None,
    folder=None,
    file_type=None,
    resolution=None,
    pixel_type=None,
    multi_page=None,
    use_feeder=None,
    duplex=None,
    scanner_name=None,
    profile=None,
    paper_source=None,
    silent_scan=None,
    show_preview=None,
    scan_batch_mode=None,
    max_pages=None,
    upload_strategy=None,
    custom_file_name=None,
    # Barcode data is captured by the local Agent and stored on the target document.
    barcode_field=None,
    barcode_value=None,
    barcode_source=None,
):
    _require_scanner_user_api()
    """ينشئ جلسة مسح جديدة بعد فحص الدور والصلاحية والـ Rule."""
    settings = _get_settings()

    if not settings.enabled:
        frappe.throw(_("Surhan Scanner is disabled"))

    _enforce_create_scan_session_rate_limit()
    _enforce_scanner_role(frappe.session.user)
    _validate_target_doc(doctype, docname, permission_type="write")

    rule_doc = _validate_scanner_rule(rule, doctype)

    resolved_upload_mode, resolved_attach_field = _resolve_rule_upload_target(
        rule_doc=rule_doc,
        doctype=doctype,
        requested_attach_field=attach_field,
    )

    token_expiry = _get_int_value(settings, "agent_token_expiry_seconds", 300)
    if token_expiry <= 0 or token_expiry > 900:
        token_expiry = 300

    scan_timeout = _get_int_value(settings, "agent_scan_timeout_seconds", 120)

    allowed_file_types = _get_value(
        settings,
        "agent_allowed_file_types",
        ",".join(sorted(SAFE_SCAN_EXTENSIONS)),
    )
    allowed_file_types = _split_allowed_file_types(allowed_file_types)
    allowed_file_types = [
        ext for ext in allowed_file_types
        if ext and ext in SAFE_SCAN_EXTENSIONS and ext not in DANGEROUS_EXTENSIONS and ext not in BLOCKED_DOCUMENT_EXTENSIONS
    ]
    if not allowed_file_types:
        allowed_file_types = sorted(SAFE_SCAN_EXTENSIONS)

    max_upload_size_mb = _get_int_value(
        settings,
        "max_upload_size_mb",
        _get_int_value(settings, "agent_max_file_size_mb", 25),
    )
    if max_upload_size_mb <= 0 or max_upload_size_mb > 100:
        max_upload_size_mb = 25

    scan_session_id = _make_scan_session_id()
    scan_token = _make_scan_token(scan_session_id)

    rule_file_type = _get_rule_value(
        rule_doc,
        "file_type",
        _get_value(settings, "default_file_type", "JPG"),
    )

    resolved_file_type = str(rule_file_type or "JPG").lower()
    if resolved_file_type not in allowed_file_types:
        resolved_file_type = allowed_file_types[0]

    resolved_resolution = cint(
        _get_rule_value(rule_doc, "resolution", None)
        or _get_int_value(settings, "default_resolution", 200)
    )

    resolved_pixel_type = (
        _get_rule_value(rule_doc, "pixel_type", None)
        or _get_value(settings, "default_pixel_type", "Color")
    )

    resolved_is_private = _get_check_value(
        rule_doc,
        "is_private",
        _get_check_value(settings, "is_private", 1),
    )

    resolved_folder = _get_value(
        rule_doc,
        "folder",
        _get_value(settings, "folder", "Home/Attachments"),
    )

    resolved_paper_source = _get_rule_value(rule_doc, "paper_source", None) or "Feeder"
    resolved_silent_scan = _get_check_value(
        rule_doc,
        "silent_scan",
        _get_check_value(settings, "enable_silent_scan", 1),
    )
    resolved_show_preview = _get_check_value(rule_doc, "show_preview", 1)

    resolved_custom_file_name = ""
    if custom_file_name:
        if not _user_can_customize_scan_filename(frappe.session.user):
            frappe.throw(_("Only users with manager role can customize file names"))

        resolved_custom_file_name = _normalize_custom_scan_filename(custom_file_name)
        if not resolved_custom_file_name:
            frappe.throw(_("Custom file name cannot be empty"))

    barcode_payload = _resolve_barcode_payload(
        rule_doc=rule_doc,
        doctype=doctype,
        barcode_field=barcode_field,
        barcode_value=barcode_value,
        barcode_source=barcode_source,
    )

    session_data = {
        "success": 1,
        "scan_session_id": scan_session_id,
        "scan_token": scan_token,
        "created_at": str(now_datetime()),
        "expires_at": str(add_to_date(now_datetime(), seconds=token_expiry)),
        "expires_in": token_expiry,
        "user": frappe.session.user,
        "site": frappe.local.site,
        "doctype": doctype,
        "docname": docname,
        "attach_field": resolved_attach_field or "",
        "upload_mode": resolved_upload_mode,
        "rule": rule_doc.name,
        "is_private": resolved_is_private,
        "folder": resolved_folder,
        "file_type": resolved_file_type,
        "resolution": resolved_resolution,
        "pixel_type": resolved_pixel_type,
        "multi_page": _get_check_value(rule_doc, "multi_page", 0),
        "use_feeder": _get_check_value(rule_doc, "use_feeder", 0),
        "duplex": _get_check_value(rule_doc, "duplex", 0),
        "scanner_name": scanner_name or "",
        "profile": rule_doc.get("agent_profile") or "",
        "custom_file_name": resolved_custom_file_name,
        # Barcode metadata is passed from the browser dialog / local Agent.
        # USB barcode readers work as keyboards: when the input is focused,
        # the scanned code is captured here and saved on the target document.
        "barcode_field": barcode_payload.get("barcode_field") or "",
        "barcode_value": barcode_payload.get("barcode_value") or "",
        "barcode_source": barcode_payload.get("barcode_source") or "",
        "paper_source": resolved_paper_source,
        "silent_scan": resolved_silent_scan,
        "show_preview": resolved_show_preview,
        "scan_batch_mode": rule_doc.get("scan_batch_mode") or "Single Page",
        "max_pages": cint(rule_doc.get("max_pages") or 1),
        "upload_strategy": (
            rule_doc.get("upload_strategy")
            or _get_value(settings, "upload_strategy", "Direct Upload")
            or "Direct Upload"
        ),
        "agent_url": _get_value(settings, "agent_url", "http://127.0.0.1:8787"),
        "agent_scan_timeout_seconds": scan_timeout,
        "allowed_file_types": allowed_file_types,
        "max_upload_size_mb": max_upload_size_mb,
        "enable_upload_retry": _get_check_value(settings, "enable_upload_retry", 1),
        "upload_retry_count": _get_int_value(settings, "upload_retry_count", 3),
        "upload_retry_delay_seconds": _get_int_value(settings, "upload_retry_delay_seconds", 5),
        "farabi_url": get_url(),
        "upload_url": get_url("/api/method/surhan_scanner.agent_api.upload_agent_scan"),
        "heartbeat_url": get_url("/api/method/surhan_scanner.agent_api.agent_heartbeat"),
        "update_manifest_url": get_url("/api/method/surhan_scanner.agent_api.get_agent_update_manifest"),
        "update_status_url": get_url("/api/method/surhan_scanner.agent_api.report_agent_update_status"),
    }

    _cache_set(scan_token, session_data, token_expiry)
    return session_data


def _safe_update_target_attach_field(doctype, docname, attach_field, file_url, max_retries=3):
    """يحدّث حقل الإرفاق مباشرة بدون doc.save لتقليل تعارض TimestampMismatchError."""
    if not doctype or not docname or not attach_field:
        return True

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            frappe.db.set_value(
                doctype,
                docname,
                attach_field,
                file_url,
                update_modified=False,
            )
            return True
        except Exception as exc:
            last_error = exc
            frappe.db.rollback()
            if attempt < max_retries:
                time.sleep(0.2 * attempt)
                continue
            break

    frappe.log_error(
        title="Surhan Scanner Attach Field Update Failed",
        message=(
            f"doctype={doctype}, docname={docname}, attach_field={attach_field}, "
            f"file_url={file_url}, error={last_error}"
        ),
    )
    return False


def _safe_update_target_fields(doctype, docname, updates, max_retries=3):
    """يحدّث أكثر من حقل في المستند الهدف دفعة واحدة لتقليل تعارضات التزامن."""
    if not doctype or not docname or not updates:
        return True

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            # نستخدم set_value المباشر بدل تحميل المستند ثم حفظه؛ هذا يقلل
            # احتمال TimestampMismatchError عند وجود عدة طلبات متزامنة.
            frappe.db.set_value(
                doctype,
                docname,
                updates,
                update_modified=False,
            )
            return True
        except Exception as exc:
            last_error = exc
            frappe.db.rollback()

            if attempt < max_retries:
                time.sleep(0.2 * attempt)
                continue

            break

    frappe.log_error(
        title="Surhan Scanner Target Fields Update Failed",
        message=(
            f"doctype={doctype}, docname={docname}, updates={updates}, error={last_error}"
        ),
    )
    return False



# SURHAN_PAGE_COUNT_PATCH_102
def _count_pdf_pages_from_file_url(file_url):
    """Return the real PDF page count for a Frappe File URL. Fallback to 1."""
    try:
        import os
        import re

        if not file_url:
            return 1

        clean_url = str(file_url).split("?", 1)[0]
        basename = os.path.basename(clean_url)

        candidates = []

        if clean_url.startswith("/private/files/"):
            candidates.append(frappe.get_site_path("private", "files", basename))
        elif clean_url.startswith("/files/"):
            candidates.append(frappe.get_site_path("public", "files", basename))

        try:
            file_doc = frappe.db.get_value(
                "File",
                {"file_url": file_url},
                ["file_name", "is_private"],
                as_dict=True,
            )

            if file_doc and file_doc.get("file_name"):
                if cint(file_doc.get("is_private")):
                    candidates.append(
                        frappe.get_site_path("private", "files", file_doc.get("file_name"))
                    )
                else:
                    candidates.append(
                        frappe.get_site_path("public", "files", file_doc.get("file_name"))
                    )
        except Exception:
            pass

        for candidate in candidates:
            if not candidate or not os.path.exists(candidate):
                continue

            if not str(candidate).lower().endswith(".pdf"):
                return 1

            with open(candidate, "rb") as f:
                data = f.read()

            pages = len(re.findall(rb"/Type\s*/Page\b", data))
            if pages > 0:
                return pages

        return 1

    except Exception as exc:
        try:
            frappe.log_error(
                title="Surhan Scanner PDF Page Count Failed",
                message=f"file_url={file_url}, error={exc}",
            )
        except Exception:
            pass
        return 1


def _set_child_table_scan_defaults(row, child_meta, file_url, file_name=None, page_count=None):
    """Fill common required/default fields in child attachment rows."""
    page_count = cint(page_count or 1)
    if page_count <= 0:
        page_count = 1

    for child_df in child_meta.fields:
        fieldname = child_df.fieldname
        if not fieldname or row.get(fieldname):
            continue

        if child_df.fieldtype in ["Attach", "Attach Image"]:
            continue

        if fieldname in ["attachment_count", "count", "qty", "quantity"]:
            row.set(fieldname, page_count)
            continue

        if fieldname in ["attachment_description", "description", "remarks"]:
            row.set(fieldname, file_name or file_url)
            continue

        if fieldname in ["attachment_no", "reference", "reference_no"]:
            row.set(fieldname, file_name or "")
            continue

        if not cint(getattr(child_df, "reqd", 0)):
            continue

        if child_df.fieldtype == "Select":
            options = [
                option.strip()
                for option in str(child_df.options or "").split("\n")
                if option.strip()
            ]
            if options:
                row.set(fieldname, options[0])

        elif child_df.fieldtype in ["Data", "Small Text", "Text"]:
            row.set(fieldname, "Scanned")

        elif child_df.fieldtype in ["Int", "Long Int"]:
            row.set(fieldname, 1)

        elif child_df.fieldtype in ["Float", "Currency", "Percent"]:
            row.set(fieldname, 1)

        elif child_df.fieldtype == "Check":
            row.set(fieldname, 0)

        elif child_df.fieldtype == "Date":
            row.set(fieldname, now_datetime().date())


def _make_attach_lock_key(doctype, docname, attach_field):
    """Build a short DB named-lock key for serializing attachment updates."""
    import hashlib as _hashlib

    site = getattr(frappe.local, "site", "") or ""
    raw = "{0}:{1}:{2}:{3}".format(
        site,
        doctype or "",
        docname or "",
        attach_field or "",
    )
    return "surhan_scan_attach_" + _hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _acquire_attach_lock(doctype, docname, attach_field, timeout_seconds=8):
    """
    Acquire a short database named lock while appending/updating attachment fields.

    This does not block creating scan sessions. It only serializes the critical
    save operation for the same doctype/docname/attach_field.
    """
    lock_key = _make_attach_lock_key(doctype, docname, attach_field)

    try:
        result = frappe.db.sql(
            "SELECT GET_LOCK(%s, %s)",
            (lock_key, cint(timeout_seconds or 8)),
            as_list=True,
        )
        acquired = bool(result and result[0] and cint(result[0][0]) == 1)
        return acquired, lock_key
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Surhan Scanner Attach Lock Acquire Failed",
        )
        # Fail-open to avoid breaking uploads if DB named locks are unavailable.
        return True, ""


def _release_attach_lock(lock_key):
    """Release a database named lock if it was acquired."""
    if not lock_key:
        return

    try:
        frappe.db.sql("SELECT RELEASE_LOCK(%s)", (lock_key,))
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Surhan Scanner Attach Lock Release Failed",
        )


def _safe_attach_file_to_target_field(doctype, docname, attach_field, file_url, file_name=None, max_retries=3):
    """Attach uploaded scan to a direct Attach field or append a child-table row."""
    if not doctype or not docname or not attach_field or not file_url:
        return True, ""

    lock_key = ""

    try:
        target = _resolve_attach_target(doctype, attach_field)

        lock_acquired, lock_key = _acquire_attach_lock(
            doctype=doctype,
            docname=docname,
            attach_field=attach_field,
            timeout_seconds=_get_attach_lock_timeout_seconds(),
        )

        if not lock_acquired:
            return False, "Another scan upload is currently being attached to this document. Please try again in a few seconds."

        try:
            if target.get("mode") == "direct":
                ok = _safe_update_target_attach_field(
                    doctype=doctype,
                    docname=docname,
                    attach_field=target.get("attach_field"),
                    file_url=file_url,
                    max_retries=max_retries,
                )
                return ok, "" if ok else "Could not update attach field"

            if target.get("mode") != "child_table":
                return False, "Unsupported attach target"

            table_field = target.get("table_field")
            child_doctype = target.get("child_doctype")
            child_attach_field = target.get("child_attach_field")
            child_meta = frappe.get_meta(child_doctype)

            last_error = None

            for attempt in range(1, max_retries + 1):
                try:
                    doc = frappe.get_doc(doctype, docname)
                    doc.check_permission("write")

                    row = doc.append(table_field, {})
                    row.set(child_attach_field, file_url)
                    page_count = _count_pdf_pages_from_file_url(file_url)

                    _set_child_table_scan_defaults(
                        row=row,
                        child_meta=child_meta,
                        file_url=file_url,
                        file_name=file_name,
                        page_count=page_count,
                    )

                    doc.save(ignore_permissions=False)
                    return True, ""

                except Exception as exc:
                    last_error = exc
                    frappe.db.rollback()

                    if attempt < max_retries:
                        time.sleep(0.2 * attempt)
                        continue

            frappe.log_error(
                title="Surhan Scanner Child Table Attach Failed",
                message=(
                    f"doctype={doctype}, docname={docname}, table_field={table_field}, "
                    f"child_attach_field={child_attach_field}, file_url={file_url}, error={last_error}"
                ),
            )
            return False, str(last_error)

        finally:
            _release_attach_lock(lock_key)

    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), "Surhan Scanner Attach Routing Failed")
        return False, str(exc)


@frappe.whitelist(allow_guest=True)
def upload_agent_scan(scan_token=None, filename=None, file_content=None):
    """واجهة رفع الملفات من Agent. التحقق الحقيقي يتم عبر scan_token داخل الدالة الداخلية."""
    return _upload_agent_scan(
        scan_token=scan_token,
        filename=filename,
        file_content=file_content,
    )

def _upload_agent_scan(scan_token=None, filename=None, file_content=None):
    """يستقبل الملف من Agent ويرفعه بعد فحص التوكن والدور والصلاحية ونوع الملف."""
    temp_path = None

    try:
        ip_rate_limit = _check_upload_ip_rate_limit()
        if not ip_rate_limit.get("allowed"):
            return _rate_limit_response(ip_rate_limit)

        scan_token = scan_token or frappe.form_dict.get("scan_token")
        if not scan_token:
            return _response(400, False, "scan_token is required")

        session_data = _cache_get(scan_token)
        if not session_data:
            return _response(403, False, "Invalid or expired scan token")

        session_user = session_data.get("user")
        if not session_user or session_user == "Guest":
            _cache_delete(scan_token)
            return _response(403, False, "Invalid scan session user")

        user_rate_limit = _check_upload_user_rate_limit(session_user)
        if not user_rate_limit.get("allowed"):
            return _rate_limit_response(user_rate_limit)

        if not frappe.db.exists("User", session_user):
            _cache_delete(scan_token)
            return _response(403, False, "Scan session user does not exist")

        if not _user_has_scanner_role(session_user):
            _cache_delete(scan_token)
            return _response(403, False, "Scan session user does not have a Surhan Scanner role")

        frappe.set_user(session_user)

        doctype = session_data.get("doctype")
        docname = session_data.get("docname")
        rule = session_data.get("rule")

        try:
            _validate_target_doc(doctype, docname, permission_type="write")

            rule_doc = _validate_scanner_rule(rule, doctype)

            current_upload_mode, current_attach_field = _resolve_rule_upload_target(
                rule_doc=rule_doc,
                doctype=doctype,
                requested_attach_field=session_data.get("attach_field"),
            )

            if current_upload_mode != session_data.get("upload_mode"):
                _cache_delete(scan_token)
                return _response(403, False, "Scanner rule upload mode changed. Please create a new scan session.")

            if (current_attach_field or "") != (session_data.get("attach_field") or ""):
                _cache_delete(scan_token)
                return _response(403, False, "Scanner rule attach field changed. Please create a new scan session.")
        except Exception as e:
            frappe.local.response.http_status_code = 403
            return {"success": False, "message": str(e)}

        max_upload_size_mb = cint(session_data.get("max_upload_size_mb") or 25)
        if max_upload_size_mb <= 0 or max_upload_size_mb > 100:
            max_upload_size_mb = 25

        max_bytes = max_upload_size_mb * 1024 * 1024

        uploaded_file = None
        try:
            uploaded_file = frappe.request.files.get("file")
        except Exception:
            uploaded_file = None

        if uploaded_file:
            file_name = _safe_filename(uploaded_file.filename)

            custom_file_name = session_data.get("custom_file_name")
            file_name = _build_scan_filename(
                file_name,
                custom_file_name,
                session_data=session_data,
            )

            try:
                temp_result = _read_uploaded_stream_to_temp(
                    uploaded_file=uploaded_file,
                    max_bytes=max_bytes,
                )
            except Exception as exc:
                return _response(400, False, str(exc))

            temp_path = temp_result.get("temp_path")
            file_size = temp_result.get("file_size")
            content_head = temp_result.get("head") or b""

        elif filename and file_content:
            file_name = _safe_filename(filename)

            custom_file_name = session_data.get("custom_file_name")
            file_name = _build_scan_filename(
                file_name,
                custom_file_name,
                session_data=session_data,
            )

            try:
                decoded_content = base64.b64decode(file_content, validate=True)
            except (binascii.Error, ValueError):
                return _response(400, False, "Invalid file content encoding")

            try:
                temp_result = _write_bytes_to_temp(
                    content=decoded_content,
                    max_bytes=max_bytes,
                )
            except Exception as exc:
                return _response(400, False, str(exc))

            temp_path = temp_result.get("temp_path")
            file_size = temp_result.get("file_size")
            content_head = temp_result.get("head") or b""

        else:
            return _response(400, False, "No file uploaded")

        if not file_name:
            return _response(400, False, "Invalid file name")

        if file_size <= 0:
            return _response(400, False, "Uploaded file is empty")

        allowed_file_types = session_data.get("allowed_file_types") or sorted(SAFE_SCAN_EXTENSIONS)

        try:
            file_validation = _validate_uploaded_file(
                filename=file_name,
                content=content_head,
                allowed_file_types=allowed_file_types,
            )
            extension = file_validation.get("extension")
            detected_extension = file_validation.get("detected_extension")
            mime_type = file_validation.get("mime_type")
        except Exception as exc:
            return _response(
                400,
                False,
                str(exc),
                {"extension": _get_extension(file_name), "allowed_file_types": allowed_file_types},
            )

        attach_field = session_data.get("attach_field")
        upload_mode = session_data.get("upload_mode") or "Attachment Only"
        folder = session_data.get("folder") or "Home/Attachments"
        is_private = cint(session_data.get("is_private"))

        if not doctype or not docname:
            _cache_delete(scan_token)
            return _response(400, False, "Invalid scan session target")

        if not frappe.db.exists(doctype, docname):
            _cache_delete(scan_token)
            return _response(404, False, "Target document no longer exists")

        try:
            target_doc = frappe.get_doc(doctype, docname)
            target_doc.check_permission("write")
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Surhan Scanner Target Permission Failed")
            return _response(403, False, "You do not have permission to attach scanned file to this document")

        if upload_mode in ["Both", "Set Attach Field"] and attach_field:
            try:
                _validate_attach_field(doctype, attach_field)
            except Exception as exc:
                return _response(400, False, str(exc))

        file_doc_attach_field = None
        if upload_mode in ["Both", "Set Attach Field"] and attach_field:
            file_doc_attach_field = _get_file_doc_attach_field_for_save(doctype, attach_field)

        try:
            settings = _get_settings()

            if _is_s3_storage_enabled(settings):
                file_doc = _save_scan_file_to_s3(
                    temp_path=temp_path,
                    file_name=file_name,
                    doctype=doctype,
                    docname=docname,
                    attach_field=file_doc_attach_field,
                    folder=folder,
                    is_private=is_private,
                    extension=extension,
                    mime_type=mime_type,
                    file_size=file_size,
                )
            else:
                content = _read_temp_file_content(temp_path)
                content = _validate_scan_file_content_before_save(
                    filename=file_name,
                    content=content,
                    extension=extension,
                )

                file_doc = save_file(
                    fname=file_name,
                    content=content,
                    dt=doctype,
                    dn=docname,
                    folder=folder,
                    decode=False,
                    is_private=is_private,
                    df=file_doc_attach_field,
                )

        except Exception as exc:
            error_text = str(exc) or ""
            validation_markers = [
                "Invalid or corrupted PDF file",
                "Invalid or corrupted image file",
                "Uploaded file is empty",
                "PdfStreamError",
                "PdfReadError",
                "Stream has ended unexpectedly",
                "cannot identify image file",
                "image file is truncated",
                "a bytes-like object is required",
            ]

            if any(marker.lower() in error_text.lower() for marker in validation_markers):
                return _response(400, False, "Invalid or corrupted scan file")

            frappe.log_error(frappe.get_traceback(), "Surhan Scanner Save File Failed")
            return _response(500, False, "Could not save uploaded scan file")

        # نحدث المستند الهدف مباشرة بطريقة جماعية:
        # - حقل الإرفاق إن كان مطلوبًا
        # - وحقل الباركود حتى لو كان وضع الرفع Attachment Only
        updates = {}

        if upload_mode in ["Both", "Set Attach Field"] and attach_field:
            ok, attach_error = _safe_attach_file_to_target_field(
                doctype=doctype,
                docname=docname,
                attach_field=attach_field,
                file_url=file_doc.file_url,
                file_name=file_doc.file_name,
            )

            if not ok:
                return _response(
                    500,
                    False,
                    "Could not attach scanned file to target field or child table",
                    {"error": attach_error, "attach_field": attach_field},
                )

        barcode_field = session_data.get("barcode_field") or ""
        barcode_value = _normalize_barcode_value(session_data.get("barcode_value") or "", 255)

        if barcode_field and barcode_value:
            try:
                _validate_barcode_field(doctype, barcode_field)
                updates[barcode_field] = barcode_value
            except Exception:
                frappe.log_error(frappe.get_traceback(), "Surhan Scanner Barcode Field Validation Failed")
                return _response(400, False, "Invalid barcode field")

        if updates:
            updated = _safe_update_target_fields(
                doctype=doctype,
                docname=docname,
                updates=updates,
            )

            if not updated:
                return _response(
                    500,
                    False,
                    "File saved, but could not update target fields",
                    {
                        "file": {
                            "name": file_doc.name,
                            "file_name": file_doc.file_name,
                            "file_url": file_doc.file_url,
                            "file_size": file_size,
                            "is_private": is_private,
                            "extension": extension,
                            "detected_extension": detected_extension,
                            "mime_type": mime_type,
                        }
                    },
                )

        try:
            if session_data.get("agent_id") or session_data.get("agent_machine_name"):
                _upsert_agent_device(
                    agent_id=session_data.get("agent_id"),
                    machine_name=session_data.get("agent_machine_name"),
                    windows_user=session_data.get("agent_windows_user"),
                    agent_version=session_data.get("agent_version"),
                    config_version=session_data.get("agent_config_version"),
                    scanner_name=session_data.get("agent_scanner_name") or session_data.get("scanner_name"),
                    scanner_driver=session_data.get("agent_scanner_driver"),
                    os_version=session_data.get("agent_os_version"),
                    health_url=session_data.get("agent_health_url"),
                    status="Online",
                    last_user=session_data.get("user"),
                    last_upload_status="Success",
                    increment_heartbeat=False,
                    increment_scan=True,
                )
        except Exception:
            frappe.log_error(frappe.get_traceback(), "Surhan Scanner Agent Device Update Failed")

        _create_agent_log(
            session_data=session_data,
            file_doc=file_doc,
            status="Success",
            message="Uploaded by Surhan Scanner Agent",
            file_size_bytes=file_size,
        )

        _cache_delete(scan_token)
        frappe.db.commit()

        return {
            "success": True,
            "message": "Scan uploaded successfully",
            "scan_session_id": session_data.get("scan_session_id"),
            "file": {
                "name": file_doc.name,
                "file_name": file_doc.file_name,
                "file_url": file_doc.file_url,
                "file_size": file_size,
                "is_private": is_private,
                "extension": extension,
                "detected_extension": detected_extension,
                "mime_type": mime_type,
            },
            "doctype": doctype,
            "docname": docname,
            "attach_field": attach_field,
            "upload_mode": upload_mode,
        }

    finally:
        _delete_temp_file(temp_path)


@frappe.whitelist()
def create_scan_session_history():
    _require_scanner_user_api()
    """دالة مساعدة احتياطية غير مستخدمة حاليًا."""
    return {"success": False, "message": "Not implemented"}


# نهاية الملف
