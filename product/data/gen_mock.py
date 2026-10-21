"""Sinh du lieu tong hop cho san pham mau A (SPEC_A §1).

Du lieu 100% tong hop, seed co dinh lay tu product/config/mock_data.json.
Khong co ten, so dien thoai, bien so, dia chi that.
Chay 2 lan phai ra 3 file JSON giong het nhau.

Chay: python product/data/gen_mock.py
"""

import json
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

_DATA_DIR = os.path.dirname(os.path.abspath(__file__))
_PRODUCT_DIR = os.path.dirname(_DATA_DIR)
if _PRODUCT_DIR not in sys.path:
    sys.path.insert(0, _PRODUCT_DIR)

from logger import (  # noqa: E402
    JsonlLogger,
    enable_utf8_stdout,
    load_json_config,
    make_run_id,
    rel,
)
# Dung dung cong thuc khoang cach cua matching.py, de con so clearance ghi
# trong log cua gen_mock va con so khoang cach do o cho khac khong lech nhau.
from matching import EARTH_RADIUS_KM, haversine_km  # noqa: E402

CONFIG_PATH = os.path.join(_PRODUCT_DIR, "config", "mock_data.json")
DRIVERS_PATH = os.path.join(_DATA_DIR, "drivers.json")
CUSTOMERS_PATH = os.path.join(_DATA_DIR, "customers.json")
RIDES_PATH = os.path.join(_DATA_DIR, "rides.json")

_SECONDS_PER_DAY = 24 * 60 * 60


def _make_id(prefix, index, width):
    return "%s%0*d" % (prefix, width, index)


def _weighted(rnd, weights):
    keys = list(weights.keys())
    return rnd.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def _coord(rnd, low, high, decimals):
    return round(rnd.uniform(low, high), decimals)


def _destination(lat, lon, distance_km, bearing_deg, decimals):
    """Diem den cach (lat, lon) dung distance_km theo huong bearing_deg.

    Cong thuc diem den tren mat cau, nghich dao cua haversine. Hang so ban kinh
    Trai Dat lay tu matching.py, khong phai tham so nghiep vu.
    """
    angular = distance_km / EARTH_RADIUS_KM
    bearing = math.radians(bearing_deg)
    phi1 = math.radians(lat)
    lam1 = math.radians(lon)
    phi2 = math.asin(
        math.sin(phi1) * math.cos(angular)
        + math.cos(phi1) * math.sin(angular) * math.cos(bearing)
    )
    lam2 = lam1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(phi1),
        math.cos(angular) - math.sin(phi1) * math.sin(phi2),
    )
    return round(math.degrees(phi2), decimals), round(math.degrees(lam2), decimals)


def _min_distance_to_drivers(lat, lon, drivers):
    best_km = None
    best_id = None
    for driver in drivers:
        km = haversine_km(lat, lon, driver["lat"], driver["lon"])
        if best_km is None or km < best_km:
            best_km = km
            best_id = driver["driver_id"]
    return best_km, best_id


def _select_overlay_indices(rnd, n_rides, out_cfg, long_cfg, logger):
    """Chon chi so chuyen cho hai nhom. Hai nhom khong giao nhau.

    Dong ngau nhien rieng (cung seed), nen moi chuyen khong duoc chon giu nguyen
    tung byte gia tri da sinh o vong truoc. Ham nay KHONG duoc tieu thu them
    bat ky lan goi rnd nao ngoai hai dong rnd.sample duoi day: moi lan goi them
    se lam lech toan bo cac gia tri toa do sinh SAU do bang cung doi tuong rnd
    (xem ham _select_coincident_indices dung doi tuong Random RIENG vi ly do nay).
    """
    k_out = int(round(out_cfg["share"] * n_rides))
    k_long = int(round(long_cfg["share"] * n_rides))
    idx_out = sorted(rnd.sample(range(n_rides), k_out))
    remaining = [i for i in range(n_rides) if i not in set(idx_out)]
    idx_long = sorted(rnd.sample(remaining, k_long))
    logger.log(
        func="_select_overlay_indices",
        event="overlay_selection",
        inputs={
            "n_rides": n_rides,
            "share_secondary_bbox": out_cfg["share"],
            "share_long_distance": long_cfg["share"],
        },
        outputs={
            "n_secondary_bbox": len(idx_out),
            "n_long_distance": len(idx_long),
            "n_unchanged": n_rides - len(idx_out) - len(idx_long),
            "indices_secondary_bbox": idx_out,
            "indices_long_distance": idx_long,
        },
        decision=None,
        reason="chon_chi_so_chuyen_cho_hai_nhom_khong_giao_nhau",
    )
    return idx_out, idx_long


