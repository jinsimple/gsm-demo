"""
M02 - A.7.4 Chat luong du lieu.
Quy tac: product/matching.py doc thuoc tinh KHONG nam trong danh sach cho
phep o INTERFACE.md muc 7 (10 thuoc tinh: ride.vehicle_type, ride.pickup_lat,
ride.pickup_lon, driver.status, driver.vehicle_type, driver.lat, driver.lon,
driver.trips_today, driver.acceptance_rate, driver.driver_id).

Phuong phap: phan tich tinh bang ast.parse (KHONG doc code bang mat).
Heuristic theo doi bien:
  - ride_vars: seed = {"ride"} (ten tham so co dinh theo chu ky ham trong
    INTERFACE.md `match(ride, drivers, config, logger=None)`), cong moi
    bien duoc gan truc tiep tu mot ten trong ride_vars (alias don gian).
  - driver_vars: seed = moi bien dich (target) trong vong `for X in drivers`
    (drivers la tham so co dinh), cong alias don gian, cong fallback: bien
    co ten chua "driver" (khong phan biet hoa/thuong) duoc dung nhu mot
    dict (bi subscript/.get).
Bat ky Subscript[string] hoac .get("...") tren cac bien nay voi khoa KHONG
nam trong danh sach cho phep -> flag.
Cac truy cap dong (getattr, **ride, ride.items()/.keys()/.values(),
vars(ride)) khong the xac minh day du bang AST tinh -> CAN NGUOI XEM rieng,
khong tu suy ra DAT.
"""
import ast
from common import make_result, ev, parse_ast, RIDE_ALLOWED, DRIVER_ALLOWED, repo_path

TARGET_FILE = "matching.py"


def _const_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _base_name(node):
    """Lay ten Name goc cua mot Subscript/Attribute value, neu co."""
    if isinstance(node, ast.Name):
        return node.id
    return None


def check(ctx):
    rid = "M02"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]
    path = repo_path("product", TARGET_FILE)

    tree, src_lines, err = parse_ast(path)
    n0 = audit_log.log(rid, "parse", {"file": TARGET_FILE, "error": err})
    if err or tree is None:
        return make_result(
            rid, "CẦN NGƯỜI XEM",
            [ev(audit_log.path, n0, commit)],
            f"[Chưa xác minh] Không phân tích được {TARGET_FILE} bằng ast.parse: {err}",
        )

    ride_vars = {"ride"}
    driver_vars = set()

    # Pass 1: seed driver_vars tu for-loop lap tren bien ten "drivers"
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            it = node.iter
            if isinstance(it, ast.Name) and it.id == "drivers":
                if isinstance(node.target, ast.Name):
                    driver_vars.add(node.target.id)

    # Pass 2: alias don gian "x = ride" / "x = <bien driver da biet>" , lap
    # vai lan de bat chuoi alias ngan.
    for _ in range(3):
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                tgt = node.targets[0]
                if isinstance(tgt, ast.Name) and isinstance(node.value, ast.Name):
                    src_name = node.value.id
                    if src_name in ride_vars:
                        ride_vars.add(tgt.id)
                    if src_name in driver_vars:
                        driver_vars.add(tgt.id)

    # Fallback heuristic: bien co ten chua "driver" (ca-insensitive) coi la
    # driver_vars de khong bo sot (nguyen tac bat doi xung: nghi ngo -> xet).
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and "driver" in node.id.lower() and node.id != "drivers":
            driver_vars.add(node.id)

    findings = []       # (lineno, var, key, obj_kind)
    dynamic_hits = []    # (lineno, mo ta) - truy cap dong khong xac minh duoc

    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            base = _base_name(node.value)
            key = None
            sl = node.slice
            # py3.9+: slice la truc tiep node (khong Index wrapper)
            key = _const_str(sl)
            if base and key is not None:
                if base in ride_vars and key not in RIDE_ALLOWED:
                    findings.append((node.lineno, base, key, "ride"))
                elif base in driver_vars and key not in DRIVER_ALLOWED:
                    findings.append((node.lineno, base, key, "driver"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            base = _base_name(node.func.value)
            if attr == "get" and base and node.args:
                key = _const_str(node.args[0])
                if key is not None:
                    if base in ride_vars and key not in RIDE_ALLOWED:
                        findings.append((node.lineno, base, key, "ride"))
                    elif base in driver_vars and key not in DRIVER_ALLOWED:
                        findings.append((node.lineno, base, key, "driver"))
            elif attr in ("items", "keys", "values") and base in (ride_vars | driver_vars):
                dynamic_hits.append((node.lineno, f"{base}.{attr}() - duyet dong, AST tinh khong liet ke het khoa"))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if node.args and _base_name(node.args[0]) in (ride_vars | driver_vars):
                dynamic_hits.append((node.lineno, "getattr(...) tren bien ride/driver - truy cap dong"))

    evidence = []
    for lineno, base, key, kind in findings:
        evidence.append(ev(path, lineno, commit))
        audit_log.log(rid, "forbidden_attr", {"line": lineno, "var": base, "key": key, "kind": kind})

    for lineno, desc in dynamic_hits:
        audit_log.log(rid, "dynamic_access", {"line": lineno, "desc": desc})

    n_scan = audit_log.log(
        rid, "scan_summary",
        {
            "file": TARGET_FILE, "ride_vars": sorted(ride_vars), "driver_vars": sorted(driver_vars),
            "n_findings": len(findings), "n_dynamic": len(dynamic_hits),
        },
    )
    evidence.append(ev(audit_log.path, n_scan, commit))

    if findings:
        detail = "; ".join(f"{base}['{key}'] (dòng {lineno}, nhóm {kind})" for lineno, base, key, kind in findings)
        return make_result(
            rid, "KHÔNG ĐẠT", evidence,
            f"ast.parse product/matching.py: phát hiện {len(findings)} truy cập thuộc tính ngoài danh sách "
            f"cho phép ở INTERFACE.md §7: {detail}. Biến ride={sorted(ride_vars)}, driver={sorted(driver_vars)}.",
        )

    if dynamic_hits:
        detail = "; ".join(f"dòng {ln}: {d}" for ln, d in dynamic_hits)
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"Không tìm thấy truy cập Subscript/.get() sai phép, nhưng có {len(dynamic_hits)} truy cập động "
            f"(getattr/.items()/.keys()/.values()) mà AST tĩnh không liệt kê hết được khóa thực tế: {detail}. "
            f"Theo nguyên tắc bất đối xứng, không suy ra ĐẠT khi còn truy cập không xác minh được.",
        )

    return make_result(
        rid, "ĐẠT", evidence,
        f"Quét toàn bộ product/matching.py bằng ast.parse (mọi Subscript[string] và .get(\"...\") trên biến "
        f"suy ra là ride={sorted(ride_vars)} hoặc driver={sorted(driver_vars)}); không có truy cập nằm ngoài "
        f"danh sách cho phép ở INTERFACE.md §7, và không có truy cập động không xác minh được.",
    )
