import gzip
import json
import os
import shutil
import subprocess
import tarfile
import time
import traceback
from pathlib import Path

import frappe
import requests

SITE = "ysmo"
BENCH = Path("/home/frappe/frappe-bench")
APP_DIR = BENCH / "apps/surhan_scanner"
REPORT_DIR = APP_DIR / "phase29_reports"
PAYLOAD_DIR = Path("/tmp/surhan_phase29_payloads")
BACKUP_DIR = BENCH / "sites" / SITE / "private" / "backups"

REPORT_DIR.mkdir(parents=True, exist_ok=True)
PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)

RAW_REPORT = REPORT_DIR / "phase29_backup_restore_raw.txt"
SUMMARY_REPORT = REPORT_DIR / "phase29_backup_restore_summary.json"
CLEANUP_REPORT = REPORT_DIR / "phase29_backup_restore_cleanup.txt"
FINAL_REPORT = REPORT_DIR / "phase29_backup_restore_result.txt"

PREFIX = "PHASE29"
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


def clear_surhan_rate_limit_cache():
    patterns = [
        "surhan_scanner:rate_limit:*",
        "*surhan_scanner:rate_limit:*",
    ]

    cache = frappe.cache()
    deleted = []

    for pattern in patterns:
        try:
            cache.delete_keys(pattern)
            deleted.append({"pattern": pattern, "method": "delete_keys"})
            continue
        except Exception:
            pass

        try:
            keys = cache.get_keys(pattern)
            for key in keys or []:
                try:
                    cache.delete_value(key)
                except Exception:
                    try:
                        cache.delete_value(key.decode() if isinstance(key, bytes) else str(key))
                    except Exception:
                        pass
            deleted.append({"pattern": pattern, "method": "get_keys_delete_value", "count": len(keys or [])})
        except Exception as exc:
            deleted.append({"pattern": pattern, "error": str(exc)})

    return deleted


def refresh_db():
    try:
        frappe.db.commit()
    except Exception:
        try:
            frappe.db.rollback()
        except Exception:
            pass


def write_valid_pdf(path: Path, marker: str):
    try:
        from pypdf import PdfWriter

        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        with path.open("wb") as f:
            writer.write(f)

        with path.open("ab") as f:
            f.write(("\n%" + marker + "\n").encode("utf-8"))
    except Exception:
        path.write_bytes(
            (
                "%PDF-1.4\n"
                "1 0 obj\n"
                "<< /Type /Catalog /Pages 2 0 R >>\n"
                "endobj\n"
                "2 0 obj\n"
                "<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
                "endobj\n"
                "3 0 obj\n"
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 72 72] >>\n"
                "endobj\n"
                "xref\n"
                "0 4\n"
                "0000000000 65535 f \n"
                "0000000009 00000 n \n"
                "0000000058 00000 n \n"
                "0000000115 00000 n \n"
                "trailer\n"
                "<< /Root 1 0 R /Size 4 >>\n"
                "startxref\n"
                "188\n"
                "%%EOF\n"
                f"%{marker}\n"
            ).encode("utf-8")
        )


def normalize_rule_file_type(file_type):
    ft = str(file_type or "Default").strip().upper()
    if ft == "PDF":
        return "PDF"
    if ft in {"JPG", "JPEG"}:
        return "JPG"
    return "Default"


def create_target(marker):
    doc = frappe.new_doc(TARGET_DOCTYPE)
    doc.description = f"{PREFIX} BACKUP RESTORE READINESS TARGET - {marker}"
    doc.insert(ignore_permissions=True)
    return doc.name


def create_rule(marker):
    rule = frappe.new_doc(RULE_DOCTYPE)

    set_if_field(rule, "enabled", 1)
    set_if_field(rule, "rule_name", f"{PREFIX} {marker}")
    set_if_field(rule, "target_doctype", TARGET_DOCTYPE)
    set_if_field(rule, "placement_type", "Toolbar Group")
    set_if_field(rule, "upload_mode", "Attachment Only")
    set_if_field(rule, "file_type", normalize_rule_file_type("PDF"))
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


