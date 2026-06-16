import json
import time
import traceback
from pathlib import Path

import frappe
import requests

SITE = "ysmo"
BENCH = Path("/home/frappe/frappe-bench")
APP_DIR = BENCH / "apps/surhan_scanner"
REPORT_DIR = APP_DIR / "phase24_reports"
PAYLOAD_DIR = Path("/tmp/surhan_phase24_payloads")

REPORT_DIR.mkdir(parents=True, exist_ok=True)
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

RAW_REPORT = REPORT_DIR / "phase24_security_abuse_raw.txt"
SUMMARY_REPORT = REPORT_DIR / "phase24_security_abuse_summary.json"
CLEANUP_REPORT = REPORT_DIR / "phase24_security_abuse_cleanup.txt"
FINAL_REPORT = REPORT_DIR / "phase24_security_abuse_result.txt"

PREFIX = "PHASE24"
TARGET_DOCTYPE = "ToDo"
RULE_DOCTYPE = "Surhan Scanner Rule"
LOG_DOCTYPE = "Surhan Scanner Log"
AGENT_DEVICE_DOCTYPE = "Surhan Scanner Agent Device"

UPLOAD_METHOD = "surhan_scanner.agent_api.upload_agent_scan"


def get_port():
    try:
        return json.loads((BENCH / "sites/common_site_config.json").read_text()).get("webserver_port") or 8000
    except Exception:
        return 8000


def base_url():
    return f"http://127.0.0.1:{get_port()}"


