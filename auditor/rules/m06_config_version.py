"""
M06 - A.6.2.7 Tai lieu ky thuat.
Quy tac: File config thieu truong "version".

Day la phat hien dang VANG MAT. Theo MATRIX_v0.md: bang chung = pham vi
da quet (liet du cac file / khoa da kiem) + phuong phap quet + dong log
cua agent kiem thu. Chi ra KHONG DAT khi quet day du ca 3 file config
(matching.json, pricing.json, mock_data.json, theo INTERFACE.md muc 3).
"""
import json
from common import make_result, ev, repo_path

CONFIG_FILES = [
    ("product/config/matching.json", repo_path("product", "config", "matching.json")),
    ("product/config/pricing.json", repo_path("product", "config", "pricing.json")),
    ("product/config/mock_data.json", repo_path("product", "config", "mock_data.json")),
]


def check(ctx):
    rid = "M06"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]

    evidence = []
    missing = []
    ok = []
    load_errors = []

    for label, path in CONFIG_FILES:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            load_errors.append((label, str(e)))
            audit_log.log(rid, "load_error", {"file": label, "error": str(e)})
            continue
        has_version = isinstance(data, dict) and isinstance(data.get("version"), str) and data.get("version").strip() != ""
        audit_log.log(rid, "checked", {"file": label, "has_version": has_version, "version": data.get("version") if isinstance(data, dict) else None})
        # bang chung: file:1 the hien "da quet toan bo file" (vangmat khong
        # co dong cu the de tro vao)
        evidence.append(ev(path, 1, commit))
        if has_version:
            ok.append(label)
        else:
            missing.append(label)

    n_sum = audit_log.log(
        rid, "scan_summary",
        {"checked": [l for l, _ in CONFIG_FILES], "ok": ok, "missing_version": missing, "load_errors": load_errors},
    )
    evidence.append(ev(audit_log.path, n_sum, commit))

    if load_errors:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"[Chưa xác minh] Không đọc được: {load_errors}. Chưa quét đầy đủ cả 3 file config nên không thể "
            f"kết luận KHÔNG ĐẠT dứt khoát.",
        )

    if missing:
        return make_result(
            rid, "KHÔNG ĐẠT", evidence,
            f"Quét đầy đủ cả {len(CONFIG_FILES)} file config theo INTERFACE.md §3 (matching.json, pricing.json, "
            f"mock_data.json). Thiếu trường 'version' (chuỗi không rỗng) ở: {missing}. Có version hợp lệ: {ok}.",
        )

    return make_result(
        rid, "ĐẠT", evidence,
        f"Quét đầy đủ cả {len(CONFIG_FILES)} file config theo INTERFACE.md §3; cả 3 đều có trường 'version' "
        f"dạng chuỗi không rỗng: {ok}.",
    )
