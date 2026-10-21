"""
M04 - A.6.2.8 Log su kien.
Quy tac: So quyet dinh != so quyet dinh co log; hoac co nhanh `return`
khong goi log.

Dinh nghia "mot quyet dinh" lay dung theo INTERFACE.md muc 5.4 (khong tu
dat rieng): decision != null CHI o event match_result (module matching)
va fare_result (module pricing). 1 chuyen = 2 quyet dinh. Ky vong = so ban
ghi rides.json x 2.

Phan dong: doc logs/matching_<run_id>.jsonl va logs/pricing_<run_id>.jsonl
(B tu chay fresh), dem so dong co decision != null va event dung ten, va
kiem reason khong rong (yeu cau cua chinh dinh nghia quyet dinh).

Phan tinh (AST): trong than ham match()/fare() cua matching.py/pricing.py,
voi moi `return`, tim nguoc trong cung block (va cac block cha truc tiep
tren duong code) mot loi goi <name>.log(...) truoc do. Day la heuristic -
khong chung minh duoc coverage runtime tuyet doi -> neu nghi ngo, CAN
NGUOI XEM, khong tu KHONG DAT.
"""
import ast
from common import make_result, ev, parse_ast, find_functions, read_jsonl, repo_path, load_json_file, cite_log_line


def _contains_log_call(stmts):
    """True neu trong list cau lenh (cung 1 block) co loi goi .log(...)."""
    for s in stmts:
        for node in ast.walk(s):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "log":
                return True
    return False


def _returns_without_preceding_log(func_node):
    """Heuristic: voi moi Return node, xet cac cau lenh truoc no trong CUNG
    body (list) chua no truc tiep; neu khong co loi goi log nao truoc do
    trong body hien tai va khong co trong than ham (toan cuc) truoc dong
    return -> flag."""
    flagged = []
    all_calls_before = {}  # lineno return -> bool co log truoc do trong toan than ham

    # Thu thap moi statement bac cao nhat theo thu tu duyet (gan dung bang
    # cach dung lineno) de kiem tra "co log truoc do trong ham".
    log_call_lines = []
    return_lines = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "log":
            log_call_lines.append(node.lineno)
        if isinstance(node, ast.Return):
            return_lines.append(node.lineno)

    log_call_lines.sort()
    for rln in return_lines:
        has_log_before = any(ll <= rln for ll in log_call_lines)
        if not has_log_before:
            flagged.append(rln)
    return flagged, log_call_lines, return_lines


def _check_file(audit_log, rid, rel_label, path, func_name):
    tree, src_lines, err = parse_ast(path)
    audit_log.log(rid, "parse", {"file": rel_label, "error": err})
    if err or tree is None:
        return None, f"[Chưa xác minh] Không phân tích được {rel_label}: {err}"
    funcs = find_functions(tree, func_name)
    if not funcs:
        return None, f"[Chưa xác minh] Không tìm thấy hàm {func_name}() trong {rel_label} qua ast."
    results = []
    for fn in funcs:
        flagged, log_lines, return_lines = _returns_without_preceding_log(fn)
        results.append({"func_lineno": fn.lineno, "flagged_returns": flagged, "n_log_calls": len(log_lines), "n_returns": len(return_lines)})
    return results, None


