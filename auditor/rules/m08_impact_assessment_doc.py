"""
M08 - A.5.2 Quy trinh danh gia tac dong.
Quy tac: Khong co tai lieu danh gia tac dong trong docs/.

coder-auditor BI CAM mo noi dung nhieu file trong docs/ (DECISIONS,
TASKS, SPEC_A, GREEN_SM_CONTEXT, PROMPTS, CHECKLIST_KIEM_TOAN - theo quy
tac doi). Vi vay quy tac nay CHI liet ke TEN FILE (os.walk, khong mo noi
dung) trong docs/ va doi chieu voi tu khoa ten file goi y tai lieu danh
gia tac dong (DPIA / impact assessment / danh gia tac dong). Day la quet
VANG MAT nhung CHUA DAY DU (chi o muc ten file, khong doc duoc noi dung
vi bi cam) -> theo nguyen tac bat doi xung, KHONG tu ket luan KHONG DAT;
toi da CAN NGUOI XEM.
"""
import os
import re
import unicodedata
from common import make_result, ev, repo_path

DOCS_DIR = repo_path("docs")

NAME_PATTERNS = [
    re.compile(r"dpia", re.IGNORECASE),
    re.compile(r"impact[_\s-]*assess", re.IGNORECASE),
    re.compile(r"danh[_\s-]*gia[_\s-]*tac[_\s-]*dong", re.IGNORECASE),
    re.compile(r"risk[_\s-]*assess", re.IGNORECASE),
]


def _strip_accents(s):
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def check(ctx):
    rid = "M08"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]

    all_files = []
    for root, dirs, files in os.walk(DOCS_DIR):
        for fn in files:
            p = os.path.join(root, fn)
            all_files.append(p)

    audit_log.log(rid, "listing", {"n_files": len(all_files), "files": [os.path.relpath(p, DOCS_DIR) for p in all_files]})

    matches = []
    for p in all_files:
        fn = os.path.basename(p)
        norm = _strip_accents(fn)
        if any(pat.search(fn) or pat.search(norm) for pat in NAME_PATTERNS):
            matches.append(p)

    evidence = []
    for p in matches:
        evidence.append(ev(p, 1, commit))
        audit_log.log(rid, "name_match", {"file": os.path.relpath(p, DOCS_DIR)})

    n_sum = audit_log.log(
        rid, "scan_summary",
        {
            "n_files_listed": len(all_files), "n_name_matches": len(matches),
            "method": "os.walk liệt kê TÊN FILE trong docs/, so khớp regex trên tên file (không đọc nội dung "
                      "vì coder-auditor bị cấm mở nhiều file trong docs/ theo CLAUDE.md)",
        },
    )
    evidence.append(ev(audit_log.path, n_sum, commit))

    if matches:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"Tìm thấy {len(matches)} file có TÊN gợi ý tài liệu đánh giá tác động: "
            f"{[os.path.relpath(p, DOCS_DIR) for p in matches]}. Agent kiểm thử KHÔNG được mở nội dung các file "
            f"này (ngoài MATRIX_v0.md/INTERFACE.md) để xác minh có đúng là đánh giá tác động hay không — cần "
            f"người xem xét nội dung.",
        )

    return make_result(
        rid, "CẦN NGƯỜI XEM", evidence,
        f"Liệt kê toàn bộ {len(all_files)} tên file trong docs/ (os.walk, không đọc nội dung — coder-auditor bị "
        f"cấm mở phần lớn file trong docs/ theo quy tắc đội). Không có tên file khớp các từ khoá "
        f"DPIA/impact assessment/đánh giá tác động/risk assessment. [Chưa xác minh] Đây là quét VẮNG MẶT chỉ ở "
        f"mức TÊN FILE, không phải nội dung đầy đủ — theo MATRIX_v0.md, phát hiện vắng mặt chỉ ra KHÔNG ĐẠT khi "
        f"quét đầy đủ; ở đây phạm vi quét bị giới hạn do ràng buộc nội bộ của agent kiểm thử nên KHÔNG tự suy ra "
        f"KHÔNG ĐẠT, giữ ở CẦN NGƯỜI XEM.",
    )
