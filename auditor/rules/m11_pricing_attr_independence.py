"""
M11 - A.5.4 (pricing).
Quy tac: Gia phu thuoc thuoc tinh cua khach ngoai quang duong va thoi
diem. fare(distance_km, requested_at, config, logger=None) theo
INTERFACE.md chi nhan 2 thuoc tinh dau vao nghiep vu: distance_km,
requested_at.

Phan AST: quet product/pricing.py tim dau hieu doc du lieu khach ngoai
2 tham so cho phep - import/open/doc customers.json, hoac dinh danh
chua "segment"/"customer" (ca-insensitive, regex tren source text -
STATIC, khong phai doc hieu noi dung nghiep vu).

Phan thong ke (Phan ML don gian trong MATRIX_v0.md + chi dan rieng cho
M11 trong "Chi tiet quy tac" cua MATRIX_v0.md): chia chuyen theo phan vi
quantiles(distance_km, n=4) thanh 4 nhom quang duong tuong duong, trong
TUNG nhom so gia trung binh (fare_vnd) giua cac customer_segment, chenh
lech tuong doi >= 10% o bat ky nhom nao -> co thong ke.

Co thong ke CHI duoc day ket qua len CAN NGUOI XEM/KHONG DAT, khong bao
gio ha xuong DAT (chot MATRIX_v0.md).
"""
import ast
import re
import statistics
from common import make_result, ev, parse_ast, find_functions, load_json_file, repo_path

THRESHOLD = 0.10
SEGMENT_KEYWORD = re.compile(r"segment|customer", re.IGNORECASE)


