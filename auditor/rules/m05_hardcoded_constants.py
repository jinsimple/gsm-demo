"""
M05 - A.6.2.3 Tai lieu thiet ke.
Quy tac: Hang so so hoc nghiep vu trong code khong co trong config.

Phuong phap (AST): quet product/matching.py va product/pricing.py, lay
moi ast.Constant kieu int/float (loai bool, loai {-1,0,1,2} vi thuong la
chi so/buoc lap/trivial), roi doi chieu voi tap gia tri so (duyet de quy)
lay tu product/config/matching.json, pricing.json, mock_data.json.
Hang so khong khop bat ky gia tri config nao -> flag "co kha nang hardcode".

Day la heuristic (co the trung voi gia tri config ngau nhien, hoac la
chi so mang khong phai hang so nghiep vu) -> ket qua toi da CAN NGUOI XEM,
khong tu ket luan KHONG DAT.
"""
import ast
from common import make_result, ev, parse_ast, repo_path

CODE_FILES = [
    ("product/matching.py", repo_path("product", "matching.py")),
    ("product/pricing.py", repo_path("product", "pricing.py")),
]
CONFIG_FILES = [
    repo_path("product", "config", "matching.json"),
    repo_path("product", "config", "pricing.json"),
    repo_path("product", "config", "mock_data.json"),
]
TRIVIAL = {-1, 0, 1, 2}


def _flatten_numbers(obj, out):
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _flatten_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _flatten_numbers(v, out)


def check(ctx):
    rid = "M05"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]
    import json

    config_numbers = set()
    config_scanned = []
    config_missing = []
    for p in CONFIG_FILES:
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            _flatten_numbers(data, config_numbers)
            config_scanned.append(p)
        except Exception as e:
            config_missing.append((p, str(e)))
            audit_log.log(rid, "config_error", {"file": p, "error": str(e)})

    evidence = []
    findings = []
    parse_errors = []

    for label, path in CODE_FILES:
        tree, src_lines, err = parse_ast(path)
        audit_log.log(rid, "parse", {"file": label, "error": err})
        if err or tree is None:
            parse_errors.append((label, err))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                val = node.value
                if val in TRIVIAL:
                    continue
                matched = any(
                    (val == cv) or (isinstance(val, float) and abs(val - cv) < 1e-9)
                    for cv in config_numbers
                )
                if not matched:
                    findings.append((label, path, node.lineno, val))

    for label, path, lineno, val in findings:
        evidence.append(ev(path, lineno, commit))
        audit_log.log(rid, "const_not_in_config", {"file": label, "line": lineno, "value": val})

    n_sum = audit_log.log(
        rid, "scan_summary",
        {
            "code_files": [l for l, _ in CODE_FILES], "config_scanned": config_scanned,
            "config_missing": config_missing, "n_config_numbers": len(config_numbers), "n_findings": len(findings),
            "parse_errors": parse_errors,
        },
    )
    evidence.append(ev(audit_log.path, n_sum, commit))

    if parse_errors:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"[Chưa xác minh] Không phân tích được bằng ast.parse: {parse_errors}. Không đủ bằng chứng.",
        )

    if config_missing:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"[Chưa xác minh] Không đọc được config để đối chiếu: {config_missing}.",
        )

    if findings:
        detail = "; ".join(f"{l}:{ln} = {v!r}" for l, _, ln, v in findings[:20])
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"ast.parse product/matching.py + product/pricing.py: {len(findings)} hằng số numeric (ngoài "
            f"{sorted(TRIVIAL)}) không khớp bất kỳ giá trị nào trong matching.json/pricing.json/mock_data.json: "
            f"{detail}{' ...' if len(findings) > 20 else ''}. Heuristic — có thể là chỉ số/độ dài hợp lệ, "
            f"cần người xem từng dòng để xác nhận có phải hằng số nghiệp vụ hay không.",
        )

    return make_result(
        rid, "ĐẠT", evidence,
        f"Quét toàn bộ ast.Constant numeric trong product/matching.py và product/pricing.py (loại trừ "
        f"{sorted(TRIVIAL)}), đối chiếu với {len(config_numbers)} giá trị số lấy từ "
        f"product/config/{{matching,pricing,mock_data}}.json: không có hằng số nào nằm ngoài config.",
    )
