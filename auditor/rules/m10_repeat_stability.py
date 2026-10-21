"""
M10 - A.6.2.4 Kiem chung & xac nhan.
Quy tac: Cung dau vao chay 3 lan -> ket qua khac nhau.

Phuong phap "chay lap": goi `python product/run_product.py` 3 lan (dung
cung config, cung product/data/*.json co san - khong sinh lai mock data
giua cac lan, vi do la "cung dau vao"). Moi lan sinh run_id/report/log
rieng. So sanh report sau khi bo cac truong de bien dong theo
INTERFACE.md muc 6 (ts, run_id, log_files, ten file). Khac nhau -> KHONG
DAT. Thieu du 3 ban de so -> CAN NGUOI XEM (khong tu KHONG DAT/DAT).
"""
import re
from common import make_result, ev, load_json_file, strip_volatile, find_line_containing, cite_log_line

_RESULT_IDX_RE = re.compile(r"\.results\[(\d+)\]")


def _diff_paths(a, b, path=""):
    """Tra ve list duong dan (dang chuoi) nơi a va b khac nhau, gioi han
    so luong de bang chung khong qua dai."""
    diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a.keys()) | set(b.keys())
        for k in sorted(keys, key=str):
            if k not in a or k not in b:
                diffs.append(f"{path}.{k} (thiếu ở một bên)")
                continue
            diffs.extend(_diff_paths(a[k], b[k], f"{path}.{k}"))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path} (độ dài khác: {len(a)} vs {len(b)})")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diffs.extend(_diff_paths(x, y, f"{path}[{i}]"))
    else:
        if a != b:
            diffs.append(f"{path}: {a!r} != {b!r}")
    return diffs


def check(ctx):
    rid = "M10"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]
    run_product_fn = ctx["run_product_fn"]

    runs = [ctx["run"]]  # lan 1 da chay o run_audit.py, tai su dung
    audit_log.log(rid, "reuse_primary_run", {"run_id": ctx["run"].get("run_id")})

    for i in (2, 3):
        r = run_product_fn()
        audit_log.log(rid, f"run_{i}", {"run_id": r.get("run_id"), "returncode": r.get("returncode")})
        runs.append(r)

    evidence = []
    reports = []
    for i, r in enumerate(runs, start=1):
        rp = r.get("report_path")
        if not rp:
            n = audit_log.log(rid, "run_missing_report", {"attempt": i, "run_id": r.get("run_id"), "returncode": r.get("returncode")})
            evidence.append(ev(audit_log.path, n, commit))
            return make_result(
                rid, "CẦN NGƯỜI XEM", evidence,
                f"[Chưa xác minh] Lần chạy thứ {i}/3 không sinh được reports/product_run_<run_id>.json "
                f"(returncode={r.get('returncode')}). Không đủ 3 bản để so sánh.",
            )
        data, text, lines = load_json_file(rp)
        reports.append({"run": r, "data": strip_volatile(data), "raw_data": data, "lines": lines, "path": rp})

    base = reports[0]["data"]
    all_diffs = []
    for other in reports[1:]:
        diffs = _diff_paths(base, other["data"])
        if diffs:
            all_diffs.append((other, diffs))

    n_sum = audit_log.log(
        rid, "compare_summary",
        {
            "run_ids": [r["run"].get("run_id") for r in reports],
            "n_diff_groups": len(all_diffs),
            "stripped_fields": sorted(["ts", "run_id", "log_files"]),
        },
    )
    evidence.append(ev(audit_log.path, n_sum, commit))

    if all_diffs:
        detail_parts = []
        for other, diffs in all_diffs:
            path = other["path"]
            lines = other["lines"]
            raw_results = other["raw_data"].get("results", [])
            run_id = other["run"].get("run_id")
            cmd = other["run"].get("cmd")
            for d in diffs[:10]:
                detail_parts.append(f"{path}: {d}")
                ln, raw = None, None
                m = _RESULT_IDX_RE.search(d)
                if m:
                    idx = int(m.group(1))
                    if 0 <= idx < len(raw_results):
                        ride_id = raw_results[idx].get("ride_id")
                        if ride_id:
                            needle = f'"ride_id": "{ride_id}"'
                            ln = find_line_containing(lines, needle)
                if ln is None:
                    ln = 1
                raw = lines[ln - 1] if lines and 0 <= ln - 1 < len(lines) else d
                evidence.extend(cite_log_line(
                    audit_log, rid, commit, path, ln, raw, run_id, cmd, {"diff_description": d},
                ))
        return make_result(
            rid, "KHÔNG ĐẠT", evidence,
            f"Chạy `python product/run_product.py` 3 lần với cùng product/data/*.json và config hiện có "
            f"(run_id={[r['run'].get('run_id') for r in reports]}). Sau khi bỏ các trường dễ biến động "
            f"(ts, run_id, log_files theo INTERFACE.md §6) và so sánh sâu các report, phát hiện khác biệt: "
            f"{'; '.join(detail_parts[:15])}{' ...' if len(detail_parts) > 15 else ''}.",
        )

    return make_result(
        rid, "ĐẠT", evidence,
        f"Chạy `python product/run_product.py` 3 lần với cùng product/data/*.json và config hiện có "
        f"(run_id={[r['run'].get('run_id') for r in reports]}). Sau khi bỏ ts/run_id/log_files "
        f"(INTERFACE.md §6) và so sánh sâu toàn bộ report (summary + results), 3 bản giống hệt nhau.",
    )
