"""
M01 - A.5.4 Tac dong len ca nhan/nhom.
Quy tac (MATRIX_v0.md dong 54): so hai chieu
  (1) ty le duoc ghep theo segment cua khach (A/B)
  (2) khoang cach trung binh theo vehicle_type cua tai xe (uoc luong qua
      vehicle_type cua chuyen di, vi results khong co vehicle_type cua
      driver da ghep - chi co cua ride; day la [Suy luan]).
Nguong chenh lech: 10% (chot G1), tinh theo chenh lech tuong doi
(max-min)/max. Day la mot co thong ke -> chi duoc day KHONG DAT/CAN NGUOI
XEM, khong tu ket luan DAT tuyet doi khi vuot nguong (nguyen tac bat doi
xung + Phan ML don gian trong MATRIX_v0.md).
"""
from common import make_result, ev, find_line_containing, load_json_file, cite_log_line

THRESHOLD = 0.10


def _group_stats(results, key):
    groups = {}
    for idx, r in enumerate(results):
        k = r.get(key)
        if k is None:
            continue
        groups.setdefault(k, []).append((idx, r))
    return groups


def check(ctx):
    rid = "M01"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]
    run = ctx["run"]

    audit_log.log(rid, "start", {"run_id": run.get("run_id")})

    report_path = run.get("report_path")
    if not report_path:
        n = audit_log.log(rid, "missing_report", {})
        return make_result(
            rid, "CẦN NGƯỜI XEM",
            [ev(ctx["audit_log"].path, n, commit)],
            "[Chưa xác minh] Không tìm thấy reports/product_run_<run_id>.json sau khi "
            "chạy `python product/run_product.py` lần kiểm fresh — thiếu bằng chứng, "
            "không thể tính tỷ lệ ghép theo segment / khoảng cách theo vehicle_type.",
        )

    data, text, lines = load_json_file(report_path)
    results = data.get("results", [])

    evidence = []
    notes = []

    # (1) ty le ghep theo segment
    seg_groups = _group_stats(results, "customer_segment")
    seg_rates = {}
    for seg, rows in seg_groups.items():
        matched = sum(1 for _, r in rows if r.get("driver_id") is not None)
        total = len(rows)
        seg_rates[seg] = (matched / total if total else 0.0, matched, total)

    seg_flag = False
    if len(seg_rates) >= 2:
        best_seg = max(seg_rates, key=lambda s: seg_rates[s][0])
        worst_seg = min(seg_rates, key=lambda s: seg_rates[s][0])
        best_rate = seg_rates[best_seg][0]
        worst_rate = seg_rates[worst_seg][0]
        rel_diff = (best_rate - worst_rate) / best_rate if best_rate > 0 else 0.0
        if rel_diff >= THRESHOLD:
            seg_flag = True
            # trich 1 dong vi du moi nhom lam bang chung
            for seg, rows in ((best_seg, seg_groups[best_seg]), (worst_seg, seg_groups[worst_seg])):
                idx, r = rows[0]
                needle = f'"ride_id": "{r.get("ride_id")}"' if r.get("ride_id") else None
                ln = find_line_containing(lines, needle) if needle else None
                if ln:
                    raw = lines[ln - 1]
                    evidence.extend(cite_log_line(
                        audit_log, rid, commit, report_path, ln, raw,
                        run.get("run_id"), run.get("cmd"), {"group": "customer_segment", "value": seg},
                    ))
            notes.append(
                f"[Suy luận] Tỷ lệ ghép theo customer_segment: {seg_rates}. "
                f"Chênh lệch tương đối giữa '{best_seg}' và '{worst_seg}' = {rel_diff:.2%} >= ngưỡng {THRESHOLD:.0%}."
            )
        else:
            notes.append(
                f"Tỷ lệ ghép theo customer_segment trong ngưỡng: {seg_rates} (chênh lệch {rel_diff:.2%} < {THRESHOLD:.0%})."
            )
    else:
        notes.append(
            f"[Chưa xác minh] Không đủ >=2 nhóm customer_segment có dữ liệu để so sánh (tìm thấy {len(seg_rates)})."
        )

    # (2) khoang cach trung binh theo vehicle_type (chi tinh tren chuyen da ghep)
    matched_rows = [(i, r) for i, r in enumerate(results) if r.get("driver_id") is not None]
    vt_groups = _group_stats([r for _, r in matched_rows], "vehicle_type")
    vt_means = {}
    for vt, rows in vt_groups.items():
        dists = [r.get("distance_km") for _, r in rows if isinstance(r.get("distance_km"), (int, float))]
        if dists:
            vt_means[vt] = (sum(dists) / len(dists), len(dists))

    vt_flag = False
    if len(vt_means) >= 2:
        best_vt = max(vt_means, key=lambda v: vt_means[v][0])
        worst_vt = min(vt_means, key=lambda v: vt_means[v][0])
        best_mean = vt_means[best_vt][0]
        worst_mean = vt_means[worst_vt][0]
        rel_diff2 = (best_mean - worst_mean) / best_mean if best_mean > 0 else 0.0
        if rel_diff2 >= THRESHOLD:
            vt_flag = True
            for vt, rows in vt_groups.items():
                if vt in (best_vt, worst_vt):
                    idx, r = rows[0]
                    needle = f'"ride_id": "{r.get("ride_id")}"' if r.get("ride_id") else None
                    ln = find_line_containing(lines, needle) if needle else None
                    if ln:
                        raw = lines[ln - 1]
                        evidence.extend(cite_log_line(
                            audit_log, rid, commit, report_path, ln, raw,
                            run.get("run_id"), run.get("cmd"), {"group": "vehicle_type", "value": vt},
                        ))
            notes.append(
                f"[Suy luận] Khoảng cách trung bình (distance_km) theo vehicle_type của chuyến đã ghép: "
                f"{ {k: round(v[0],3) for k,v in vt_means.items()} }. "
                f"Chênh lệch tương đối giữa '{best_vt}' và '{worst_vt}' = {rel_diff2:.2%} >= ngưỡng {THRESHOLD:.0%}. "
                f"[Chưa xác minh] vehicle_type ở đây lấy từ trường vehicle_type của ride (yêu cầu matching), "
                f"không phải vehicle_type thực của driver đã ghép — INTERFACE.md không trả field đó trong results."
            )
        else:
            notes.append(
                f"Khoảng cách trung bình theo vehicle_type trong ngưỡng (chênh lệch {rel_diff2:.2%} < {THRESHOLD:.0%})."
            )
    else:
        notes.append(
            f"[Chưa xác minh] Không đủ >=2 nhóm vehicle_type có chuyến đã ghép để so sánh (tìm thấy {len(vt_means)})."
        )

    for n in notes:
        audit_log.log(rid, "note", {"text": n})
    n = audit_log.log(rid, "done", {"seg_flag": seg_flag, "vt_flag": vt_flag})
    evidence.append(ev(audit_log.path, n, commit))

    if seg_flag or vt_flag:
        status = "CẦN NGƯỜI XEM"
        note = (
            "Cờ thống kê (M01 + phần ML trong MATRIX_v0.md) vượt ngưỡng 10% — cần người xem xét "
            "ý nghĩa thực tế (tương quan không chắc là nguyên nhân). " + " ".join(notes)
        )
    else:
        status = "ĐẠT"
        note = (
            f"Đã quét toàn bộ {len(results)} dòng results trong {report_path} (phương pháp: nhóm theo "
            f"customer_segment và vehicle_type, so chênh lệch tương đối, ngưỡng 10%). " + " ".join(notes)
        )

    return make_result(rid, status, evidence, note)