def create_scan_test_data(marker):
    import surhan_scanner.agent_api as agent_api

    clear_surhan_rate_limit_cache()

    agent_api._enforce_create_scan_session_rate_limit = lambda: None
    create_scan_session = agent_api.create_scan_session

    target = create_target(marker)
    rule = create_rule(marker)

    custom_file_name = f"phase29_backup_restore_{marker}"

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

    frappe.db.commit()

    payload = PAYLOAD_DIR / f"{custom_file_name}.pdf"
    write_valid_pdf(payload, f"PHASE29_BACKUP_RESTORE_{marker}")

    with payload.open("rb") as fp:
        resp = requests.post(
            f"{base_url()}/api/method/{UPLOAD_METHOD}",
            headers=headers(),
            data={"scan_token": session.get("scan_token")},
            files={"file": (payload.name, fp, "application/pdf")},
            timeout=120,
        )

    upload_result = {
        "kind": "http",
        "http_status": resp.status_code,
        "message": response_message(resp),
    }

    refresh_db()

    return {
        "target": target,
        "rule": rule,
        "scan_session_id": session.get("scan_session_id"),
        "scan_token": session.get("scan_token"),
        "custom_file_name": custom_file_name,
        "payload": str(payload),
        "upload_result": upload_result,
    }


def phase_counts():
    return {
        "targets": frappe.db.count(TARGET_DOCTYPE, {"description": ["like", f"%{PREFIX} BACKUP RESTORE READINESS TARGET%"]}),
        "rules": frappe.db.count(RULE_DOCTYPE, {"rule_name": ["like", f"%{PREFIX}%"]}),
        "logs": frappe.db.count(LOG_DOCTYPE, {"file_name": ["like", "%phase29_backup_restore%"]}),
        "files": frappe.db.count("File", {"file_name": ["like", "%phase29_backup_restore%"]}),
    }


def get_file_doc(file_name):
    rows = frappe.get_all(
        "File",
        filters={"file_name": file_name},
        fields=["name", "file_name", "file_url", "file_size", "is_private", "attached_to_doctype", "attached_to_name"],
        limit_page_length=10,
    )
    return rows[0] if rows else None


def get_scan_log(scan_session_id):
    existing = {
        df.fieldname
        for df in getattr(frappe.get_meta(LOG_DOCTYPE), "fields", [])
        if getattr(df, "fieldname", None)
    }
    wanted = ["name", "status", "file_name", "file_url", "scan_session_id"]
    fields = [x for x in wanted if x == "name" or x in existing]

    rows = frappe.get_all(
        LOG_DOCTYPE,
        filters={"scan_session_id": scan_session_id},
        fields=fields,
        limit_page_length=10,
    )
    return rows[0] if rows else None


def list_backup_files():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    return {
        p.name: {
            "path": str(p),
            "mtime": p.stat().st_mtime,
            "size": p.stat().st_size,
        }
        for p in BACKUP_DIR.glob("*")
        if p.is_file()
    }


def run_backup():
    before = list_backup_files()

    cmd = ["bench", "--site", SITE, "backup", "--with-files"]
    proc = subprocess.run(
        cmd,
        cwd=str(BENCH),
        text=True,
        capture_output=True,
        timeout=600,
    )

    after = list_backup_files()
    before_names = set(before.keys())
    new_files = {
        name: meta
        for name, meta in after.items()
        if name not in before_names or meta.get("mtime") != before.get(name, {}).get("mtime")
    }

    return {
        "command": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-3000:],
        "new_files": new_files,
    }


def classify_backup_files(new_files):
    sql_files = []
    public_files = []
    private_files = []
    other_files = []

    for name, meta in new_files.items():
        lower = name.lower()
        if lower.endswith(".sql.gz") or lower.endswith(".sql"):
            sql_files.append(meta["path"])
        elif "private" in lower and (lower.endswith(".tar") or lower.endswith(".tar.gz") or lower.endswith(".tgz")):
            private_files.append(meta["path"])
        elif "files" in lower and (lower.endswith(".tar") or lower.endswith(".tar.gz") or lower.endswith(".tgz")):
            public_files.append(meta["path"])
        else:
            other_files.append(meta["path"])

    return {
        "sql_files": sql_files,
        "public_files": public_files,
        "private_files": private_files,
        "other_files": other_files,
    }


