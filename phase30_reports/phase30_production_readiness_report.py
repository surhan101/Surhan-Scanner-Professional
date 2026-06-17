import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

APP_DIR = Path("/home/frappe/frappe-bench/apps/surhan_scanner")
BENCH = Path("/home/frappe/frappe-bench")
SITE = "ysmo"

REPORT_DIR = APP_DIR / "phase30_reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

FINAL_TXT = REPORT_DIR / "phase30_production_readiness_result.txt"
FINAL_MD = REPORT_DIR / "phase30_production_readiness_report.md"
FINAL_JSON = REPORT_DIR / "phase30_production_readiness_summary.json"

EXPECTED_PHASES = list(range(21, 30))

BASELINE_TAG = "surhan-scanner-final-hardened-20260616_090846"
BASELINE_BUNDLE = Path("/home/frappe/surhan_scanner_final_hardened_20260616_090846.bundle")
AGENT_ZIP = APP_DIR / "surhan_scanner/public/agent/releases/SurhanScannerAgent-v1.0.2.zip"


def run(cmd, cwd=APP_DIR, timeout=120):
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    return {
        "cmd": " ".join(cmd),
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def safe_read(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return f"READ_ERROR: {exc}"


def disk_snapshot():
    usage = shutil.disk_usage(str(BENCH))
    return {
        "total_gb": round(usage.total / 1024**3, 2),
        "used_gb": round(usage.used / 1024**3, 2),
        "free_gb": round(usage.free / 1024**3, 2),
        "used_percent": round((usage.used / usage.total) * 100, 2) if usage.total else None,
    }


def memory_snapshot():
    data = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            data[key] = int(value.strip().split()[0]) // 1024
    except Exception as exc:
        data["error"] = str(exc)
    return {
        "mem_total_mb": data.get("MemTotal"),
        "mem_available_mb": data.get("MemAvailable"),
        "mem_free_mb": data.get("MemFree"),
        "swap_total_mb": data.get("SwapTotal"),
        "swap_free_mb": data.get("SwapFree"),
    }


def load_snapshot():
    try:
        return Path("/proc/loadavg").read_text().strip()
    except Exception as exc:
        return f"ERROR: {exc}"



def status_clean_or_only_phase30_reports(status_stdout):
    """Before committing Phase 30, phase30_reports can appear as untracked/modified."""
    lines = [line.strip() for line in str(status_stdout or "").splitlines() if line.strip()]
    if not lines:
        return True

    allowed_prefixes = [
        "?? phase30_reports/",
        "A  phase30_reports/",
        "AM phase30_reports/",
        "M  phase30_reports/",
        " M phase30_reports/",
    ]

    return all(any(line.startswith(prefix) for prefix in allowed_prefixes) for line in lines)


def current_branch_is_valid_for_phase30(branch):
    return branch in {
        "master",
        "testing/phase-30-production-readiness-final-report",
    }



def find_phase_result(phase):
    report_dir = APP_DIR / f"phase{phase}_reports"
    if not report_dir.exists():
        return {
            "phase": phase,
            "report_dir": str(report_dir),
            "exists": False,
            "passed": False,
            "result_files": [],
            "reason": "report directory missing",
        }

    candidates = []
    for pattern in ["*result*.txt", "*summary*.json", "*.txt"]:
        for path in report_dir.glob(pattern):
            if path.is_file() and path not in candidates:
                candidates.append(path)

    result_files = []
    passed = False
    review_required = False

    for path in candidates:
        text = safe_read(path)
        if "PASSED" in text:
            passed = True
        if "REVIEW_REQUIRED" in text:
            review_required = True

        if "PASSED" in text or "REVIEW_REQUIRED" in text or "Result" in text:
            result_files.append({
                "path": str(path.relative_to(APP_DIR)),
                "contains_passed": "PASSED" in text,
                "contains_review_required": "REVIEW_REQUIRED" in text,
                "tail": text[-2000:],
            })

    return {
        "phase": phase,
        "report_dir": str(report_dir.relative_to(APP_DIR)),
        "exists": True,
        "passed": passed and not review_required,
        "passed_present": passed,
        "review_required_present": review_required,
        "result_files": result_files,
    }


def latest_backup_files():
    backup_dir = BENCH / "sites" / SITE / "private" / "backups"
    if not backup_dir.exists():
        return []

    files = sorted(
        [p for p in backup_dir.glob("*") if p.is_file()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    return [
        {
            "name": p.name,
            "path": str(p),
            "size_mb": round(p.stat().st_size / 1024**2, 2),
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p.stat().st_mtime)),
        }
        for p in files[:8]
    ]


def get_agent_manifest_info():
    manifest_candidates = list((APP_DIR / "surhan_scanner/public/agent").glob("*manifest*")) if (APP_DIR / "surhan_scanner/public/agent").exists() else []
    manifests = []

    for path in manifest_candidates:
        if path.is_file():
            text = safe_read(path)
            manifests.append({
                "path": str(path.relative_to(APP_DIR)),
                "size": path.stat().st_size,
                "text_sample": text[:2000],
            })

    return {
        "agent_zip_exists": AGENT_ZIP.exists(),
        "agent_zip_path": str(AGENT_ZIP),
        "agent_zip_size_mb": round(AGENT_ZIP.stat().st_size / 1024**2, 2) if AGENT_ZIP.exists() else None,
        "manifest_candidates": manifests,
    }


def main():
    checks = []

    git_branch = run(["git", "branch", "--show-current"])
    git_status = run(["git", "status", "--short"])
    git_log = run(["git", "--no-pager", "log", "--oneline", "--decorate", "-12"])
    git_tag = run(["git", "tag", "--list", BASELINE_TAG])
    git_head = run(["git", "rev-parse", "--short", "HEAD"])

    checks.append(("git_branch_valid_for_phase30", current_branch_is_valid_for_phase30(git_branch["stdout"]), git_branch))
    checks.append(("git_worktree_clean_or_only_phase30_reports", status_clean_or_only_phase30_reports(git_status["stdout"]), git_status))
    checks.append(("baseline_tag_exists", git_tag["stdout"].strip() == BASELINE_TAG, git_tag))
    checks.append(("baseline_bundle_exists", BASELINE_BUNDLE.exists(), str(BASELINE_BUNDLE)))
    checks.append(("agent_zip_exists", AGENT_ZIP.exists(), str(AGENT_ZIP)))

    phase_results = [find_phase_result(p) for p in EXPECTED_PHASES]
    for item in phase_results:
        checks.append((f"phase_{item['phase']}_passed", item["passed"], item))

    bench_doctor = run(["bench", "doctor"], cwd=BENCH, timeout=180)
    checks.append(("bench_doctor_completed", bench_doctor["returncode"] == 0, bench_doctor))

    build_check = run(["bench", "build", "--app", "surhan_scanner"], cwd=BENCH, timeout=600)
    checks.append(("bench_build_surhan_scanner_success", build_check["returncode"] == 0, {
        "returncode": build_check["returncode"],
        "stdout_tail": build_check["stdout"][-3000:],
        "stderr_tail": build_check["stderr"][-3000:],
    }))

    disk = disk_snapshot()
    memory = memory_snapshot()
    loadavg = load_snapshot()
    latest_backups = latest_backup_files()
    agent_info = get_agent_manifest_info()

    checks.append(("disk_free_gb_at_least_5", (disk.get("free_gb") or 0) >= 5, disk))
    checks.append(("latest_backup_files_exist", len(latest_backups) >= 3, latest_backups))

    critical_passed = all(bool(x[1]) for x in checks)

    warnings = []

    if (memory.get("swap_free_mb") or 0) < 512:
        warnings.append("Swap free is below 512 MB; production host should monitor memory/swap under load.")

    if (memory.get("mem_available_mb") or 0) < 2048:
        warnings.append("Available memory is below 2 GB; production host should consider more RAM or reduced concurrency.")

    if disk.get("free_gb", 0) < 20:
        warnings.append("Disk free space is acceptable but should be monitored because scanner backups/private files can grow quickly.")

    warnings.append("Full destructive restore was intentionally not run on production-like site ysmo. Phase 29 verified backup readability and file/database inclusion without overwriting the active site.")

    readiness_status = "READY_FOR_PRODUCTION" if critical_passed else "NOT_READY_REVIEW_REQUIRED"

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "site": SITE,
        "readiness_status": readiness_status,
        "head_commit": git_head["stdout"],
        "git_branch": git_branch["stdout"],
        "git_clean": status_clean_or_only_phase30_reports(git_status["stdout"]),
        "baseline_tag": BASELINE_TAG,
        "baseline_bundle_exists": BASELINE_BUNDLE.exists(),
        "agent_info": agent_info,
        "disk": disk,
        "memory": memory,
        "loadavg": loadavg,
        "latest_backups": latest_backups,
        "phase_results": phase_results,
        "checks": checks,
        "warnings": warnings,
        "critical_passed": critical_passed,
    }

    FINAL_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    md = []
    md.append("# Surhan Scanner Production Readiness Final Report")
    md.append("")
    md.append(f"**Generated at:** {summary['generated_at']}")
    md.append(f"**Site:** `{SITE}`")
    md.append(f"**Final status:** `{readiness_status}`")
    md.append(f"**HEAD commit:** `{summary['head_commit']}`")
    md.append(f"**Branch:** `{summary['git_branch']}`")
    md.append(f"**Git clean:** `{summary['git_clean']}`")
    md.append("")
    md.append("## Executive Summary")
    md.append("")
    if readiness_status == "READY_FOR_PRODUCTION":
        md.append("Surhan Scanner passed the full hardening, security, upload, agent, storage, failure recovery, load, data integrity, and backup-readiness validation sequence from Phase 21 through Phase 29.")
        md.append("")
        md.append("The application is considered **READY FOR PRODUCTION** with the operational notes listed below.")
    else:
        md.append("Surhan Scanner is **NOT READY** until the failed checks below are reviewed and corrected.")
    md.append("")
    md.append("## Phase Results")
    md.append("")
    md.append("| Phase | Result | Evidence files |")
    md.append("|---:|---|---|")
    for item in phase_results:
        result = "PASSED" if item["passed"] else "REVIEW REQUIRED"
        files = "<br>".join([f"`{x['path']}`" for x in item.get("result_files", [])[:3]]) or "-"
        md.append(f"| {item['phase']} | {result} | {files} |")
    md.append("")
    md.append("## Final Technical Checks")
    md.append("")
    md.append("| Check | Result |")
    md.append("|---|---|")
    for name, ok, _detail in checks:
        md.append(f"| `{name}` | {'PASS' if ok else 'FAIL'} |")
    md.append("")
    md.append("## Current Runtime Snapshot")
    md.append("")
    md.append(f"- Disk: `{json.dumps(disk, ensure_ascii=False)}`")
    md.append(f"- Memory: `{json.dumps(memory, ensure_ascii=False)}`")
    md.append(f"- Load average: `{loadavg}`")
    md.append("")
    md.append("## Latest Backup Files")
    md.append("")
    for item in latest_backups:
        md.append(f"- `{item['name']}` — {item['size_mb']} MB — {item['mtime']}")
    md.append("")
    md.append("## Agent Package")
    md.append("")
    md.append(f"- Agent ZIP exists: `{agent_info['agent_zip_exists']}`")
    md.append(f"- Agent ZIP size: `{agent_info['agent_zip_size_mb']} MB`")
    md.append("")
    md.append("## Operational Notes")
    md.append("")
    for warning in warnings:
        md.append(f"- {warning}")
    md.append("")
    md.append("## Recommendation")
    md.append("")
    if readiness_status == "READY_FOR_PRODUCTION":
        md.append("Proceed to controlled production deployment, keeping backup monitoring, disk monitoring, worker monitoring, and scanner-agent rollout monitoring enabled.")
    else:
        md.append("Do not deploy until all failed checks are corrected and Phase 30 is rerun.")
    md.append("")

    FINAL_MD.write_text("\n".join(md), encoding="utf-8")

    txt = []
    txt.append("=== Phase 30 Production Readiness Final Report ===")
    txt.append("")
    txt.append(f"readiness_status={readiness_status}")
    txt.append(f"head_commit={summary['head_commit']}")
    txt.append(f"branch={summary['git_branch']}")
    txt.append(f"git_clean={summary['git_clean']}")
    txt.append("")
    txt.append("=== Checks ===")
    for name, ok, detail in checks:
        txt.append(json.dumps([name, bool(ok), detail], ensure_ascii=False, default=str))
    txt.append("")
    txt.append("=== Warnings ===")
    for warning in warnings:
        txt.append(f"- {warning}")
    txt.append("")
    txt.append("=== Reports ===")
    txt.append(f"markdown_report={FINAL_MD}")
    txt.append(f"json_summary={FINAL_JSON}")
    txt.append("")
    txt.append("=== Result ===")
    txt.append("PASSED" if critical_passed else "REVIEW_REQUIRED")

    FINAL_TXT.write_text("\n".join(txt), encoding="utf-8")

    print(FINAL_TXT.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
