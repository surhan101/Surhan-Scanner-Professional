import json
import os
import time
import traceback
from pathlib import Path

import frappe
import requests

SITE = "ysmo"
BENCH = Path("/home/frappe/frappe-bench")
APP_DIR = BENCH / "apps/surhan_scanner"
REPORT_DIR = APP_DIR / "phase25_reports"
PAYLOAD_DIR = Path("/tmp/surhan_phase25_payloads")

REPORT_DIR.mkdir(parents=True, exist_ok=True)
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

RAW_REPORT = REPORT_DIR / "phase25_archive_storage_raw.txt"
SUMMARY_REPORT = REPORT_DIR / "phase25_archive_storage_summary.json"
CLEANUP_REPORT = REPORT_DIR / "phase25_archive_storage_cleanup.txt"
FINAL_REPORT = REPORT_DIR / "phase25_archive_storage_result.txt"

PREFIX = "PHASE25"
TARGET_DOCTYPE = "ToDo"
RULE_DOCTYPE = "Surhan Scanner Rule"
LOG_DOCTYPE = "Surhan Scanner Log"
UPLOAD_METHOD = "surhan_scanner.agent_api.upload_agent_scan"


def get_port():
    try:
        return json.loads((BENCH / "sites/common_site_config.json").read_text()).get("webserver_port") or 8000
    except Exception:
        return 8000


def base_url():
    return f"http://127.0.0.1:{get_port()}"


def headers():
    return {
        "Host": SITE,
        "Accept": "application/json",
    }


def response_message(resp):
    try:
        data = resp.json()
    except Exception:
        return {"raw": resp.text[:1000]}

    if isinstance(data, dict) and isinstance(data.get("message"), dict):
        return data["message"]

    return data


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


def write_valid_pdf(path: Path, padding_bytes=0):
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        with path.open("wb") as f:
            writer.write(f)

        if padding_bytes:
            with path.open("ab") as f:
                f.write(b"\n%PHASE25_PADDING_START\n")
                f.write(b"A" * padding_bytes)
                f.write(b"\n%PHASE25_PADDING_END\n")
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


def create_session(label, custom_file_name):
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
        custom_file_name=custom_file_name,
    )

    return {
        "label": label,
        "target": target,
        "rule": rule,
        "scan_session_id": session.get("scan_session_id"),
        "scan_token": session.get("scan_token"),
    }


def upload_payload(scan_token, payload_path, upload_filename, mime_type="application/pdf"):
    with open(payload_path, "rb") as fp:
        files = {
            "file": (upload_filename, fp, mime_type)
        }
        resp = requests.post(
            f"{base_url()}/api/method/{UPLOAD_METHOD}",
            headers=headers(),
            data={"scan_token": scan_token},
            files=files,
            timeout=90,
        )

    return {
        "http_status": resp.status_code,
        "message": response_message(resp),
    }


def file_url_to_disk_path(file_url):
    if not file_url:
        return None

    if file_url.startswith("/private/files/"):
        return BENCH / "sites" / SITE / "private" / "files" / Path(file_url).name

    if file_url.startswith("/files/"):
        return BENCH / "sites" / SITE / "public" / "files" / Path(file_url).name

    return None


def get_file_doc(name):
    if not name or not frappe.db.exists("File", name):
        return None

    fields = [
        "name",
        "file_name",
        "file_url",
        "file_size",
        "is_private",
        "attached_to_doctype",
        "attached_to_name",
        "folder",
    ]

    return frappe.get_doc("File", name).as_dict()