def _select_coincident_indices(seed, n_rides, idx_out, idx_long, coincident_cfg, logger):
    """Chon chi so chuyen cho nhom thu ba (diem don trung toa do), tren phan
    chi so CON LAI sau khi tru hai nhom dau.

    Dung MOT doi tuong Random RIENG, tach khoi doi tuong rnd dung cho hai nhom
    dau va cho viec sinh toa do cua chung: neu dung chung mot doi tuong, moi
    lan rnd.sample() them o day se tieu thu ngau nhien va lam lech tung byte
    toa do da sinh cho hai nhom dau (da xay ra va duoc phat hien khi doi chieu
    rides.json truoc/sau). Dung doi tuong rieng loai bo hoan toan rui ro nay.
    """
    k_coincident = sum(a["ride_count"] for a in coincident_cfg["assignments"])
    taken = set(idx_out) | set(idx_long)
    remaining = [i for i in range(n_rides) if i not in taken]
    rnd_coincident = random.Random(seed)
    idx_coincident = sorted(rnd_coincident.sample(remaining, k_coincident))
    logger.log(
        func="_select_coincident_indices",
        event="coincident_selection",
        inputs={
            "n_rides": n_rides,
            "n_already_taken": len(taken),
            "n_coincident_point": k_coincident,
        },
        outputs={
            "n_coincident_point": len(idx_coincident),
            "indices_coincident_point": idx_coincident,
        },
        decision=None,
        reason="chon_chi_so_chuyen_cho_nhom_diem_don_trung_toa_do_tren_rnd_rieng",
    )
    return idx_coincident


