"""Chay toan bo san pham mau A (SPEC_A §4).

Doc mock -> ghep tung chuyen -> tinh gia -> ghi reports/product_run_<run_id>.json + log.
Chay bang mot lenh: python product/run_product.py

Quang duong tinh gia = haversine(pickup -> dropoff), khong he so duong bo.
Chuyen khong ghep duoc tai xe VAN tinh gia, ket qua ghi driver_id: null.

[Suy luan] Sandbox mo phong, khong phai san pham that cua Green SM.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import matching  # noqa: E402
import pricing  # noqa: E402
from logger import (  # noqa: E402
    REPO_ROOT,
    JsonlLogger,
    enable_utf8_stdout,
    load_json_config,
    make_run_id,
    rel,
)

MODULE_NAME = "run_product"
DATA_DIR = os.path.join(_HERE, "data")
REPORTS_DIR = os.path.join(REPO_ROOT, "reports")
DRIVERS_PATH = os.path.join(DATA_DIR, "drivers.json")
CUSTOMERS_PATH = os.path.join(DATA_DIR, "customers.json")
RIDES_PATH = os.path.join(DATA_DIR, "rides.json")
MOCK_CONFIG_PATH = os.path.join(_HERE, "config", "mock_data.json")


def _read_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _sha256(path):
    """Bang chung lan chay nay dung dung file du lieu nao."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_mock_data(run_log, run_id):
    missing = [p for p in (DRIVERS_PATH, CUSTOMERS_PATH, RIDES_PATH) if not os.path.exists(p)]
    if not missing:
        run_log.log(
            func="_ensure_mock_data",
            event="mock_data_check",
            inputs={
                "checked_files": [
                    rel(p) for p in (DRIVERS_PATH, CUSTOMERS_PATH, RIDES_PATH)
                ]
            },
            outputs={"missing_files": [], "generated": False},
            decision=None,
            reason="mock_data_day_du_khong_sinh_lai",
        )
        return False
    run_log.log(
        func="_ensure_mock_data",
        event="mock_data_check",
        inputs={
            "checked_files": [
                rel(p) for p in (DRIVERS_PATH, CUSTOMERS_PATH, RIDES_PATH)
            ]
        },
        outputs={"missing_files": [rel(p) for p in missing], "generated": True},
        decision=None,
        reason="thieu_file_mock_nen_se_sinh_lai",
    )
    sys.path.insert(0, DATA_DIR)
    import gen_mock

    gen_mock.main(run_id=run_id)
    run_log.log(
        func="_ensure_mock_data",
        event="mock_data_generated",
        inputs={"missing_files": [rel(p) for p in missing]},
        outputs={"generated": True},
        decision=None,
        reason="thieu_file_mock_nen_sinh_lai_bang_gen_mock",
    )
    return True