def verify_success_case(case, result):
    checks = []

    msg = result.get("message") if isinstance(result.get("message"), dict) else {}
    file_info = msg.get("file") or {}
    file_name = file_info.get("name")
    file_url = file_info.get("file_url")

    checks.append((case["label"], "http_200_success", result["http_status"] == 200 and msg_success(result), result))
    checks.append((case["label"], "file_info_present", bool(file_name and file_url), file_info))
    checks.append((case["label"], "private_file_url", bool(file_url and file_url.startswith("/private/files/")), file_info))

    file_doc = get_file_doc(file_name)
    checks.append((case["label"], "file_doc_exists", bool(file_doc), file_doc))

    if file_doc:
        checks.append((case["label"], "file_doc_is_private", int(file_doc.get("is_private") or 0) == 1, file_doc.get("is_private")))
        checks.append((case["label"], "attached_to_target", file_doc.get("attached_to_doctype") == TARGET_DOCTYPE and file_doc.get("attached_to_name") == case["target"], file_doc))

    disk_path = file_url_to_disk_path(file_url)
    disk_exists = bool(disk_path and disk_path.exists())
    checks.append((case["label"], "disk_file_exists", disk_exists, str(disk_path) if disk_path else None))

    if disk_exists:
        disk_size = disk_path.stat().st_size
        checks.append((case["label"], "disk_file_size_positive", disk_size > 0, disk_size))
        if file_info.get("file_size"):
            checks.append((case["label"], "disk_size_matches_response_or_close", abs(disk_size - int(file_info.get("file_size"))) <= 16, {"disk_size": disk_size, "response_size": file_info.get("file_size")}))

    logs = frappe.get_all(
        LOG_DOCTYPE,
        filters={"scan_session_id": case["scan_session_id"]},
        fields=["name", "status", "file_name", "file_url", "scan_session_id"],
        limit_page_length=20,
    )
    checks.append((case["label"], "scan_log_exists", bool(logs), logs))
    checks.append((case["label"], "scan_log_success", any(str(x.get("status")).lower() == "success" for x in logs), logs))
    checks.append((case["label"], "scan_log_file_url_matches", any(x.get("file_url") == file_url for x in logs), logs))

    return checks


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

    for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase25%"]}, pluck="name"):
        safe_delete(LOG_DOCTYPE, name, deleted)

    for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%أرشفة%"]}, pluck="name"):
        safe_delete(LOG_DOCTYPE, name, deleted)

    for name in frappe.get_all("File", filters={"file_name": ["like", "%phase25%"]}, pluck="name"):
        safe_delete("File", name, deleted)

    for name in frappe.get_all("File", filters={"file_name": ["like", "%أرشفة%"]}, pluck="name"):
        safe_delete("File", name, deleted)

    for name in frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} TEST TARGET%"]}, pluck="name"):
        safe_delete(TARGET_DOCTYPE, name, deleted)

    for name in frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, pluck="name"):
        safe_delete(RULE_DOCTYPE, name, deleted)

    # تنظيف بقايا فعلية على القرص، لكن فقط الملفات التي تبدأ phase25
    for folder in [
        BENCH / "sites" / SITE / "private" / "files",
        BENCH / "sites" / SITE / "public" / "files",
    ]:
        if folder.exists():
            for path in folder.glob("phase25*"):
                try:
                    if path.is_file():
                        path.unlink()
                        deleted.append(("disk_file", str(path), True))
                except Exception as exc:
                    deleted.append(("disk_file", str(path), False, str(exc)))

    frappe.db.commit()
    return deleted


def find_orphans_by_prefix():
    private_dir = BENCH / "sites" / SITE / "private" / "files"
    public_dir = BENCH / "sites" / SITE / "public" / "files"

    disk_files = []
    for folder, prefix in [(private_dir, "/private/files/"), (public_dir, "/files/")]:
        if folder.exists():
            for path in folder.glob("phase25*"):
                if path.is_file():
                    disk_files.append({
                        "path": str(path),
                        "file_url": prefix + path.name,
                        "size": path.stat().st_size,
                    })

    file_docs = frappe.get_all(
        "File",
        filters={"file_name": ["like", "%phase25%"]},
        fields=["name", "file_name", "file_url", "is_private", "attached_to_doctype", "attached_to_name"],
        limit_page_length=100,
    )

    logs = frappe.get_all(
        LOG_DOCTYPE,
        filters={"file_name": ["like", "%phase25%"]},
        fields=["name", "file_name", "file_url", "scan_session_id", "status"],
        limit_page_length=100,
    )

    return {
        "disk_files": disk_files,
        "file_docs": file_docs,
        "logs": logs,
    }