def check(ctx):
    rid = "M04"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]
    run = ctx["run"]

    evidence = []
    notes = []
    static_flag = False

    matching_path = repo_path("product", "matching.py")
    pricing_path = repo_path("product", "pricing.py")

    m_res, m_err = _check_file(audit_log, rid, "product/matching.py", matching_path, "match")
    p_res, p_err = _check_file(audit_log, rid, "product/pricing.py", pricing_path, "fare")

    for label, res, err, path in (("match", m_res, m_err, matching_path), ("fare", p_res, p_err, pricing_path)):
        if err:
            notes.append(err)
            continue
        for r in res:
            if r["flagged_returns"]:
                static_flag = True
                for rln in r["flagged_returns"]:
                    evidence.append(ev(path, rln, commit))
                notes.append(
                    f"[Chưa xác minh] Hàm {label}() tại dòng {r['func_lineno']}: return ở dòng "
                    f"{r['flagged_returns']} không thấy lời gọi .log(...) nào trước đó trong cùng hàm "
                    f"(heuristic theo số dòng, không phải control-flow graph thật)."
                )

    # Phan dong: dem quyet dinh thuc te trong log
    mlog = read_jsonl(run["log_paths"].get("matching"))
    plog = read_jsonl(run["log_paths"].get("pricing"))

    audit_log.log(rid, "log_files", {"matching": run["log_paths"].get("matching"), "pricing": run["log_paths"].get("pricing")})

    if run.get("returncode") not in (0,) or (not mlog and not plog):
        n = audit_log.log(rid, "run_incomplete", {"returncode": run.get("returncode")})
        evidence.append(ev(audit_log.path, n, commit))
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"[Chưa xác minh] Lần chạy fresh `python product/run_product.py` không sinh được log matching/pricing "
            f"đầy đủ (returncode={run.get('returncode')}). Không đủ bằng chứng để đối chiếu số quyết định. " + " ".join(notes),
        )

    match_decisions = [it for it in mlog if it["obj"] and it["obj"].get("event") == "match_result" and it["obj"].get("decision") is not None]
    fare_decisions = [it for it in plog if it["obj"] and it["obj"].get("event") == "fare_result" and it["obj"].get("decision") is not None]

    empty_reason = []
    for it in match_decisions + fare_decisions:
        if not str(it["obj"].get("reason") or "").strip():
            empty_reason.append(it)

    rides_path = repo_path("product", "data", "rides.json")
    try:
        rides_data, _, _ = load_json_file(rides_path)
        n_rides = len(rides_data)
    except Exception as e:
        n_rides = None
        audit_log.log(rid, "rides_load_error", {"error": str(e)})

    expected = n_rides * 2 if n_rides is not None else None
    actual = len(match_decisions) + len(fare_decisions)

    for it in empty_reason[:10]:
        src_path = run["log_paths"]["matching" if it["obj"].get("event") == "match_result" else "pricing"]
        evidence.extend(cite_log_line(
            audit_log, rid, commit, src_path, it["line"], it["raw"],
            run.get("run_id"), run.get("cmd"), {"reason_check": "empty_reason"},
        ))

    n_sum = audit_log.log(
        rid, "decision_count",
        {
            "n_rides": n_rides, "expected": expected, "n_match_decisions": len(match_decisions),
            "n_fare_decisions": len(fare_decisions), "actual_total": actual, "n_empty_reason": len(empty_reason),
        },
    )
    evidence.append(ev(audit_log.path, n_sum, commit))

    mismatch = expected is not None and actual != expected

    if mismatch or empty_reason:
        detail = []
        if mismatch:
            detail.append(f"kỳ vọng {expected} quyết định (n_rides={n_rides} x 2) nhưng log có {actual} "
                           f"(match_result={len(match_decisions)}, fare_result={len(fare_decisions)})")
        if empty_reason:
            detail.append(f"{len(empty_reason)} dòng quyết định có reason rỗng")
        return make_result(
            rid, "KHÔNG ĐẠT", evidence,
            "Đối chiếu log sau khi tự chạy fresh product/run_product.py: " + "; ".join(detail) + ". " + " ".join(notes),
        )

    if static_flag:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"Đối chiếu số lượng khớp (log có đủ {actual}/{expected} quyết định, reason không rỗng), "
            f"nhưng AST heuristic tìm thấy return nghi ngờ thiếu log trước đó. " + " ".join(notes),
        )

    return make_result(
        rid, "ĐẠT", evidence,
        f"Tự chạy fresh `python product/run_product.py` (run_id={run.get('run_id')}), đọc toàn bộ "
        f"logs/matching_*.jsonl và logs/pricing_*.jsonl: {actual}/{expected} quyết định khớp số lượng kỳ vọng "
        f"(n_rides={n_rides} x 2), mọi reason không rỗng. AST heuristic trên match()/fare() không thấy "
        f"return thiếu log.",
    )