def apply_ride_overlays(rides, drivers, config, logger):
    """Dat lai toa do cho ba nhom chuyen, tren danh sach rides da sinh.

    Nhom 1: diem don va diem den chuyen sang bbox rieng (rides_in_secondary_bbox).
    Nhom 2: giu diem don, dat lai diem den theo khoang cach rut tu distance_km_bands.
    Nhom 3: dat lai diem don dung bang toa do mot cap diem co dinh
    (rides_with_pickup_at_coincident_point).
    Chuyen khong thuoc nhom nao: khong doi mot byte.
    """
    out_cfg = config["rides_in_secondary_bbox"]
    long_cfg = config["long_distance_rides"]
    coincident_cfg = config["rides_with_pickup_at_coincident_point"]
    decimals = config["coord_decimals"]
    rnd = random.Random(config["seed"])
    n_rides = len(rides)

    idx_out, idx_long = _select_overlay_indices(rnd, n_rides, out_cfg, long_cfg, logger)
    idx_coincident = _select_coincident_indices(
        config["seed"], n_rides, idx_out, idx_long, coincident_cfg, logger
    )
    set_out = set(idx_out)
    set_long = set(idx_long)
    set_coincident = set(idx_coincident)

    # Moi chuyen di qua dung mot trong bon nhanh; ghi log ca bon nhanh.
    for i in range(n_rides):
        if i in set_out:
            group = "secondary_bbox"
            reason = "chuyen_thuoc_nhom_bbox_rieng"
        elif i in set_long:
            group = "long_distance"
            reason = "chuyen_thuoc_nhom_diem_den_xa"
        elif i in set_coincident:
            group = "coincident_point"
            reason = "chuyen_thuoc_nhom_diem_don_trung_toa_do"
        else:
            group = "base"
            reason = "chuyen_giu_nguyen_gia_tri_da_sinh"
        logger.log(
            func="apply_ride_overlays",
            event="ride_group_assigned",
            inputs={"index": i, "ride_id": rides[i]["ride_id"]},
            outputs={"group": group},
            decision=None,
            reason=reason,
        )

    out_bbox = out_cfg["bbox"]
    min_clearance_km = out_cfg["min_clearance_km"]
    clearances = []
    for i in idx_out:
        ride = rides[i]
        before = {
            k: ride[k]
            for k in ("pickup_lat", "pickup_lon", "dropoff_lat", "dropoff_lon")
        }
        ride["pickup_lat"] = _coord(rnd, out_bbox["lat_min"], out_bbox["lat_max"], decimals)
        ride["pickup_lon"] = _coord(rnd, out_bbox["lon_min"], out_bbox["lon_max"], decimals)
        ride["dropoff_lat"] = _coord(rnd, out_bbox["lat_min"], out_bbox["lat_max"], decimals)
        ride["dropoff_lon"] = _coord(rnd, out_bbox["lon_min"], out_bbox["lon_max"], decimals)
        clearance_km, nearest_id = _min_distance_to_drivers(
            ride["pickup_lat"], ride["pickup_lon"], drivers
        )
        clearances.append(clearance_km)
        logger.log(
            func="apply_ride_overlays",
            event="ride_adjusted",
            inputs={
                "index": i,
                "ride_id": ride["ride_id"],
                "group": "secondary_bbox",
                "bbox": out_bbox,
                "before": before,
            },
            outputs={
                "pickup_lat": ride["pickup_lat"],
                "pickup_lon": ride["pickup_lon"],
                "dropoff_lat": ride["dropoff_lat"],
                "dropoff_lon": ride["dropoff_lon"],
                "trip_distance_km": haversine_km(
                    ride["pickup_lat"],
                    ride["pickup_lon"],
                    ride["dropoff_lat"],
                    ride["dropoff_lon"],
                ),
                "nearest_driver_id": nearest_id,
                "nearest_driver_km": clearance_km,
            },
            decision=None,
            reason="dat_lai_toa_do_trong_bbox_rieng",
        )

    observed_min = min(clearances) if clearances else None
    clearance_ok = observed_min is not None and observed_min >= min_clearance_km
    logger.log(
        func="apply_ride_overlays",
        event="clearance_check",
        inputs={
            "n_rides_checked": len(clearances),
            "min_clearance_km": min_clearance_km,
            "n_drivers": len(drivers),
        },
        outputs={"observed_min_km": observed_min, "ok": clearance_ok},
        decision=None,
        reason=(
            "khoang_cach_den_tai_xe_gan_nhat_dat_nguong"
            if clearance_ok
            else "khoang_cach_den_tai_xe_gan_nhat_duoi_nguong_nen_bao_loi"
        ),
    )
    if not clearance_ok:
        raise ValueError(
            "rides_in_secondary_bbox: khoang cach nho nhat %r km < min_clearance_km %r"
            % (observed_min, min_clearance_km)
        )

    bands = long_cfg["distance_km_bands"]
    bearing_lo, bearing_hi = long_cfg["bearing_deg_range"]
    for order, i in enumerate(idx_long):
        ride = rides[i]
        band_index = order % len(bands)
        band_lo, band_hi = bands[band_index]
        target_km = rnd.uniform(band_lo, band_hi)
        bearing_deg = rnd.uniform(bearing_lo, bearing_hi)
        before = {k: ride[k] for k in ("dropoff_lat", "dropoff_lon")}
        ride["dropoff_lat"], ride["dropoff_lon"] = _destination(
            ride["pickup_lat"], ride["pickup_lon"], target_km, bearing_deg, decimals
        )
        actual_km = haversine_km(
            ride["pickup_lat"],
            ride["pickup_lon"],
            ride["dropoff_lat"],
            ride["dropoff_lon"],
        )
        logger.log(
            func="apply_ride_overlays",
            event="ride_adjusted",
            inputs={
                "index": i,
                "ride_id": ride["ride_id"],
                "group": "long_distance",
                "band_index": band_index,
                "band_km": [band_lo, band_hi],
                "target_km": target_km,
                "bearing_deg": bearing_deg,
                "before": before,
            },
            outputs={
                "pickup_lat": ride["pickup_lat"],
                "pickup_lon": ride["pickup_lon"],
                "dropoff_lat": ride["dropoff_lat"],
                "dropoff_lon": ride["dropoff_lon"],
                "trip_distance_km": actual_km,
            },
            decision=None,
            reason="dat_lai_diem_den_theo_band_khoang_cach",
        )

    pairs = config["coincident_driver_points"]["pairs"]
    coincident_vehicle_type = coincident_cfg["vehicle_type"]
    pos = 0
    for assignment in coincident_cfg["assignments"]:
        pair = pairs[assignment["pair_index"]]
        point = pair["point"]
        count = assignment["ride_count"]
        for i in idx_coincident[pos : pos + count]:
            ride = rides[i]
            before = {
                k: ride[k] for k in ("pickup_lat", "pickup_lon", "vehicle_type")
            }
            ride["pickup_lat"] = point["lat"]
            ride["pickup_lon"] = point["lon"]
            ride["vehicle_type"] = coincident_vehicle_type
            logger.log(
                func="apply_ride_overlays",
                event="ride_adjusted",
                inputs={
                    "index": i,
                    "ride_id": ride["ride_id"],
                    "group": "coincident_point",
                    "pair_index": assignment["pair_index"],
                    "point": point,
                    "before": before,
                },
                outputs={
                    "pickup_lat": ride["pickup_lat"],
                    "pickup_lon": ride["pickup_lon"],
                    "vehicle_type": ride["vehicle_type"],
                    "dropoff_lat": ride["dropoff_lat"],
                    "dropoff_lon": ride["dropoff_lon"],
                    "trip_distance_km": haversine_km(
                        ride["pickup_lat"],
                        ride["pickup_lon"],
                        ride["dropoff_lat"],
                        ride["dropoff_lon"],
                    ),
                },
                decision=None,
                reason="dat_lai_diem_don_trung_toa_do_cap_diem_co_dinh",
            )
        pos += count

    return rides


