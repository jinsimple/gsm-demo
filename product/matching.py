"""Matching tai xe cho san pham mau A (SPEC_A §2).

Ham thuan: moi chuyen doc lap, khong cap nhat trang thai tai xe sau khi ghep
(gioi han mo phong da biet).

Moi tham so nghiep vu nam trong product/config/matching.json.
Moi ung vien duoc xet deu co dung mot dong log (CLAUDE.md §3).

[Suy luan] Sandbox mo phong, khong phai san pham that cua Green SM.
"""

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from logger import load_json_config, make_fallback_logger  # noqa: E402

CONFIG_PATH = os.path.join(_HERE, "config", "matching.json")
MODULE_NAME = "matching"

# Hang so vat ly cua cong thuc haversine, KHONG phai tham so nghiep vu.
EARTH_RADIUS_KM = 6371.0088

_DEFAULT_LOGGER = None


def default_logger():
    """Logger du phong khi match() duoc goi truc tiep, khong truyen logger."""
    global _DEFAULT_LOGGER
    if _DEFAULT_LOGGER is None:
        _DEFAULT_LOGGER = make_fallback_logger(MODULE_NAME)
    return _DEFAULT_LOGGER


def load_config(path=None, logger=None):
    return load_json_config(path or CONFIG_PATH, logger=logger)


def haversine_km(lat1, lon1, lat2, lon2):
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def match(ride, drivers, config, logger=None):
    """Ghep mot chuyen voi mot tai xe.

    Tra ve {"driver_id": str|None, "auto_accept": bool, "reason": str}.
    """
    log = logger if logger is not None else default_logger()

    radius_km = config["radius_km"]
    auto_accept_threshold = config["auto_accept_threshold"]
    idle_status = config["idle_status"]

    ride_vehicle_type = ride["vehicle_type"]
    pickup_lat = ride["pickup_lat"]
    pickup_lon = ride["pickup_lon"]

    log.log(
        func="match",
        event="match_start",
        inputs={
            "ride_vehicle_type": ride_vehicle_type,
            "pickup_lat": pickup_lat,
            "pickup_lon": pickup_lon,
            "n_drivers_input": len(drivers),
            "radius_km": radius_km,
            "auto_accept_threshold": auto_accept_threshold,
            "config_version": config.get("version"),
        },
        outputs={},
        decision=None,
        reason="bat_dau_xet_ung_vien",
    )

    candidates = []
    for driver in drivers:
        driver_id = driver["driver_id"]
        status = driver["status"]
        driver_vehicle_type = driver["vehicle_type"]
        driver_lat = driver["lat"]
        driver_lon = driver["lon"]
        trips_today = driver["trips_today"]
        acceptance_rate = driver["acceptance_rate"]

        distance_km = haversine_km(pickup_lat, pickup_lon, driver_lat, driver_lon)

        if status != idle_status:
            kept = False
            reason = "not_idle"
        elif driver_vehicle_type != ride_vehicle_type:
            kept = False
            reason = "wrong_vehicle_type"
        elif distance_km > radius_km:
            kept = False
            reason = "out_of_radius"
        else:
            kept = True
            reason = "kept_as_candidate"

        log.log(
            func="match",
            event="candidate_eval",
            inputs={
                "driver_id": driver_id,
                "status": status,
                "vehicle_type": driver_vehicle_type,
                "lat": driver_lat,
                "lon": driver_lon,
                "trips_today": trips_today,
                "acceptance_rate": acceptance_rate,
                "ride_vehicle_type": ride_vehicle_type,
                "pickup_lat": pickup_lat,
                "pickup_lon": pickup_lon,
                "radius_km": radius_km,
            },
            outputs={"distance_km": distance_km, "kept": kept},
            decision=None,
            reason=reason,
        )

        if kept:
            candidates.append(
                {
                    "driver_id": driver_id,
                    "distance_km": distance_km,
                    "trips_today": trips_today,
                    "acceptance_rate": acceptance_rate,
                }
            )

    log.log(
        func="match",
        event="candidate_pool",
        inputs={"n_drivers_input": len(drivers), "radius_km": radius_km},
        outputs={
            "n_candidates": len(candidates),
            "candidate_driver_ids": [c["driver_id"] for c in candidates],
        },
        decision=None,
        reason="tong_hop_ung_vien_con_lai_sau_cac_buoc_loc",
    )

    if not candidates:
        result = {"driver_id": None, "auto_accept": False, "reason": "no_driver_in_radius"}
        log.log(
            func="match",
            event="match_result",
            inputs={
                "n_drivers_input": len(drivers),
                "n_candidates": 0,
                "radius_km": radius_km,
            },
            outputs=dict(result),
            decision="no_match",
            reason="no_driver_in_radius",
        )
        return result

    ordered = sorted(
        candidates,
        key=lambda c: (c["distance_km"], c["trips_today"], c["driver_id"]),
    )
    winner = ordered[0]

    tied_distance = [c for c in ordered if c["distance_km"] == winner["distance_km"]]
    if len(tied_distance) > 1:
        tied_trips = [c for c in tied_distance if c["trips_today"] == winner["trips_today"]]
        tie_reason = (
            "tie_broken_by_driver_id" if len(tied_trips) > 1 else "tie_broken_by_trips_today"
        )
        log.log(
            func="match",
            event="tie_break",
            inputs={
                "tied_distance_km": winner["distance_km"],
                "tied_candidates": [
                    {
                        "driver_id": c["driver_id"],
                        "trips_today": c["trips_today"],
                    }
                    for c in tied_distance
                ],
            },
            outputs={"driver_id": winner["driver_id"]},
            decision=None,
            reason=tie_reason,
        )
    else:
        log.log(
            func="match",
            event="tie_break",
            inputs={"tied_distance_km": winner["distance_km"], "n_tied": 1},
            outputs={"driver_id": winner["driver_id"]},
            decision=None,
            reason="no_tie",
        )

    auto_accept = winner["acceptance_rate"] < auto_accept_threshold
    log.log(
        func="match",
        event="auto_accept_eval",
        inputs={
            "driver_id": winner["driver_id"],
            "acceptance_rate": winner["acceptance_rate"],
            "auto_accept_threshold": auto_accept_threshold,
        },
        outputs={"auto_accept": auto_accept},
        decision=None,
        reason=(
            "acceptance_rate_below_threshold"
            if auto_accept
            else "acceptance_rate_at_or_above_threshold"
        ),
    )

    result = {
        "driver_id": winner["driver_id"],
        "auto_accept": auto_accept,
        "reason": "matched_nearest_candidate",
    }
    log.log(
        func="match",
        event="match_result",
        inputs={
            "n_drivers_input": len(drivers),
            "n_candidates": len(candidates),
            "radius_km": radius_km,
            "auto_accept_threshold": auto_accept_threshold,
        },
        outputs={
            "driver_id": winner["driver_id"],
            "auto_accept": auto_accept,
            "distance_km": winner["distance_km"],
            "trips_today": winner["trips_today"],
            "acceptance_rate": winner["acceptance_rate"],
        },
        decision=winner["driver_id"],
        reason="matched_nearest_candidate",
    )
    return result
