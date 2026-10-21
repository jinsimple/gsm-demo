"""
auditor/run_audit.py

Chay toan bo 12 quy tac M01..M12 cua agent kiem thu B va xuat:
  reports/audit_<commit>.json
  reports/audit_<commit>.md
  reports/audit_<commit>.log.jsonl   (log cua chinh B, duoc commit)

Nguon duy nhat cho logic kiem: docs/MATRIX_v0.md + docs/INTERFACE.md.
CHI dung Python standard library.

Chay: python auditor/run_audit.py
"""
import datetime
import importlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import common  # noqa: E402

RULE_MODULES = [
    "m01_group_impact",
    "m02_allowed_attrs",
    "m03_personal_data_format",
    "m04_decision_log_coverage",
    "m05_hardcoded_constants",
    "m06_config_version",
    "m07_adverse_action_review",
    "m08_impact_assessment_doc",
    "m09_reason_present",
    "m10_repeat_stability",
    "m11_pricing_attr_independence",
    "m12_auto_accept_alert",
]


def load_matrix():
    with open(common.repo_path("auditor", "matrix.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    commit = common.get_commit()
    audit_run_id = common.make_audit_run_id()
    audit_log_path = common.repo_path("reports", f"audit_{commit}.log.jsonl")
    audit_log = common.AuditLog(audit_log_path, audit_run_id)

    matrix = load_matrix()
    matrix_by_id = {row["id"]: row for row in matrix["rows"]}

    audit_log.log("RUN", "audit_start", {"commit": commit})

    print(f"[audit] commit={commit} audit_run_id={audit_run_id}")
    print("[audit] chay fresh: python product/run_product.py ...")
    run = common.run_product_once()
    audit_log.log("RUN", "primary_product_run", {
        "run_id": run.get("run_id"), "returncode": run.get("returncode"), "report_path": run.get("report_path"),
    })
    print(f"[audit] product run_id={run.get('run_id')} returncode={run.get('returncode')}")
    if run.get("returncode") != 0:
        print(f"[audit] STDERR product:\n{run.get('stderr')}")

    ctx = {
        "commit": commit,
        "audit_log": audit_log,
        "run": run,
        "run_product_fn": common.run_product_once,
    }

    sys.path.insert(0, common.repo_path("auditor", "rules"))

    rows_out = []
    for mod_name in RULE_MODULES:
        rid = mod_name[:3].upper()
        try:
            mod = importlib.import_module(mod_name)
            res = mod.check(ctx)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            n = audit_log.log(rid, "rule_exception", {"error": str(e), "traceback": tb})
            res = common.make_result(
                rid, "CẦN NGƯỜI XEM",
                [common.ev(audit_log_path, n, commit)],
                f"[Chưa xác minh] Quy tắc {rid} ({mod_name}) lỗi khi chạy: {e}",
            )
        matrix_row = matrix_by_id.get(rid, {})
        rows_out.append({
            "id": rid,
            "control": matrix_row.get("control", ""),
            "law": matrix_row.get("law", ""),
            "rule": matrix_row.get("rule", ""),
            "result": res["result"],
            "evidence": res["evidence"],
            "note": res["note"],
            "mechanism": matrix_row.get("mechanism", ""),
            "effect": matrix_row.get("effect", ""),
        })
        print(f"[audit] {rid}: {res['result']} ({len(res['evidence'])} bằng chứng)")

    report = {
        "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "run_id": audit_run_id,
        "commit": commit,
        "product_run_id": run.get("run_id"),
        "schema_version": "0.1",
        "note": "[Suy luận] Bao cao agent kiem thu B, sinh boi auditor/run_audit.py tu docs/MATRIX_v0.md + docs/INTERFACE.md.",
        "rows": rows_out,
    }

    audit_log.log("RUN", "audit_end", {"n_rows": len(rows_out)})
    audit_log.close()

    out_json = common.repo_path("reports", f"audit_{commit}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    out_md = common.repo_path("reports", f"audit_{commit}.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(f"# Báo cáo kiểm thử B — commit `{commit}`\n\n")
        f.write(f"- ts: {report['ts']}\n")
        f.write(f"- audit_run_id: {audit_run_id}\n")
        f.write(f"- product run_id: {run.get('run_id')}\n\n")
        f.write("| ID | Control | Luật | Kết quả | Bằng chứng | Ghi chú | Mechanism | Effect |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for row in rows_out:
            ev_str = "<br>".join(row["evidence"]) if row["evidence"] else "(không có)"
            note = row["note"].replace("|", "\\|").replace("\n", " ")
            rule = row["rule"].replace("|", "\\|")
            f.write(
                f"| {row['id']} | {row['control']} | {row['law']} | {row['result']} | {ev_str} | {note} | "
                f"{row['mechanism']} | {row['effect']} |\n"
            )

    print(f"[audit] xuất {out_json}")
    print(f"[audit] xuất {out_md}")
    print(f"[audit] log B: {audit_log_path}")
    print(f"[audit] tổng {len(rows_out)} dòng")
    return 0


if __name__ == "__main__":
    sys.exit(main())