def verify_sql_backup(sql_path, expected_terms):
    """Stream-search the full SQL backup instead of reading only an early sample."""
    p = Path(sql_path)
    result = {
        "path": sql_path,
        "exists": p.exists(),
        "readable": False,
        "contains": {term: False for term in expected_terms},
        "bytes_scanned_estimate": 0,
    }

    try:
        if p.name.lower().endswith(".gz"):
            opener = gzip.open
            mode = "rt"
        else:
            opener = open
            mode = "r"

        pending = set(expected_terms)
        carry = ""

        with opener(p, mode, encoding="utf-8", errors="ignore") as f:
            while True:
                chunk = f.read(1024 * 1024)
                if not chunk:
                    break

                result["readable"] = True
                result["bytes_scanned_estimate"] += len(chunk.encode("utf-8", errors="ignore"))

                blob = carry + chunk
                for term in list(pending):
                    if term and term in blob:
                        result["contains"][term] = True
                        pending.remove(term)

                carry = blob[-4096:]

                if not pending:
                    break

        result["missing_terms"] = sorted(pending)

    except Exception as exc:
        result["error"] = str(exc)

    return result


def verify_tar_backup(tar_path, expected_basename):
    result = {
        "path": tar_path,
        "exists": Path(tar_path).exists(),
        "readable": False,
        "contains_expected_file": False,
        "sample_names": [],
    }

    try:
        with tarfile.open(tar_path, "r:*") as tf:
            names = tf.getnames()
            result["readable"] = True
            result["sample_names"] = names[:30]
            result["contains_expected_file"] = any(Path(name).name == expected_basename for name in names)
    except Exception as exc:
        result["error"] = str(exc)

    return result


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

    for name in frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase29_backup_restore%"]}, pluck="name"):
        safe_delete(LOG_DOCTYPE, name, deleted)

    for name in frappe.get_all("File", filters={"file_name": ["like", "%phase29_backup_restore%"]}, pluck="name"):
        safe_delete("File", name, deleted)

    for name in frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} BACKUP RESTORE READINESS TARGET%"]}, pluck="name"):
        safe_delete(TARGET_DOCTYPE, name, deleted)

    for name in frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, pluck="name"):
        safe_delete(RULE_DOCTYPE, name, deleted)

    for folder in [
        BENCH / "sites" / SITE / "private" / "files",
        BENCH / "sites" / SITE / "public" / "files",
    ]:
        if folder.exists():
            for path in folder.glob("phase29_backup_restore*"):
                try:
                    if path.is_file():
                        path.unlink()
                        deleted.append(("disk_file", str(path), True))
                except Exception as exc:
                    deleted.append(("disk_file", str(path), False, str(exc)))

    frappe.db.commit()
    return deleted


def find_remaining():
    private_dir = BENCH / "sites" / SITE / "private" / "files"
    public_dir = BENCH / "sites" / SITE / "public" / "files"

    disk_files = []
    for folder in [private_dir, public_dir]:
        if folder.exists():
            for path in folder.glob("phase29_backup_restore*"):
                if path.is_file():
                    disk_files.append(str(path))

    return {
        "targets": frappe.get_all(TARGET_DOCTYPE, filters={"description": ["like", f"%{PREFIX} BACKUP RESTORE READINESS TARGET%"]}, fields=["name"]),
        "rules": frappe.get_all(RULE_DOCTYPE, filters={"rule_name": ["like", f"%{PREFIX}%"]}, fields=["name"]),
        "logs": frappe.get_all(LOG_DOCTYPE, filters={"file_name": ["like", "%phase29_backup_restore%"]}, fields=["name", "file_name", "file_url"]),
        "files": frappe.get_all("File", filters={"file_name": ["like", "%phase29_backup_restore%"]}, fields=["name", "file_name", "file_url"]),
        "disk_files": disk_files,
    }


