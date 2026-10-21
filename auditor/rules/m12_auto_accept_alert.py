"""
M12 - A.6.2.6 Van hanh & giam sat.
Quy tac: Khong co nguong canh bao cho ty le auto_accept.

Phat hien dang VANG MAT. Phuong phap: doc het khoa cua ca 3 file config
(matching.json, pricing.json, mock_data.json - theo INTERFACE.md muc 3)
tim khoa goi y "canh bao"/"alert"/"threshold" GAN voi ty le auto_accept
tong hop (khac voi `auto_accept_threshold` la nguong QUYET DINH tung
chuyen, khong phai nguong CANH BAO tren ty le tong hop); va quet regex
toan bo cac file .py trong product/ tim tu khoa alert/warn/canh_bao gan
voi auto_accept/n_auto_accept.

Quet day du (toan bo file da liet ke trong INTERFACE.md) -> neu khong
thay gi, ket qua KHONG DAT theo quy uoc vang-mat-quet-day-du cua
MATRIX_v0.md.
"""
import json
import re
from common import make_result, ev, repo_path

CONFIG_FILES = [
    ("product/config/matching.json", repo_path("product", "config", "matching.json")),
    ("product/config/pricing.json", repo_path("product", "config", "pricing.json")),
    ("product/config/mock_data.json", repo_path("product", "config", "mock_data.json")),
]
PY_FILES = [
    ("product/matching.py", repo_path("product", "matching.py")),
    ("product/pricing.py", repo_path("product", "pricing.py")),
    ("product/run_product.py", repo_path("product", "run_product.py")),
    ("product/logger.py", repo_path("product", "logger.py")),
    ("product/data/gen_mock.py", repo_path("product", "data", "gen_mock.py")),
]

ALERT_KEYWORD = re.compile(r"alert|canh_?bao|warn(?!ing_mode)", re.IGNORECASE)
AUTO_ACCEPT_KEYWORD = re.compile(r"auto_accept", re.IGNORECASE)


def _flatten_keys(obj, prefix, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.append(f"{prefix}.{k}" if prefix else k)
            _flatten_keys(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _flatten_keys(v, f"{prefix}[{i}]", out)


def check(ctx):
    rid = "M12"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]

    evidence = []
    config_keys_by_file = {}
    load_errors = []
    for label, path in CONFIG_FILES:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            load_errors.append((label, str(e)))
            audit_log.log(rid, "config_load_error", {"file": label, "error": str(e)})
            continue
        keys = []
        _flatten_keys(data, "", keys)
        config_keys_by_file[label] = keys
        evidence.append(ev(path, 1, commit))

    alert_key_hits = []
    for label, keys in config_keys_by_file.items():
        for k in keys:
            if ALERT_KEYWORD.search(k) and AUTO_ACCEPT_KEYWORD.search(k):
                alert_key_hits.append((label, k))

    code_hits = []
    scanned_py = []
    for label, path in PY_FILES:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            continue
        scanned_py.append(label)
        for i, line in enumerate(lines, start=1):
            if ALERT_KEYWORD.search(line) and AUTO_ACCEPT_KEYWORD.search(line):
                code_hits.append((label, path, i))
            elif ALERT_KEYWORD.search(line):
                # tu khoa canh bao dung mot minh, khong gan auto_accept tren cung dong
                # - van ghi lai de nguoi xem, khong tinh la hit du dieu kien
                audit_log.log(rid, "alert_keyword_alone", {"file": label, "line": i})

    for label, path, i in code_hits:
        evidence.append(ev(path, i, commit))
        audit_log.log(rid, "alert_code_hit", {"file": label, "line": i})
    for label, k in alert_key_hits:
        audit_log.log(rid, "alert_config_key_hit", {"file": label, "key": k})

    n_sum = audit_log.log(
        rid, "scan_summary",
        {
            "config_scanned": list(config_keys_by_file.keys()), "load_errors": load_errors,
            "py_scanned": scanned_py, "n_alert_key_hits": len(alert_key_hits), "n_alert_code_hits": len(code_hits),
            "method": "liệt kê toàn bộ khoá config (đệ quy) + regex (alert|canh_bao|warn) kết hợp auto_accept trên "
                      "cùng dòng, toàn bộ .py trong INTERFACE.md",
        },
    )
    evidence.append(ev(audit_log.path, n_sum, commit))

    if load_errors:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"[Chưa xác minh] Không đọc được: {load_errors}. Chưa quét đầy đủ cả 3 file config.",
        )

    if alert_key_hits or code_hits:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"Tìm thấy dấu hiệu liên quan cảnh báo + auto_accept: config keys {alert_key_hits}, code "
            f"{[(l, i) for l, _, i in code_hits]}. Cần người xem có đúng là ngưỡng cảnh báo cho TỶ LỆ "
            f"auto_accept tổng hợp (khác với auto_accept_threshold — ngưỡng quyết định từng chuyến) hay không.",
        )

    return make_result(
        rid, "KHÔNG ĐẠT", evidence,
        f"Quét đầy đủ khoá của cả 3 file config ({list(config_keys_by_file.keys())}) và toàn bộ {len(scanned_py)} "
        f"file .py liệt kê trong INTERFACE.md ({scanned_py}): không có khoá config hay dòng code nào thể hiện "
        f"ngưỡng cảnh báo cho tỷ lệ auto_accept tổng hợp. Khoá 'auto_accept_threshold' trong matching.json chỉ là "
        f"ngưỡng quyết định từng chuyến (per-ride), không phải ngưỡng cảnh báo vận hành trên tỷ lệ tổng hợp "
        f"(summary.n_auto_accept / n_rides).",
    )