def apply_coincident_driver_points(drivers, config, logger):
    """Dat lai lat/lon/status/vehicle_type/trips_today cua tung cap tai xe
    duoc neu ten trong coincident_driver_points, de hai tai xe trong cung mot
    cap nam DUNG mot toa do. Khong doi vi tri tai xe nao khac.
    """
    pairs = config["coincident_driver_points"]["pairs"]
    by_id = {d["driver_id"]: d for d in drivers}

    for pair_index, pair in enumerate(pairs):
        point = pair["point"]
        driver_ids = pair["driver_ids"]
        trips_today_list = pair["trips_today"]
        for member_index, driver_id in enumerate(driver_ids):
            driver = by_id.get(driver_id)
            if driver is None:
                logger.log(
                    func="apply_coincident_driver_points",
                    event="driver_point_override",
                    inputs={
                        "pair_index": pair_index,
                        "driver_id": driver_id,
                        "point": point,
                    },
                    outputs={},
                    decision=None,
                    reason="driver_id_khong_ton_tai_nen_bao_loi",
                )
                raise ValueError(
                    "coincident_driver_points: driver_id %r khong ton tai" % driver_id
                )
            before = {
                k: driver[k]
                for k in ("lat", "lon", "status", "vehicle_type", "trips_today")
            }
            driver["lat"] = point["lat"]
            driver["lon"] = point["lon"]
            driver["status"] = pair["status"]
            driver["vehicle_type"] = pair["vehicle_type"]
            driver["trips_today"] = trips_today_list[member_index]
            logger.log(
                func="apply_coincident_driver_points",
                event="driver_point_override",
                inputs={
                    "pair_index": pair_index,
                    "driver_id": driver_id,
                    "point": point,
                    "before": before,
                },
                outputs={
                    "lat": driver["lat"],
                    "lon": driver["lon"],
                    "status": driver["status"],
                    "vehicle_type": driver["vehicle_type"],
                    "trips_today": driver["trips_today"],
                },
                decision=None,
                reason="dat_lai_toa_do_tai_xe_dung_mot_diem_chung_voi_tai_xe_khac_trong_cap",
            )
    return drivers


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def generate(config, logger):
    """Sinh 3 bang du lieu tong hop tu config. Tra ve dict 3 danh sach."""
    rnd = random.Random(config["seed"])
    bbox = config["bbox"]
    decimals = config["coord_decimals"]
    counts = config["counts"]
    idf = config["id_format"]
    ar_lo, ar_hi = config["acceptance_rate_range"]
    ar_dec = config["acceptance_rate_decimals"]
    trips_lo, trips_hi = config["trips_today_range"]

    logger.log(
        func="generate",
        event="gen_start",
        inputs={
            "seed": config["seed"],
            "config_version": config["version"],
            "bbox": bbox,
            "counts": counts,
            "argv": list(sys.argv),
        },
        outputs={},
        decision=None,
        reason="bat_dau_sinh_du_lieu_tong_hop",
    )

    drivers = []
    for i in range(1, counts["drivers"] + 1):
        record = {
            "driver_id": _make_id(idf["driver_prefix"], i, idf["width"]),
            "lat": _coord(rnd, bbox["lat_min"], bbox["lat_max"], decimals),
            "lon": _coord(rnd, bbox["lon_min"], bbox["lon_max"], decimals),
            "status": _weighted(rnd, config["driver_status_weights"]),
            "vehicle_type": _weighted(rnd, config["vehicle_type_weights"]),
            "acceptance_rate": round(rnd.uniform(ar_lo, ar_hi), ar_dec),
            "trips_today": rnd.randint(trips_lo, trips_hi),
        }
        drivers.append(record)
        logger.log(
            func="generate",
            event="record_generated",
            inputs={"table": "drivers", "index": i},
            outputs=record,
            decision=None,
            reason="sinh_ban_ghi_tai_xe_tong_hop",
        )

    drivers = apply_coincident_driver_points(drivers, config, logger)

    customers = []
    for i in range(1, counts["customers"] + 1):
        record = {
            "customer_id": _make_id(idf["customer_prefix"], i, idf["width"]),
            "segment": _weighted(rnd, config["customer_segment_weights"]),
        }
        customers.append(record)
        logger.log(
            func="generate",
            event="record_generated",
            inputs={"table": "customers", "index": i},
            outputs=record,
            decision=None,
            reason="sinh_ban_ghi_khach_hang_tong_hop",
        )

    base_date = config["base_date"]
    tz = timezone(timedelta(hours=config["utc_offset_hours"]))
    day_start = datetime.fromisoformat(base_date).replace(tzinfo=tz)
    customer_ids = [c["customer_id"] for c in customers]
    n_rides = counts["rides"]

    rides = []
    for i in range(1, n_rides + 1):
        offset_seconds = (i - 1) * _SECONDS_PER_DAY // n_rides
        requested_at = (day_start + timedelta(seconds=offset_seconds)).isoformat()
        record = {
            "ride_id": _make_id(idf["ride_prefix"], i, idf["width"]),
            "customer_id": rnd.choice(customer_ids),
            "vehicle_type": _weighted(rnd, config["vehicle_type_weights"]),
            "pickup_lat": _coord(rnd, bbox["lat_min"], bbox["lat_max"], decimals),
            "pickup_lon": _coord(rnd, bbox["lon_min"], bbox["lon_max"], decimals),
            "dropoff_lat": _coord(rnd, bbox["lat_min"], bbox["lat_max"], decimals),
            "dropoff_lon": _coord(rnd, bbox["lon_min"], bbox["lon_max"], decimals),
            "requested_at": requested_at,
        }
        rides.append(record)
        logger.log(
            func="generate",
            event="record_generated",
            inputs={"table": "rides", "index": i, "offset_seconds": offset_seconds},
            outputs=record,
            decision=None,
            reason="sinh_ban_ghi_chuyen_tong_hop",
        )

    rides = apply_ride_overlays(rides, drivers, config, logger)

    return {"drivers": drivers, "customers": customers, "rides": rides}