def scan_for_token_leaks(tokens):
    leaks = {
        "error_logs": [],
        "phase29_reports": [],
    }

    tokens = [t for t in tokens if t]
    if not tokens:
        return leaks

    rows = frappe.get_all(
        "Error Log",
        fields=["name", "creation", "method", "error"],
        order_by="creation desc",
        limit_page_length=100,
    )

    for row in rows:
        blob = json.dumps(row, ensure_ascii=False, default=str)
        for token in tokens:
            if token in blob:
                leaks["error_logs"].append({
                    "name": row.get("name"),
                    "creation": str(row.get("creation")),
                    "method": row.get("method"),
                })
                break

    for path in REPORT_DIR.glob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="ignore")
            for token in tokens:
                if token in text:
                    leaks["phase29_reports"].append(str(path))
                    break

    return leaks


def main():
    frappe.init(site=SITE, sites_path=str(BENCH / "sites"))
    frappe.connect()
    frappe.set_user("Administrator")

    try:
        checks = []

        previous_cleanup = cleanup_previous()
        refresh_db()

        initial_counts = phase_counts()
        checks.append(("initial_phase_counts_zero", all(v == 0 for v in initial_counts.values()), initial_counts))

        marker = str(int(time.time()))
        test_data = create_scan_test_data(marker)
        upload_result = test_data["upload_result"]
        upload_msg = upload_result.get("message") if isinstance(upload_result.get("message"), dict) else {}
        file_info = upload_msg.get("file") if isinstance(upload_msg, dict) else {}

        refresh_db()

        file_doc = get_file_doc(file_info.get("file_name"))
        scan_log = get_scan_log(test_data.get("scan_session_id"))
        after_create_counts = phase_counts()

        checks.append(("upload_success_before_backup", upload_result.get("http_status") == 200 and msg_success(upload_result), upload_result))
        checks.append(("file_doc_exists_before_backup", bool(file_doc), file_doc))
        checks.append(("scan_log_exists_before_backup", bool(scan_log), scan_log))
        checks.append(("after_create_counts_expected", after_create_counts["targets"] == 1 and after_create_counts["rules"] == 1 and after_create_counts["files"] == 1 and after_create_counts["logs"] == 1, after_create_counts))

        backup_result = run_backup()
        classified = classify_backup_files(backup_result["new_files"])

        checks.append(("backup_command_success", backup_result["returncode"] == 0, backup_result))
        checks.append(("backup_sql_file_created", len(classified["sql_files"]) >= 1, classified))
        checks.append(("backup_private_files_created", len(classified["private_files"]) >= 1, classified))

        expected_sql_terms = [
            test_data["target"],
            test_data["rule"],
            test_data["custom_file_name"],
            file_info.get("file_name"),
            file_info.get("file_url"),
            test_data["scan_session_id"],
        ]
        expected_sql_terms = [x for x in expected_sql_terms if x]

        sql_verification = None
        if classified["sql_files"]:
            sql_path = max(classified["sql_files"], key=lambda x: Path(x).stat().st_mtime)
            sql_verification = verify_sql_backup(sql_path, expected_sql_terms)
            checks.append(("backup_sql_readable", sql_verification.get("readable") is True, sql_verification))
            checks.append(("backup_sql_contains_phase29_data", all(sql_verification.get("contains", {}).values()), sql_verification))
        else:
            checks.append(("backup_sql_readable", False, classified))
            checks.append(("backup_sql_contains_phase29_data", False, classified))

        private_tar_verification = None
        if classified["private_files"] and file_info.get("file_name"):
            private_tar_path = max(classified["private_files"], key=lambda x: Path(x).stat().st_mtime)
            private_tar_verification = verify_tar_backup(private_tar_path, file_info.get("file_name"))
            checks.append(("backup_private_tar_readable", private_tar_verification.get("readable") is True, private_tar_verification))
            checks.append(("backup_private_tar_contains_uploaded_file", private_tar_verification.get("contains_expected_file") is True, private_tar_verification))
        else:
            checks.append(("backup_private_tar_readable", False, classified))
            checks.append(("backup_private_tar_contains_uploaded_file", False, classified))

        token_leaks = scan_for_token_leaks([test_data.get("scan_token")])
        checks.append(("scan_token_not_in_recent_error_logs", len(token_leaks["error_logs"]) == 0, token_leaks["error_logs"]))
        checks.append(("scan_token_not_in_phase29_reports", len(token_leaks["phase29_reports"]) == 0, token_leaks["phase29_reports"]))

        deleted = cleanup_previous()
        refresh_db()

        final_remaining = find_remaining()
        final_cleanup_ok = all(len(v) == 0 for v in final_remaining.values())
        final_counts = phase_counts()

        checks.append(("final_cleanup_ok", final_cleanup_ok, final_remaining))
        checks.append(("final_phase_counts_zero", all(v == 0 for v in final_counts.values()), final_counts))

        all_passed = all(bool(c[1]) for c in checks)

        safe_test_data = {
            k: ("***REDACTED***" if k == "scan_token" else v)
            for k, v in test_data.items()
            if k != "upload_result"
        }

        summary_doc = {
            "previous_cleanup": previous_cleanup,
            "initial_counts": initial_counts,
            "test_data": safe_test_data,
            "upload_result": upload_result,
            "file_doc": file_doc,
            "scan_log": scan_log,
            "after_create_counts": after_create_counts,
            "backup_result": backup_result,
            "classified_backup_files": classified,
            "sql_verification": sql_verification,
            "private_tar_verification": private_tar_verification,
            "token_leaks": token_leaks,
            "deleted_count": len(deleted),
            "final_remaining": final_remaining,
            "final_counts": final_counts,
            "checks": checks,
            "all_passed": all_passed,
        }

        SUMMARY_REPORT.write_text(json.dumps(summary_doc, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

        RAW_REPORT.write_text(
            "=== Phase 29 Backup & Restore Readiness Raw ===\n\n"
            + json.dumps(summary_doc, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

        CLEANUP_REPORT.write_text(
            "=== Deleted Count ===\n"
            + str(len(deleted))
            + "\n\n=== Final Remaining ===\n"
            + json.dumps(final_remaining, ensure_ascii=False, indent=2, default=str)
            + "\n\n=== Final Counts ===\n"
            + json.dumps(final_counts, ensure_ascii=False, indent=2, default=str)
            + f"\n\nfinal_cleanup_ok={final_cleanup_ok}\n",
            encoding="utf-8",
        )

        with FINAL_REPORT.open("w", encoding="utf-8") as f:
            f.write("=== Phase 29 Backup & Restore Readiness Test Result ===\n\n")

            f.write("=== Counts ===\n")
            f.write(f"initial_counts={json.dumps(initial_counts, ensure_ascii=False, default=str)}\n")
            f.write(f"after_create_counts={json.dumps(after_create_counts, ensure_ascii=False, default=str)}\n")
            f.write(f"final_counts={json.dumps(final_counts, ensure_ascii=False, default=str)}\n")

            f.write("\n=== Upload ===\n")
            f.write(json.dumps(upload_result, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Backup ===\n")
            f.write(json.dumps({
                "returncode": backup_result.get("returncode"),
                "new_file_count": len(backup_result.get("new_files", {})),
                "classified": classified,
            }, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Restore Readiness Verification ===\n")
            f.write(json.dumps({
                "sql_verification": sql_verification,
                "private_tar_verification": private_tar_verification,
            }, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Token Leakage ===\n")
            f.write(json.dumps(token_leaks, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Checks ===\n")
            for c in checks:
                f.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")

            f.write("\n=== Cleanup ===\n")
            f.write(f"final_cleanup_ok={final_cleanup_ok}\n")

            f.write("\n=== Result ===\n")
            f.write("PASSED\n" if all_passed else "REVIEW_REQUIRED\n")

        print(FINAL_REPORT.read_text(encoding="utf-8"))

    except Exception:
        frappe.db.rollback()
        err = traceback.format_exc()
        FINAL_REPORT.write_text(
            "=== Phase 29 Backup & Restore Readiness Test Result ===\n\n"
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
