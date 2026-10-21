"""
M07 - A.9.2 Su dung co trach nhiem.
Quy tac: Co hanh dong bat loi hoac rang buoc len tai xe (khoa, phat, ha
uu tien, tu dong nhan chuyen) ma KHONG co buoc/co nguoi xem xet.

Phuong phap: AST + log. match() tra ve `auto_accept: bool` (INTERFACE.md
muc 2) - day la mot hanh dong rang buoc ro rang (tu dong nhan chuyen thay
tai xe). Quet toan bo product/ (ast cho .py, regex cho ten dinh danh) tim
dau hieu "con nguoi xem xet" (human/review/manual/approve/override...).

Day la phat hien hop: mot phan tinh (auto_accept co that, trich dong AST)
+ mot phan vang mat (khong thay co/buoc review). Theo nguyen tac bat doi
xung va vi Mechanism/Effect de trong cho nguoi (chi Anh) dien, ket qua
CHI o muc CAN NGUOI XEM (khong tu ket luan KHONG DAT mot phat hien can
dien giai y nghia nghiep vu/phap ly).
"""
import ast
import re
from common import make_result, ev, parse_ast, read_jsonl, repo_path, cite_log_line

REVIEW_KEYWORDS = re.compile(r"human|review|manual|approve|override|xac_nhan|phe_duyet|nguoi_xem|nguoi_duyet", re.IGNORECASE)

PY_FILES = [
    ("product/matching.py", repo_path("product", "matching.py")),
    ("product/pricing.py", repo_path("product", "pricing.py")),
    ("product/run_product.py", repo_path("product", "run_product.py")),
    ("product/logger.py", repo_path("product", "logger.py")),
    ("product/data/gen_mock.py", repo_path("product", "data", "gen_mock.py")),
]
CONFIG_FILES = [
    ("product/config/matching.json", repo_path("product", "config", "matching.json")),
    ("product/config/pricing.json", repo_path("product", "config", "pricing.json")),
]


def check(ctx):
    rid = "M07"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]
    run = ctx["run"]

    evidence = []

    # 1) tim noi auto_accept duoc gan trong matching.py (AST)
    auto_accept_assigns = []
    path = repo_path("product", "matching.py")
    tree, src_lines, err = parse_ast(path)
    audit_log.log(rid, "parse", {"file": "product/matching.py", "error": err})
    if tree is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "auto_accept":
                        auto_accept_assigns.append(node.lineno)
            if isinstance(node, ast.Dict):
                for k in node.keys:
                    if isinstance(k, ast.Constant) and k.value == "auto_accept":
                        auto_accept_assigns.append(node.lineno)

    for ln in sorted(set(auto_accept_assigns)):
        evidence.append(ev(path, ln, commit))
        audit_log.log(rid, "auto_accept_assignment", {"line": ln})

    # 2) tim bang chung dong: log that su co dong auto_accept=True trong
    # lan chay fresh
    mlog = read_jsonl(run["log_paths"].get("matching"))
    n_auto_true = 0
    sample_log_ev = []
    for it in mlog:
        obj = it["obj"]
        if obj and obj.get("event") == "match_result":
            dec_outputs = obj.get("outputs") or {}
            if dec_outputs.get("auto_accept") is True:
                n_auto_true += 1
                if len(sample_log_ev) < 3:
                    sample_log_ev.append(it)
    for it in sample_log_ev:
        evidence.extend(cite_log_line(
            audit_log, rid, commit, run["log_paths"]["matching"], it["line"], it["raw"],
            run.get("run_id"), run.get("cmd"), {"check": "auto_accept_true"},
        ))
    audit_log.log(rid, "auto_accept_runtime_count", {"n_auto_accept_true": n_auto_true, "run_id": run.get("run_id")})

    # 3) quet toan bo product/ tim dau hieu "nguoi xem xet"
    review_hits = []
    scanned_files = []
    for label, p in PY_FILES + CONFIG_FILES:
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            continue
        scanned_files.append(label)
        for i, line in enumerate(lines, start=1):
            if REVIEW_KEYWORDS.search(line):
                review_hits.append((label, p, i))

    for label, p, i in review_hits:
        evidence.append(ev(p, i, commit))
        audit_log.log(rid, "review_keyword_hit", {"file": label, "line": i})

    n_sum = audit_log.log(
        rid, "scan_summary",
        {
            "scanned_files": scanned_files, "n_auto_accept_assigns": len(set(auto_accept_assigns)),
            "n_auto_accept_true_runtime": n_auto_true, "n_review_hits": len(review_hits),
        },
    )
    evidence.append(ev(audit_log.path, n_sum, commit))

    has_adverse_action = bool(auto_accept_assigns) or n_auto_true > 0
    has_review_mechanism = len(review_hits) > 0

    if not has_adverse_action:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"[Chưa xác minh] Không xác định được qua AST nơi auto_accept được gán trong matching.py, và log "
            f"fresh (run_id={run.get('run_id')}) không có match_result với outputs.auto_accept=true. Không đủ "
            f"bằng chứng để xác nhận có/không hành động ràng buộc tự động.",
        )

    if has_review_mechanism:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"auto_accept (hành động tự động nhận chuyến) có thật: gán ở dòng {sorted(set(auto_accept_assigns))} "
            f"của matching.py, {n_auto_true} quyết định auto_accept=true trong lần chạy fresh run_id="
            f"{run.get('run_id')}. Quét product/ bằng regex tìm thấy {len(review_hits)} chỗ có từ khoá liên "
            f"quan 'review/human/manual/approve/override' — cần người xem có phải là bước xem xét con người "
            f"thực sự hay chỉ trùng từ khoá.",
        )

    return make_result(
        rid, "CẦN NGƯỜI XEM", evidence,
        f"auto_accept (hành động tự động nhận chuyến, ràng buộc trực tiếp lên tài xế) có thật: gán ở dòng "
        f"{sorted(set(auto_accept_assigns))} của matching.py, {n_auto_true} quyết định auto_accept=true trong "
        f"lần chạy fresh run_id={run.get('run_id')}. Quét toàn bộ {scanned_files} bằng regex "
        f"({REVIEW_KEYWORDS.pattern}) KHÔNG tìm thấy dấu hiệu bước/cờ con người xem xét. Theo nguyên tắc bất "
        f"đối xứng và vì cột Mechanism/Effect để trống cho người điền (§ chốt G1), kết luận mức độ 'bất lợi' cần "
        f"người xem xét, không tự quy KHÔNG ĐẠT dứt khoát từ một quét tĩnh/động đơn lẻ.",
    )