def write_tables(tables, logger):
    for name, path in (
        ("drivers", DRIVERS_PATH),
        ("customers", CUSTOMERS_PATH),
        ("rides", RIDES_PATH),
    ):
        _write_json(path, tables[name])
        logger.log(
            func="write_tables",
            event="table_written",
            inputs={"table": name, "path": rel(path)},
            outputs={"n_records": len(tables[name])},
            decision=None,
            reason="ghi_bang_du_lieu_tong_hop_ra_dia",
        )


def main(run_id=None):
    enable_utf8_stdout()
    run_id = run_id or make_run_id()
    logger = JsonlLogger("gen_mock", run_id)
    try:
        config = load_json_config(CONFIG_PATH, logger=logger)
        tables = generate(config, logger)
        write_tables(tables, logger)
        logger.log(
            func="main",
            event="gen_end",
            inputs={"run_id": run_id, "config_version": config["version"]},
            outputs={
                "n_drivers": len(tables["drivers"]),
                "n_customers": len(tables["customers"]),
                "n_rides": len(tables["rides"]),
                "log_file": os.path.basename(logger.path),
            },
            decision=None,
            reason="sinh_du_lieu_tong_hop_xong",
        )
    finally:
        logger.close()
    print("gen_mock run_id=%s" % run_id)
    print("  drivers   -> %s (%d)" % (rel(DRIVERS_PATH), len(tables["drivers"])))
    print("  customers -> %s (%d)" % (rel(CUSTOMERS_PATH), len(tables["customers"])))
    print("  rides     -> %s (%d)" % (rel(RIDES_PATH), len(tables["rides"])))
    print("  log       -> %s" % rel(logger.path))
    return tables


if __name__ == "__main__":
    main()