def check(ctx):
    rid = "M11"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]
    run = ctx["run"]

    path = repo_path("product", "pricing.py")
    evidence = []

    # --- AST: cac tham so thuc te cua fare() ---
    tree, src_lines, err = parse_ast(path)
    audit_log.log(rid, "parse", {"file": "product/pricing.py", "error": err})
    param_issue = None
    if err or tree is None:
        param_issue = f"[Chưa xác minh] Không phân tích được product/pricing.py bằng ast.parse: {err}"
    else:
        fns = find_functions(tree, "fare")
        if not fns:
            param_issue = "[Chưa xác minh] Không tìm thấy hàm fare() trong product/pricing.py qua ast."
        else:
            fn = fns[0]
            arg_names = [a.arg for a in fn.args.args] + [a.arg for a in fn.args.kwonlyargs]
            allowed = {"distance_km", "requested_at", "config", "logger", "self"}
            extra = [a for a in arg_names if a not in allowed]
            if extra:
                evidence.append(ev(path, fn.lineno, commit))
                audit_log.log(rid, "extra_params", {"line": fn.lineno, "params": extra})
                param_issue = f"Hàm fare() nhận thêm tham số ngoài hợp đồng INTERFACE.md: {extra} (dòng {fn.lineno})."

    # --- quet tinh: dau hieu truy cap du lieu khach trong pricing.py ---
    keyword_hits = []
    io_hits = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for i, line in enumerate(lines, start=1):
            if SEGMENT_KEYWORD.search(line):
                keyword_hits.append(i)
    except FileNotFoundError:
        lines = []

    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fname = None
                if isinstance(node.func, ast.Name):
                    fname = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    fname = node.func.attr
                if fname in ("open", "load", "loads") :
                    io_hits.append(node.lineno)

    for ln in keyword_hits:
        evidence.append(ev(path, ln, commit))
        audit_log.log(rid, "keyword_hit", {"line": ln})
    for ln in io_hits:
        evidence.append(ev(path, ln, commit))
        audit_log.log(rid, "io_call", {"line": ln})

    code_flag = bool(keyword_hits) or bool(io_hits) or (param_issue is not None and "nhận thêm tham số" in (param_issue or ""))

    # --- thong ke theo quantile quang duong ---
    stat_flag = False
    stat_notes = []
    report_path = run.get("report_path")
    if report_path:
        data, text, rlines = load_json_file(report_path)
        results = data.get("results", [])
        dists = [r.get("distance_km") for r in results if isinstance(r.get("distance_km"), (int, float))]
        if len(dists) >= 8:
            try:
                qs = statistics.quantiles(dists, n=4)
            except Exception:
                qs = []
            if qs:
                def bucket(d):
                    for bi, q in enumerate(qs):
                        if d <= q:
                            return bi
                    return len(qs)

                buckets = {}
                for r in results:
                    d = r.get("distance_km")
                    seg = r.get("customer_segment")
                    fare = r.get("fare_vnd")
                    if not isinstance(d, (int, float)) or seg is None or not isinstance(fare, (int, float)):
                        continue
                    b = bucket(d)
                    buckets.setdefault(b, {}).setdefault(seg, []).append(fare)

                for b, seg_map in sorted(buckets.items()):
                    means = {seg: (sum(v) / len(v), len(v)) for seg, v in seg_map.items() if v}
                    if len(means) >= 2:
                        best = max(means, key=lambda s: means[s][0])
                        worst = min(means, key=lambda s: means[s][0])
                        bm, wm = means[best][0], means[worst][0]
                        rel = (bm - wm) / bm if bm > 0 else 0.0
                        if rel >= THRESHOLD:
                            stat_flag = True
                            stat_notes.append(
                                f"[Suy luận] Nhóm quãng đường #{b}: giá trung bình theo segment {means} — "
                                f"chênh lệch '{best}' vs '{worst}' = {rel:.2%} >= {THRESHOLD:.0%}."
                            )
                audit_log.log(rid, "quantile_stats", {"n_buckets": len(buckets), "stat_flag": stat_flag})
            else:
                stat_notes.append("[Chưa xác minh] Không tính được quantiles (statistics.quantiles lỗi hoặc rỗng).")
        else:
            stat_notes.append(f"[Chưa xác minh] Chỉ có {len(dists)} chuyến có distance_km hợp lệ — không đủ dữ liệu chia 4 nhóm phân vị đáng tin cậy.")
    else:
        stat_notes.append("[Chưa xác minh] Không có reports/product_run_<run_id>.json từ lần chạy fresh để thống kê.")

    n_sum = audit_log.log(
        rid, "scan_summary",
        {"param_issue": param_issue, "code_flag": code_flag, "stat_flag": stat_flag, "n_keyword_hits": len(keyword_hits), "n_io_hits": len(io_hits)},
    )
    evidence.append(ev(audit_log.path, n_sum, commit))

    if code_flag:
        return make_result(
            rid, "KHÔNG ĐẠT", evidence,
            f"ast.parse + quét regex product/pricing.py: {param_issue or ''} "
            f"Từ khoá segment/customer xuất hiện ở dòng {keyword_hits}; lời gọi open/load/loads ở dòng {io_hits}. "
            f"Đây là bằng chứng mã nguồn (không phải chỉ thống kê), cho thấy pricing có khả năng đọc dữ liệu/thuộc "
            f"tính khách ngoài distance_km, requested_at.",
        )

    if stat_flag:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            "Không tìm thấy dấu hiệu mã nguồn đọc thuộc tính khách ngoài hợp đồng (ast + regex sạch), nhưng cờ "
            "thống kê theo nhóm phân vị quãng đường (statistics.quantiles, n=4) vượt ngưỡng 10%: " + " ".join(stat_notes) +
            " Cờ thống kê không được dùng để tự kết luận KHÔNG ĐẠT (MATRIX_v0.md) — cần người xem xét.",
        )

    return make_result(
        rid, "ĐẠT", evidence,
        f"ast.parse fare() trong product/pricing.py: tham số đúng hợp đồng INTERFACE.md "
        f"(distance_km, requested_at, config, logger). Quét regex toàn file không thấy từ khoá "
        f"segment/customer, không có lời gọi open/load/loads. " + " ".join(stat_notes),
    )
