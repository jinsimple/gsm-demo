"""
M09 - A.8.2 Thong tin cho nguoi dung.
Quy tac: Quyet dinh khong kem reason doc duoc.

Dinh nghia "quyet dinh" theo INTERFACE.md 5.4: decision != null CHI o
event match_result (module matching) va fare_result (module pricing).
reason phai la chuoi khong rong o MOI event quyet dinh (INTERFACE.md 5.2
truong 9, va 5.4).

Phuong phap: doc toan bo logs/matching_<run_id>.jsonl va
logs/pricing_<run_id>.jsonl tu lan chay fresh, kiem tung dong quyet dinh.
"""
from common import make_result, ev, read_jsonl, cite_log_line


def check(ctx):
    rid = "M09"
    commit = ctx["commit"]
    audit_log = ctx["audit_log"]
    run = ctx["run"]

    evidence = []

    mpath = run["log_paths"].get("matching")
    ppath = run["log_paths"].get("pricing")
    mlog = read_jsonl(mpath)
    plog = read_jsonl(ppath)

    audit_log.log(rid, "log_files", {"matching": mpath, "pricing": ppath, "n_matching_lines": len(mlog), "n_pricing_lines": len(plog)})

    if not mpath or not ppath or (not mlog and not plog):
        n = audit_log.log(rid, "missing_logs", {})
        evidence.append(ev(audit_log.path, n, commit))
        return make_result(
            rid, "CẦN NGƯỜI XEM", evidence,
            "[Chưa xác minh] Không đọc được logs/matching_*.jsonl và/hoặc logs/pricing_*.jsonl từ lần chạy fresh "
            "— thiếu bằng chứng để kiểm trường reason.",
        )

    bad = []
    n_decisions = 0
    for path, log in ((mpath, mlog), (ppath, plog)):
        for it in log:
            obj = it["obj"]
            if obj is None:
                continue
            if obj.get("event") in ("match_result", "fare_result") and obj.get("decision") is not None:
                n_decisions += 1
                reason = obj.get("reason")
                if not isinstance(reason, str) or not reason.strip():
                    bad.append((path, it, reason))

    for path, it, reason in bad[:30]:
        evidence.extend(cite_log_line(
            audit_log, rid, commit, path, it["line"], it["raw"],
            run.get("run_id"), run.get("cmd"), {"reason": reason},
        ))

    n_sum = audit_log.log(rid, "scan_summary", {"n_decisions": n_decisions, "n_empty_reason": len(bad), "run_id": run.get("run_id")})
    evidence.append(ev(audit_log.path, n_sum, commit))

    if bad:
        return make_result(
            rid, "KHÔNG ĐẠT", evidence,
            f"Đọc toàn bộ {len(mlog)} dòng {mpath} và {len(plog)} dòng {ppath} (run_id={run.get('run_id')}), "
            f"xét {n_decisions} dòng quyết định (event match_result/fare_result, decision != null theo "
            f"INTERFACE.md 5.4): {len(bad)} dòng có reason rỗng hoặc không phải chuỗi.",
        )

    return make_result(
        rid, "ĐẠT", evidence,
        f"Đọc toàn bộ {len(mlog)} dòng {mpath} và {len(plog)} dòng {ppath} (run_id={run.get('run_id')}), "
        f"xét đủ {n_decisions} dòng quyết định (match_result/fare_result): mọi reason là chuỗi không rỗng.",
    )