def headers(extra=None):
    h = {
        "Host": SITE,
        "Accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def response_message(resp):
    try:
        data = resp.json()
    except Exception:
        return {"raw": resp.text[:1000]}

    if isinstance(data, dict) and isinstance(data.get("message"), dict):
        return data["message"]

    return data


def http_get(method, params=None, session=None):
    s = session or requests
    resp = s.get(
        f"{base_url()}/api/method/{method}",
        headers=headers(),
        params=params or {},
        timeout=60,
    )
    return {
        "http_status": resp.status_code,
        "message": response_message(resp),
    }


def http_post(method, data=None, session=None, files=None):
    s = session or requests
    resp = s.post(
        f"{base_url()}/api/method/{method}",
        headers=headers(),
        data=data or {},
        files=files,
        timeout=60,
    )
    return {
        "http_status": resp.status_code,
        "message": response_message(resp),
    }


def raw_get_path(path, session=None):
    s = session or requests
    resp = s.get(
        f"{base_url()}{path}",
        headers=headers(),
        timeout=60,
        allow_redirects=False,
    )
    return {
        "http_status": resp.status_code,
        "content_type": resp.headers.get("Content-Type"),
        "location": resp.headers.get("Location"),
        "text_head": resp.text[:300],
    }


def msg_success(result):
    msg = result.get("message")
    return isinstance(msg, dict) and bool(msg.get("success"))


def msg_text(result):
    msg = result.get("message")
    if isinstance(msg, dict):
        return str(msg.get("message") or msg)
    return str(msg)


def no_500(result):
    return int(result.get("http_status") or 0) != 500


def set_if_field(doc, fieldname, value):
    try:
        if doc.meta.has_field(fieldname):
            doc.set(fieldname, value)
            return
    except Exception:
        pass

    try:
        if fieldname in [df.fieldname for df in getattr(doc.meta, "fields", [])]:
            doc.set(fieldname, value)
    except Exception:
        pass


def normalize_rule_file_type(file_type):
    ft = str(file_type or "Default").strip().upper()
    if ft == "PDF":
        return "PDF"
    if ft in {"JPG", "JPEG"}:
        return "JPG"
    return "Default"


def write_valid_pdf(path: Path):
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with path.open("wb") as f:
            writer.write(f)
    except Exception:
        path.write_bytes(
            b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] >>
endobj
xref
0 4
0000000000 65535 f 
0000000009 00000 n 
0000000058 00000 n 
0000000115 00000 n 
trailer
<< /Root 1 0 R /Size 4 >>
startxref
188
%%EOF
"""
        )


def create_target(label):
    doc = frappe.new_doc(TARGET_DOCTYPE)
    doc.description = f"{PREFIX} TEST TARGET - {label}"
    doc.insert(ignore_permissions=True)
    return doc.name


def create_rule(label, file_type="PDF"):
    rule = frappe.new_doc(RULE_DOCTYPE)

    set_if_field(rule, "enabled", 1)
    set_if_field(rule, "rule_name", f"{PREFIX} {label}")
    set_if_field(rule, "target_doctype", TARGET_DOCTYPE)
    set_if_field(rule, "placement_type", "Toolbar Group")
    set_if_field(rule, "upload_mode", "Attachment Only")
    set_if_field(rule, "file_type", normalize_rule_file_type(file_type))
    set_if_field(rule, "multi_page", 1)
    set_if_field(rule, "is_private", 1)
    set_if_field(rule, "folder", "Home/Attachments")
    set_if_field(rule, "resolution", 200)
    set_if_field(rule, "pixel_type", "Color")
    set_if_field(rule, "use_feeder", 0)
    set_if_field(rule, "duplex", 0)
    set_if_field(rule, "silent_scan", 0)
    set_if_field(rule, "show_preview", 0)
    set_if_field(rule, "scan_batch_mode", "Single Page")
    set_if_field(rule, "max_pages", 1)
    set_if_field(rule, "upload_strategy", "Direct Upload")

    rule.insert(ignore_permissions=True)
    return rule.name


def create_session(label):
    from surhan_scanner.agent_api import create_scan_session

    target = create_target(label)
    rule = create_rule(label)

    session = create_scan_session(
        doctype=TARGET_DOCTYPE,
        docname=target,
        attach_field="",
        upload_mode="Attachment Only",
        rule=rule,
        is_private=1,
        folder="Home/Attachments",
        file_type="pdf",
        resolution=200,
        pixel_type="Color",
        multi_page=1,
        use_feeder=0,
        duplex=0,
        paper_source="Feeder",
        silent_scan=0,
        show_preview=0,
        scan_batch_mode="Single Page",
        max_pages=1,
        upload_strategy="Direct Upload",
        custom_file_name=f"phase24_{label}_{int(time.time())}",
    )

    return {
        "label": label,
        "target": target,
        "rule": rule,
        "scan_session_id": session.get("scan_session_id"),
        "scan_token": session.get("scan_token"),
    }


def safe_delete(dt, name, deleted):
    try:
        if name and frappe.db.exists(dt, name):
            frappe.delete_doc(dt, name, ignore_permissions=True, force=True)
            deleted.append((dt, name, True))
        elif name:
            deleted.append((dt, name, "already_missing"))
    except Exception as exc:
        deleted.append((dt, name, False, str(exc)))


def cleanup_previous():
    deleted = []

    for name in frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": ["like", f"%{PREFIX}%"]}, pluck="name"):
        safe_delete(LOG_DOCTYPE, name, deleted)

    for name in frappe.get_all("File", filters={"file_name": ["like", "%phase24%"]}, pluck="name"):
        safe_delete("File", name, deleted)

    for name in frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, pluck="name"):
        safe_delete(TARGET_DOCTYPE, name, deleted)

    for name in frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, pluck="name"):
        safe_delete(RULE_DOCTYPE, name, deleted)

    try:
        fields = [df.fieldname for df in frappe.get_meta(AGENT_DEVICE_DOCTYPE).fields]
        for field in ["agent_id", "device_id", "machine_name", "hostname", "computer_name"]:
            if field in fields:
                for name in frappe.get_all(AGENT_DEVICE_DOCTYPE, filters={field: ["like", f"%{PREFIX}%"]}, pluck="name"):
                    safe_delete(AGENT_DEVICE_DOCTYPE, name, deleted)
    except Exception:
        pass

    for user in [f"phase24.security.{SITE}@example.test"]:
        try:
            if frappe.db.exists("User", user):
                safe_delete("User", user, deleted)
        except Exception:
            try:
                frappe.db.set_value("User", user, "enabled", 0)
                deleted.append(("User", user, "disabled"))
            except Exception as exc:
                deleted.append(("User", user, False, str(exc)))

    frappe.db.commit()
    return deleted


def upload_private_file(scan_token):
    pdf = PAYLOAD_DIR / "phase24_private.pdf"
    write_valid_pdf(pdf)

    with pdf.open("rb") as fp:
        files = {
            "file": ("phase24_private.pdf", fp, "application/pdf")
        }
        resp = requests.post(
            f"{base_url()}/api/method/{UPLOAD_METHOD}",
            headers=headers(),
            data={"scan_token": scan_token},
            files=files,
            timeout=60,
        )

    r = {
        "http_status": resp.status_code,
        "message": response_message(resp),
    }

    file_doc = {}
    if isinstance(r["message"], dict):
        file_doc = r["message"].get("file") or {}

    return r, file_doc


def create_low_priv_user():
    from frappe.utils.password import update_password

    email = f"phase24.security.{SITE}@example.test"
    password = f"Phase24Pass-{int(time.time())}!"

    if frappe.db.exists("User", email):
        safe_delete("User", email, [])

    user = frappe.new_doc("User")
    user.email = email
    user.first_name = "Phase24"
    user.last_name = "Security"
    user.enabled = 1
    user.send_welcome_email = 0
    user.user_type = "Website User"
    user.insert(ignore_permissions=True)

    update_password(email, password)
    frappe.db.commit()

    return email, password


def login_user(email, password):
    s = requests.Session()
    resp = s.post(
        f"{base_url()}/api/method/login",
        headers=headers(),
        data={"usr": email, "pwd": password},
        timeout=60,
    )
    return s, {
        "http_status": resp.status_code,
        "message": response_message(resp),
        "cookies": list(s.cookies.keys()),
    }


def scan_for_secret_leak(secret):
    leaks = {
        "error_logs": [],
        "phase24_reports": [],
    }

    if not secret:
        return leaks

    try:
        rows = frappe.get_all(
            "Error Log",
            fields=["name", "creation", "method", "error"],
            order_by="creation desc",
            limit_page_length=50,
        )
        for row in rows:
            blob = json.dumps(row, ensure_ascii=False, default=str)
            if secret in blob:
                leaks["error_logs"].append({
                    "name": row.get("name"),
                    "creation": str(row.get("creation")),
                    "method": row.get("method"),
                })
    except Exception as exc:
        leaks["error_logs"].append({"scan_error": str(exc)})

    try:
        for path in REPORT_DIR.glob("*"):
            if path.is_file():
                try:
                    if secret in path.read_text(encoding="utf-8", errors="ignore"):
                        leaks["phase24_reports"].append(str(path))
                except Exception:
                    pass
    except Exception:
        pass

    return leaks


def main():
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        previous_cleanup = cleanup_previous()

        results = []
        checks = []

        # 1) Prepare valid session + private upload
        sess = create_session("security_private_file")
        frappe.db.commit()

        upload_result, file_doc = upload_private_file(sess["scan_token"])
        results.append(("admin_prepared_private_upload", upload_result))
        checks.append(("private_upload_success", upload_result["http_status"] == 200 and msg_success(upload_result), upload_result))

        file_url = file_doc.get("file_url") or ""
        file_name = file_doc.get("name") or ""
        checks.append(("private_file_url_exists", bool(file_url and file_url.startswith("/private/files/")), file_doc))

        # 2) Guest direct access to private file must not be 200
        if file_url:
            r = raw_get_path(file_url)
            results.append(("guest_private_file_direct_get", r))
            checks.append(("guest_private_file_not_200", r["http_status"] != 200, r))
            checks.append(("guest_private_file_no_500", no_500(r), r))

        # 3) Guest protected API abuse
        protected_api_tests = [
            ("guest_get_agent_monitoring_status", "GET", "surhan_scanner.agent_api.get_agent_monitoring_status", {}),
            ("guest_get_agent_dashboard_data", "GET", "surhan_scanner.agent_api.get_agent_dashboard_data", {}),
            ("guest_mark_stale_agents_offline", "POST", "surhan_scanner.agent_api.mark_stale_agents_offline", {}),
            ("guest_get_agent_device_detail", "GET", "surhan_scanner.agent_api.get_agent_device_detail", {"agent_id": f"{PREFIX}-NOPE"}),
            ("guest_set_agent_device_status", "POST", "surhan_scanner.agent_api.set_agent_device_status", {"agent_id": f"{PREFIX}-NOPE", "status": "Offline"}),
            ("guest_create_scan_session", "POST", "surhan_scanner.agent_api.create_scan_session", {
                "doctype": TARGET_DOCTYPE,
                "docname": sess["target"],
                "rule": sess["rule"],
                "upload_mode": "Attachment Only",
            }),
            ("guest_create_scan_session_history", "POST", "surhan_scanner.agent_api.create_scan_session_history", {}),
        ]

        for label, method, endpoint, data in protected_api_tests:
            if method == "GET":
                r = http_get(endpoint, data)
            else:
                r = http_post(endpoint, data)

            results.append((label, r))
            checks.append((f"{label}_not_200", r["http_status"] != 200, r))
            checks.append((f"{label}_no_500", no_500(r), r))

        # 4) Guest abuse on allow_guest APIs with missing/invalid token
        guest_abuse_tests = [
            ("guest_manifest_no_token", "GET", "surhan_scanner.agent_api.get_agent_update_manifest", {}),
            ("guest_manifest_fake_token", "GET", "surhan_scanner.agent_api.get_agent_update_manifest", {"scan_token": "fake-phase24-token"}),
            ("guest_heartbeat_no_token", "POST", "surhan_scanner.agent_api.agent_heartbeat", {}),
            ("guest_heartbeat_fake_token", "POST", "surhan_scanner.agent_api.agent_heartbeat", {"scan_token": "fake-phase24-token"}),
            ("guest_update_status_invalid", "POST", "surhan_scanner.agent_api.report_agent_update_status", {"scan_token": "fake-phase24-token", "status": "Installed"}),
            ("guest_upload_no_token", "POST", "surhan_scanner.agent_api.upload_agent_scan", {}),
        ]

        for label, method, endpoint, data in guest_abuse_tests:
            if method == "GET":
                r = http_get(endpoint, data)
            else:
                r = http_post(endpoint, data)

            results.append((label, r))
            checks.append((f"{label}_not_success", not msg_success(r), r))
            checks.append((f"{label}_safe_status", r["http_status"] in {400, 401, 403, 404, 417}, r))
            checks.append((f"{label}_no_500", no_500(r), r))

        # 5) Low-privileged authenticated user boundary
        low_user, low_pwd = create_low_priv_user()
        low_session, login_result = login_user(low_user, low_pwd)
        results.append(("low_priv_login", login_result))
        checks.append(("low_priv_login_success", login_result["http_status"] == 200, login_result))

        low_priv_tests = [
            ("lowpriv_get_agent_monitoring_status", "GET", "surhan_scanner.agent_api.get_agent_monitoring_status", {}),
            ("lowpriv_get_agent_dashboard_data", "GET", "surhan_scanner.agent_api.get_agent_dashboard_data", {}),
            ("lowpriv_mark_stale_agents_offline", "POST", "surhan_scanner.agent_api.mark_stale_agents_offline", {}),
            ("lowpriv_create_scan_session", "POST", "surhan_scanner.agent_api.create_scan_session", {
                "doctype": TARGET_DOCTYPE,
                "docname": sess["target"],
                "rule": sess["rule"],
                "upload_mode": "Attachment Only",
            }),
            ("lowpriv_get_agent_device_detail", "GET", "surhan_scanner.agent_api.get_agent_device_detail", {"agent_id": f"{PREFIX}-NOPE"}),
        ]

        for label, method, endpoint, data in low_priv_tests:
            if method == "GET":
                r = http_get(endpoint, data, session=low_session)
            else:
                r = http_post(endpoint, data, session=low_session)

            results.append((label, r))
            checks.append((f"{label}_not_200_success", not (r["http_status"] == 200 and msg_success(r)), r))
            checks.append((f"{label}_no_500", no_500(r), r))

        # 6) Low-priv direct private file access must not be 200
        if file_url:
            r = raw_get_path(file_url, session=low_session)
            results.append(("lowpriv_private_file_direct_get", r))
            checks.append(("lowpriv_private_file_not_200", r["http_status"] != 200, r))
            checks.append(("lowpriv_private_file_no_500", no_500(r), r))

        # 7) Token leakage scan
        token_leaks = scan_for_secret_leak(sess["scan_token"])
        checks.append(("scan_token_not_in_recent_error_logs", len(token_leaks["error_logs"]) == 0, token_leaks["error_logs"]))
        checks.append(("scan_token_not_in_phase24_reports", len(token_leaks["phase24_reports"]) == 0, token_leaks["phase24_reports"]))

        # 8) Cleanup
        deleted = []

        if file_name:
            safe_delete("File", file_name, deleted)

        for row in frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": sess["scan_session_id"]}, pluck="name"):
            safe_delete(LOG_DOCTYPE, row, deleted)

        safe_delete(TARGET_DOCTYPE, sess["target"], deleted)
        safe_delete(RULE_DOCTYPE, sess["rule"], deleted)

        try:
            if frappe.db.exists("User", low_user):
                safe_delete("User", low_user, deleted)
        except Exception:
            try:
                frappe.db.set_value("User", low_user, "enabled", 0)
                deleted.append(("User", low_user, "disabled"))
            except Exception as exc:
                deleted.append(("User", low_user, False, str(exc)))

        frappe.db.commit()

        remaining = {
            "targets": frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, fields=["name", "description"]),
            "rules": frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, fields=["name", "rule_name"]),
            "logs": frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": ["like", f"%{PREFIX}%"]}, fields=["name", "scan_session_id"]),
            "files": frappe.get_all("File", filters={"file_name": ["like", "%phase24%"]}, fields=["name", "file_name"]),
        }

        try:
            remaining["users"] = frappe.get_all("User", filters={"email": ["like", "%phase24.security%"]}, fields=["name", "enabled"])
        except Exception:
            remaining["users"] = []

        cleanup_ok = all(len(v) == 0 for v in remaining.values())
        checks.append(("cleanup_ok", cleanup_ok, remaining))

        all_passed = all(bool(c[1]) for c in checks)

        summary = {
            "previous_cleanup": previous_cleanup,
            "results": results,
            "file_doc": file_doc,
            "token_leaks": token_leaks,
            "deleted": deleted,
            "remaining": remaining,
            "checks": checks,
            "cleanup_ok": cleanup_ok,
            "all_passed": all_passed,
        }

        SUMMARY_REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        raw_lines = []
        raw_lines.append("=== Phase 24 Security Abuse Raw Results ===")
        raw_lines.append(f"BASE_URL={base_url()}")
        raw_lines.append("")
        for label, r in results:
            raw_lines.append(f"--- {label} ---")
            raw_lines.append(json.dumps(r, ensure_ascii=False, indent=2, default=str))
            raw_lines.append("")
        RAW_REPORT.write_text("\n".join(raw_lines), encoding="utf-8")

        CLEANUP_REPORT.write_text(
            "=== Deleted ===\n"
            + json.dumps(deleted, ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Remaining ===\n"
            + json.dumps(remaining, ensure_ascii=False, indent=2, default=str)
            + f"\n\ncleanup_ok={cleanup_ok}\n",
            encoding="utf-8",
        )

        with FINAL_REPORT.open("w", encoding="utf-8") as f:
            f.write("=== Phase 24 Security Abuse & Permission Boundary Test Result ===\n\n")

            f.write("=== HTTP Results ===\n")
            for label, r in results:
                f.write(f"{label}: http={r.get('http_status')} message={msg_text(r)}\n")

            f.write("\n=== Token Leakage ===\n")
            f.write(json.dumps(token_leaks, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Checks ===\n")
            for c in checks:
                f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Cleanup ===\n")
            f.write(f"cleanup_ok={cleanup_ok}\n")

            f.write("\n=== Result ===\n")
            f.write("PASSED\n" if all_passed else "REVIEW_REQUIRED\n")

        print(FINAL_REPORT.read_text(encoding="utf-8"))

    except Exception:
        frappe.db.rollback()
        err = traceback.format_exc()
        FINAL_REPORT.write_text(
            "=== Phase 24 Security Abuse & Permission Boundary Test Result ===\n\n"
            "=== Result ===\nREVIEW_REQUIRED\n\n"
            "=== Traceback ===\n"
            + err,
            encoding="utf-8",
        )
        print(FINAL_REPORT.read_text(encoding="utf-8"))
        raise

    finally:
        try:
            frappe.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
