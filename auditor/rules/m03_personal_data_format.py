"""
M03 - A.7.5 Nguon goc du lieu.
Quy tac: Mock data co truong mang dinh dang du lieu ca nhan thuc (SDT,
email, CCCD...). Phuong phap: quet regex tren toan bo noi dung text cua
cac file trong product/data/*.json (drivers.json, customers.json,
rides.json) va product/config/mock_data.json.

Day la quet dinh dang (regex), khong xac minh du lieu la "thuc" hay
"tong hop" - chi bao dinh dang giong du lieu ca nhan thuc, theo dung
pham vi cot "Quy tac kiem bang may" cua M03.
"""
import re
from common import make_result, ev, repo_path

FILES = [
    ("product/data/drivers.json", repo_path("product", "data", "drivers.json")),
    ("product/data/customers.json", repo_path("product", "data", "customers.json")),
    ("product/data/rides.json", repo_path("product", "data", "rides.json")),
    ("product/config/mock_data.json", repo_path("product", "config", "mock_data.json")),
]

PATTERNS = {
    "phone_vn": re.compile(r"(?<!\d)(0|\+?84)(\d[\s.-]?){8,10}\d(?!\d)"),
    "email": re.compile(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9-.]+"),
    "cccd_12_digit": re.compile(r"(?<!\d)\d{12}(?!\d)"),
    "cmnd_9_digit": re.compile(r"(?<!\d)\d{9}(?!\d)"),
}

# Nhung key ki thuat thuong co so 9-12 chu so lien tiep nhung khong phai
# du lieu ca nhan (vi du id_format, seed...) - khong loai tru tu dong,
# chi ghi chu trong note de nguoi xem xet doi chieu; khong tu ha ket qua.


def check(ctx):
    rid = "M03"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]

    evidence = []
    findings = []
    scanned = []
    missing = []

    for label, path in FILES:
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except FileNotFoundError:
            missing.append(label)
            audit_log.log(rid, "file_missing", {"file": label})
            continue
        scanned.append((label, path, len(lines)))
        for i, line in enumerate(lines, start=1):
            for pname, pat in PATTERNS.items():
                for m in pat.finditer(line):
                    findings.append((label, path, i, pname, m.group(0)))

    for label, path, i, pname, sample in findings:
        evidence.append(ev(path, i, commit))
        audit_log.log(rid, "pattern_hit", {"file": label, "line": i, "pattern": pname, "sample": sample})

    n_scan = audit_log.log(
        rid, "scan_summary",
        {"scanned": [{"file": l, "n_lines": n} for l, _, n in scanned], "missing": missing, "n_findings": len(findings)},
    )
    evidence.append(ev(audit_log.path, n_scan, commit))

    if missing:
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            f"[Chưa xác minh] Thiếu file để quét: {missing}. Không đủ phạm vi quét đầy đủ product/data/*.json.",
        )

    if findings:
        detail = "; ".join(f"{label}:{i} ({pname}: {sample!r})" for label, _, i, pname, sample in findings[:20])
        return make_result(
            rid, "KHÔNG ĐẠT", evidence,
            f"Quét regex toàn bộ {len(scanned)} file ({[l for l,_,_ in scanned]}): phát hiện "
            f"{len(findings)} chuỗi khớp định dạng dữ liệu cá nhân (SĐT/email/CCCD/CMND): {detail}"
            f"{' ...' if len(findings) > 20 else ''}. [Chưa xác minh] Có thể là số ngẫu nhiên trùng định dạng "
            f"(id_format, seed, toạ độ) — cần người xem xét từng dòng.",
        )

    return make_result(
        rid, "ĐẠT", evidence,
        f"Quét regex toàn bộ {len(scanned)} file trong product/data/ và product/config/mock_data.json "
        f"({[f'{l} ({n} dòng)' for l, _, n in scanned]}), patterns: {list(PATTERNS.keys())}. "
        f"Không tìm thấy chuỗi khớp định dạng SĐT/email/CCCD/CMND.",
    )