def main():
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        previous_cleanup = cleanup_previous()

        results = []
        checks = []
        cases = []

        # إعداد payloads
        small_pdf = PAYLOAD_DIR / "phase25_small.pdf"
        arabic_pdf = PAYLOAD_DIR / "phase25_أرشفة_عربية.pdf"
        long_pdf = PAYLOAD_DIR / ("phase25_" + "x" * 100 + ".pdf")
        medium_pdf = PAYLOAD_DIR / "phase25_medium_3mb.pdf"
        exe_file = PAYLOAD_DIR / "phase25_forbidden.exe"

        write_valid_pdf(small_pdf)
        write_valid_pdf(arabic_pdf)
        write_valid_pdf(long_pdf)
        write_valid_pdf(medium_pdf, padding_bytes=3 * 1024 * 1024)
        exe_file.write_bytes(b"MZ" + b"\x00" * 256)

        success_specs = [
            {
                "label": "small_private_pdf",
                "payload": small_pdf,
                "upload_filename": "phase25_small.pdf",
                "custom_file_name": "phase25_small_private_pdf",
            },
            {
                "label": "arabic_private_pdf",
                "payload": arabic_pdf,
                "upload_filename": "أرشفة_تجريبية_مرحلة25.pdf",
                "custom_file_name": "phase25_أرشفة_عربية",
            },
            {
                "label": "long_name_private_pdf",
                "payload": long_pdf,
                "upload_filename": "phase25_" + "x" * 120 + ".pdf",
                "custom_file_name": "phase25_" + "long_" * 25,
            },
            {
                "label": "medium_3mb_private_pdf",
                "payload": medium_pdf,
                "upload_filename": "phase25_medium_3mb.pdf",
                "custom_file_name": "phase25_medium_3mb_private_pdf",
            },
        ]

        # رفع الحالات الصحيحة
        for spec in success_specs:
            sess = create_session(spec["label"], spec["custom_file_name"])
            frappe.db.commit()

            case = {
                **spec,
                **sess,
            }
            cases.append(case)

            r = upload_payload(
                scan_token=sess["scan_token"],
                payload_path=str(spec["payload"]),
                upload_filename=spec["upload_filename"],
                mime_type="application/pdf",
            )
            results.append((spec["label"], r))
            checks.extend(verify_success_case(case, r))
            checks.append((spec["label"], "no_http_500", no_500(r), r))

        # حالة ممنوعة: exe لا يجب أن تتحول إلى File Doc أو قرص
        exe_sess = create_session("forbidden_exe_storage", "phase25_forbidden_exe_storage")
        frappe.db.commit()
        exe_case = {
            "label": "forbidden_exe_storage",
            "payload": exe_file,
            "upload_filename": "phase25_forbidden.exe",
            "custom_file_name": "phase25_forbidden_exe_storage",
            **exe_sess,
        }
        cases.append(exe_case)

        r = upload_payload(
            scan_token=exe_sess["scan_token"],
            payload_path=str(exe_file),
            upload_filename="phase25_forbidden.exe",
            mime_type="application/octet-stream",
        )
        results.append(("forbidden_exe_storage", r))
        checks.append(("forbidden_exe_storage", "expected_400", r["http_status"] == 400 and not msg_success(r), r))
        checks.append(("forbidden_exe_storage", "no_http_500", no_500(r), r))

        pre_cleanup_orphans = find_orphans_by_prefix()

        # تنظيف كل ما أنشأناه
        deleted = []

        for label, r in results:
            msg = r.get("message") if isinstance(r.get("message"), dict) else {}
            file_info = msg.get("file") or {}
            if file_info.get("name"):
                safe_delete("File", file_info.get("name"), deleted)

        for case in cases:
            if case.get("scan_session_id"):
                for row in frappe.get_all(LOG_DOCTYPE, filters={"scan_session_id": case["scan_session_id"]}, pluck="name"):
                    safe_delete(LOG_DOCTYPE, row, deleted)

            safe_delete(TARGET_DOCTYPE, case.get("target"), deleted)
            safe_delete(RULE_DOCTYPE, case.get("rule"), deleted)

        frappe.db.commit()

        # تنظيف أي بقايا قرص بدأت phase25
        disk_cleanup = []
        for folder in [
            BENCH / "sites" / SITE / "private" / "files",
            BENCH / "sites" / SITE / "public" / "files",
        ]:
            if folder.exists():
                for path in folder.glob("phase25*"):
                    try:
                        if path.is_file():
                            path.unlink()
                            disk_cleanup.append((str(path), True))
                    except Exception as exc:
                        disk_cleanup.append((str(path), False, str(exc)))

        post_cleanup_orphans = find_orphans_by_prefix()

        cleanup_ok = (
            len(post_cleanup_orphans["disk_files"]) == 0
            and len(post_cleanup_orphans["file_docs"]) == 0
            and len(post_cleanup_orphans["logs"]) == 0
        )
        checks.append(("cleanup_ok_no_phase25_orphans", cleanup_ok, post_cleanup_orphans))

        all_passed = all(bool(c[2]) for c in checks)

        summary = {
            "previous_cleanup": previous_cleanup,
            "results": results,
            "pre_cleanup_orphans": pre_cleanup_orphans,
            "deleted": deleted,
            "disk_cleanup": disk_cleanup,
            "post_cleanup_orphans": post_cleanup_orphans,
            "checks": checks,
            "cleanup_ok": cleanup_ok,
            "all_passed": all_passed,
        }

        SUMMARY_REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        raw_lines = []
        raw_lines.append("=== Phase 25 Archive & Storage Integrity Raw Results ===")
        raw_lines.append(f"BASE_URL={base_url()}")
        raw_lines.append("")
        for label, r in results:
            raw_lines.append(f"--- {label} ---")
            raw_lines.append(json.dumps(r, ensure_ascii=False, indent=2, default=str))
            raw_lines.append("")
        RAW_REPORT.write_text("\n".join(raw_lines), encoding="utf-8")

        CLEANUP_REPORT.write_text(
            "=== Pre Cleanup Orphans ===\n"
            + json.dumps(pre_cleanup_orphans, ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Deleted ===\n"
            + json.dumps(deleted, ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Disk Cleanup ===\n"
            + json.dumps(disk_cleanup, ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Post Cleanup Orphans ===\n"
            + json.dumps(post_cleanup_orphans, ensure_ascii=False, indent=2, default=str)
            + f"\n\ncleanup_ok={cleanup_ok}\n",
            encoding="utf-8",
        )

        with FINAL_REPORT.open("w", encoding="utf-8") as f:
            f.write("=== Phase 25 Archive & Storage Integrity Test Result ===\n\n")

            f.write("=== HTTP Results ===\n")
            for label, r in results:
                f.write(f"{label}: http={r.get('http_status')} message={msg_text(r)}\n")

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
            "=== Phase 25 Archive & Storage Integrity Test Result ===\n\n"
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
