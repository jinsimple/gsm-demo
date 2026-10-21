"""
auditor/common.py
Ha tang chung cho cac quy tac M01..M12 cua agent kiem thu B.

CHI dung Python standard library.
B KHONG doc product/*.py bang mat; moi truy cap product/ o day la truy cap
bang chuong trinh (ast, regex, doc file JSON/JSONL, chay lap lai san pham).
"""
from __future__ import annotations

import ast
import glob
import json
import os
import re
import subprocess
import sys
import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RIDE_ALLOWED = {"vehicle_type", "pickup_lat", "pickup_lon"}
DRIVER_ALLOWED = {
    "status", "vehicle_type", "lat", "lon",
    "trips_today", "acceptance_rate", "driver_id",
}
PRICING_ALLOWED_PARAMS = {"distance_km", "requested_at"}

VOLATILE_REPORT_KEYS = {"ts", "run_id", "log_files"}
VOLATILE_LOG_FIELDS = {"ts", "run_id"}

MATCH_DECISION_EVENT = "match_result"
FARE_DECISION_EVENT = "fare_result"


def repo_path(*parts):
    return os.path.join(REPO_ROOT, *parts)


def rel(path):
    return os.path.relpath(path, REPO_ROOT).replace("\\", "/")


def get_commit():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


_tracked_cache = {}


def is_git_tracked(path):
    r = rel(path)
    if r in _tracked_cache:
        return _tracked_cache[r]
    try:
        out = subprocess.run(
            ["git", "ls-files", "--error-unmatch", r],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
        )
        tracked = out.returncode == 0
    except Exception:
        tracked = False
    _tracked_cache[r] = tracked
    return tracked


def ev(path, line, commit):
    """Tao mot phan tu evidence 'file:dong@commit'. File khong nam trong git
    (vi du logs/*.jsonl, reports/product_run_*.json) thi KHONG co @commit,
    theo ngoai le duy nhat chot trong MATRIX_v0.md."""
    r = rel(path)
    if is_git_tracked(path):
        return f"{r}:{line}@{commit}"
    return f"{r}:{line}"


def cite_log_line(audit_log, rid, commit, source_path, line_no, raw, run_id, cmd, extra=None):
    """Khi trich MOT dong log/report san pham lam bang chung: chep NGUYEN
    VAN dong do vao reports/audit_<commit>.log.jsonl (duoc commit), kem
    run_id da sinh va lenh da chay (chot MATRIX_v0.md dong 15-18). Can vi
    logs/*.jsonl va reports/product_run_*.json KHONG vao git (.gitignore)
    nen neu chi tro vao do, bang chung da commit se khong tai lap duoc
    sau khi file bien mat.

    Tra ve list 2 evidence: (1) dong goc trong file san pham (khong
    @commit - ngoai le duy nhat cua quy uoc file:dong@commit), (2) dong
    tuong ung trong audit log cua B (co @commit, duoc commit, tai lap
    duoc doc lap voi logs/ san pham)."""
    detail = {
        "source_file": rel(source_path),
        "source_line": line_no,
        "raw": raw,
        "run_id": run_id,
        "cmd": cmd,
    }
    if extra:
        detail.update(extra)
    n = audit_log.log(rid, "cite_log_line", detail)
    return [ev(source_path, line_no, commit), ev(audit_log.path, n, commit)]


def make_result(id_, status, evidence_list, note):
    assert status in ("ĐẠT", "KHÔNG ĐẠT", "CẦN NGƯỜI XEM"), status
    return {
        "id": id_,
        "result": status,
        "evidence": list(evidence_list),
        "note": note,
    }


# ---------------------------------------------------------------- file IO --