def run(run_id=None):
    run_id = run_id or make_run_id()

    run_log = JsonlLogger(MODULE_NAME, run_id)
    match_log = JsonlLogger(matching.MODULE_NAME, run_id)
    price_log = JsonlLogger(pricing.MODULE_NAME, run_id)

    try:
        # Doc mock_data.json TRUOC run_start de dong log dau tien mang du argv va
        # seed: lan chay tai lap duoc tu log, khong phai suy ra.
        mock_config = load_json_config(MOCK_CONFIG_PATH, logger=run_log)
        run_log.log(
            func="run",
            event="run_start",
            inputs={
                "run_id": run_id,
                "argv": list(sys.argv),
                "seed": mock_config["seed"],
                "mock_data_config_version": mock_config["version"],
            },
            outputs={
                "log_files": [
                    rel(run_log.path),
                    rel(match_log.path),
                    rel(price_log.path),
                ]
            },
            decision=None,
            reason="bat_dau_lan_chay_san_pham_mau_A",
        )

        matching_config = matching.load_config(logger=run_log)
        pricing_config = pricing.load_config(logger=run_log)
        run_log.log(
            func="run",
            event="config_loaded",
            inputs={
                "matching_config_path": rel(matching.CONFIG_PATH),
                "pricing_config_path": rel(pricing.CONFIG_PATH),
                "mock_data_config_path": rel(MOCK_CONFIG_PATH),
            },
            outputs={
                "matching_config_version": matching_config["version"],
                "pricing_config_version": pricing_config["version"],
                "mock_data_config_version": mock_config["version"],
            },
            decision=None,
            reason="doc_tham_so_nghiep_vu_tu_config",
        )

        _ensure_mock_data(run_log, run_id)
        drivers = _read_json(DRIVERS_PATH)
        customers = _read_json(CUSTOMERS_PATH)
        rides = _read_json(RIDES_PATH)
        segment_of = {c["customer_id"]: c["segment"] for c in customers}
        run_log.log(
            func="run",
            event="data_loaded",
            inputs={
                "drivers_path": rel(DRIVERS_PATH),
                "customers_path": rel(CUSTOMERS_PATH),
                "rides_path": rel(RIDES_PATH),
            },
            outputs={
                "n_drivers": len(drivers),
                "n_customers": len(customers),
                "n_rides": len(rides),
                "sha256": {
                    rel(DRIVERS_PATH): _sha256(DRIVERS_PATH),
                    rel(CUSTOMERS_PATH): _sha256(CUSTOMERS_PATH),
                    rel(RIDES_PATH): _sha256(RIDES_PATH),
                },
                "mock_data_config_version": mock_config["version"],
                "mock_data_seed": mock_config["seed"],
            },
            decision=None,
            reason="doc_du_lieu_tong_hop",
        )

        results = []
        for ride in rides:
            ride_id = ride["ride_id"]
            context = {"ride_id": ride_id}

            match_log.set_context(context)
            match_result = matching.match(ride, drivers, matching_config, match_log)

            distance_km = matching.haversine_km(
                ride["pickup_lat"],
                ride["pickup_lon"],
                ride["dropoff_lat"],
                ride["dropoff_lon"],
            )
            run_log.set_context(context)
            run_log.log(
                func="run",
                event="ride_distance",
                inputs={
                    "pickup_lat": ride["pickup_lat"],
                    "pickup_lon": ride["pickup_lon"],
                    "dropoff_lat": ride["dropoff_lat"],
                    "dropoff_lon": ride["dropoff_lon"],
                },
                outputs={"distance_km": distance_km},
                decision=None,
                reason="quang_duong_tinh_gia_pickup_den_dropoff",
            )

            price_log.set_context(context)
            fare_result = pricing.fare(
                distance_km, ride["requested_at"], pricing_config, price_log
            )

            results.append(
                {
                    "ride_id": ride_id,
                    "customer_id": ride["customer_id"],
                    "customer_segment": segment_of.get(ride["customer_id"]),
                    "vehicle_type": ride["vehicle_type"],
                    "requested_at": ride["requested_at"],
                    "distance_km": distance_km,
                    "driver_id": match_result["driver_id"],
                    "auto_accept": match_result["auto_accept"],
                    "match_reason": match_result["reason"],
                    "fare_vnd": fare_result["fare_vnd"],
                    "time_coef": fare_result["time_coef"],
                    "fare_reason": fare_result["reason"],
                }
            )

        run_log.clear_context()
        match_log.clear_context()
        price_log.clear_context()

        n_matched = sum(1 for r in results if r["driver_id"] is not None)
        n_auto_accept = sum(1 for r in results if r["auto_accept"])
        # n_decisions DEM THAT tu so dong log co decision != null, khong suy ra
        # tu so chuyen, de con so nay khong tu khang dinh chinh no.
        n_decisions = match_log.decision_count + price_log.decision_count
        summary = {
            "n_rides": len(results),
            "n_matched": n_matched,
            "n_unmatched": len(results) - n_matched,
            "n_auto_accept": n_auto_accept,
            "n_decisions": n_decisions,
            "n_decisions_by_module": {
                matching.MODULE_NAME: match_log.decision_count,
                pricing.MODULE_NAME: price_log.decision_count,
            },
            "total_fare_vnd": sum(r["fare_vnd"] for r in results),
        }

        report = {
            "ts": None,
            "run_id": run_id,
            "schema_version": "0.1",
            "note": "[Suy luan] Ket qua tu du lieu tong hop. Khong phai so lieu that.",
            "config_versions": {
                "matching": matching_config["version"],
                "pricing": pricing_config["version"],
            },
            "log_files": [rel(run_log.path), rel(match_log.path), rel(price_log.path)],
            "summary": summary,
            "results": results,
        }
        report["ts"] = _iso_now()

        os.makedirs(REPORTS_DIR, exist_ok=True)
        report_path = os.path.join(REPORTS_DIR, "product_run_%s.json" % run_id)
        # Mode "x" nhu file log: vo ngay neu bao cao cua run_id nay da ton tai,
        # thay vi ghi de im lang bang chung cua lan chay truoc.
        with open(report_path, "x", encoding="utf-8", newline="\n") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
            fh.write("\n")

        run_log.log(
            func="run",
            event="run_end",
            inputs={"run_id": run_id},
            outputs={
                "report_path": rel(report_path),
                "summary": summary,
                # +1 la chinh dong run_end nay, de con so bang so dong cua file
                # sau khi dong log nay duoc ghi.
                "log_lines": {
                    MODULE_NAME: run_log.line_count + 1,
                    matching.MODULE_NAME: match_log.line_count,
                    pricing.MODULE_NAME: price_log.line_count,
                },
            },
            decision=None,
            reason="ket_thuc_lan_chay_san_pham_mau_A",
        )

        return {
            "run_id": run_id,
            "report_path": report_path,
            "summary": summary,
            "log_paths": [run_log.path, match_log.path, price_log.path],
            # Khong cong 1 o day: dong run_end da duoc ghi va dem xong.
            "log_lines": {
                MODULE_NAME: run_log.line_count,
                matching.MODULE_NAME: match_log.line_count,
                pricing.MODULE_NAME: price_log.line_count,
            },
        }
    finally:
        run_log.close()
        match_log.close()
        price_log.close()


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def main():
    enable_utf8_stdout()
    outcome = run()
    print("run_id=%s" % outcome["run_id"])
    print("report -> %s" % rel(outcome["report_path"]))
    for path in outcome["log_paths"]:
        print("log    -> %s" % rel(path))
    print("summary: %s" % json.dumps(outcome["summary"], ensure_ascii=False))
    print("log_lines: %s" % json.dumps(outcome["log_lines"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