def load_json_file(path):
    """Tra ve (data, text, lines) hoac raise."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    data = json.loads(text)
    lines = text.split("\n")
    return data, text, lines


def try_load_json_file(path):
    try:
        return load_json_file(path)
    except Exception as e:
        return None, None, None


def find_line_containing(lines, needle):
    if not lines:
        return None
    for i, l in enumerate(lines, start=1):
        if needle in l:
            return i
    return None


def read_jsonl(path):
    """Doc file JSON Lines, tra ve list cac dict {line, raw, obj}.
    obj=None neu dong do khong parse duoc JSON (van giu raw)."""
    items = []
    if not path or not os.path.exists(path):
        return items
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            raw = line.rstrip("\n")
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                obj = None
            items.append({"line": i, "raw": raw, "obj": obj})
    return items


# ----------------------------------------------------------------- AST ----

def parse_ast(path):
    """Tra ve (tree, src_lines, error). error la None neu thanh cong."""
    if not os.path.exists(path):
        return None, None, f"file khong ton tai: {rel(path)}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    except Exception as e:
        return None, None, f"loi doc file {rel(path)}: {e}"
    try:
        tree = ast.parse(src, filename=path)
    except SyntaxError as e:
        return None, src.split("\n"), f"loi cu phap {rel(path)}: {e}"
    return tree, src.split("\n"), None


def find_functions(tree, name):
    """Tra ve list cac ast.FunctionDef co ten `name` trong toan bo module
    (moi cap do, ke ca long trong class)."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            out.append(node)
    return out


# ------------------------------------------------------- chay product/ ----

def run_product_once(timeout=180):
    """Chay fresh `python product/run_product.py`, tra ve dict mo ta ket qua
    cua MOT lan chay: run_id, report_path, log_paths (dict module->path),
    returncode, stdout, stderr, cmd.
    B tu chay de sinh log moi, khong dung log cu (chot MATRIX_v0)."""
    logs_dir = repo_path("logs")
    reports_dir = repo_path("reports")
    os.makedirs(logs_dir, exist_ok=True)
    before_logs = set(glob.glob(os.path.join(logs_dir, "*.jsonl")))
    before_reports = set(glob.glob(os.path.join(reports_dir, "product_run_*.json")))

    cmd = [sys.executable, repo_path("product", "run_product.py")]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=env,
        )
        returncode, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
        run_error = None
    except Exception as e:
        returncode, stdout, stderr = -1, "", ""
        run_error = str(e)

    after_logs = set(glob.glob(os.path.join(logs_dir, "*.jsonl")))
    after_reports = set(glob.glob(os.path.join(reports_dir, "product_run_*.json")))
    new_logs = sorted(after_logs - before_logs)
    new_reports = sorted(after_reports - before_reports)

    report_path = None
    if new_reports:
        report_path = max(new_reports, key=os.path.getmtime)
    run_id = None
    if report_path:
        m = re.search(r"product_run_([0-9A-Za-z]+)\.json$", os.path.basename(report_path))
        if m:
            run_id = m.group(1)

    log_paths = {}
    for p in new_logs:
        bn = os.path.basename(p)
        m = re.match(r"^([a-z_]+)_([0-9A-Za-z]+)\.jsonl$", bn)
        if m:
            log_paths[m.group(1)] = p

    return {
        "cmd": " ".join(cmd),
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "run_error": run_error,
        "run_id": run_id,
        "report_path": report_path,
        "log_paths": log_paths,
    }


def strip_volatile(obj):
    """Bo cac truong de bien dong (ts, run_id, log_files, duong dan log)
    truoc khi so sanh ket qua 2 lan chay khac nhau. Xem INTERFACE.md muc 6."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in VOLATILE_REPORT_KEYS:
                continue
            out[k] = strip_volatile(v)
        return out
    if isinstance(obj, list):
        return [strip_volatile(x) for x in obj]
    return obj


# ------------------------------------------------------------- AuditLog ---

class AuditLog:
    """Log JSONL cua chinh agent kiem thu B. Ghi vao
    reports/audit_<commit>.log.jsonl (duoc commit, khac logs/ san pham)."""

    def __init__(self, path, run_id):
        self.path = path
        self.run_id = run_id
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._f = open(path, "w", encoding="utf-8")
        self._n = 0

    def log(self, rule_id, event, detail=None):
        self._n += 1
        rec = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "audit_run_id": self.run_id,
            "rule_id": rule_id,
            "event": event,
            "detail": detail if detail is not None else {},
        }
        self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._f.flush()
        return self._n  # so thu tu dong (1-based) trong file nay

    def line_no(self):
        return self._n

    def close(self):
        self._f.close()


def make_audit_run_id():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3]
