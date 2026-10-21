"""Pricing gia cuoc khach cho san pham mau A (SPEC_A §3).

Moi tham so nghiep vu nam trong product/config/pricing.json.
Log tung bac km va tien cua bac, he so ap dung va ly do, gia truoc va sau lam tron.

[Suy luan] Sandbox mo phong, moi con so la GIA.
"""

import math
import os
import sys
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from logger import load_json_config, make_fallback_logger  # noqa: E402

CONFIG_PATH = os.path.join(_HERE, "config", "pricing.json")
MODULE_NAME = "pricing"

# Sai so lam tron cua so thuc, khong phai tham so nghiep vu.
_FLOAT_EPSILON = 1e-9
_FLOAT_DECIMALS = 6

_DEFAULT_LOGGER = None


def default_logger():
    """Logger du phong khi fare() duoc goi truc tiep, khong truyen logger."""
    global _DEFAULT_LOGGER
    if _DEFAULT_LOGGER is None:
        _DEFAULT_LOGGER = make_fallback_logger(MODULE_NAME)
    return _DEFAULT_LOGGER


def load_config(path=None, logger=None):
    return load_json_config(path or CONFIG_PATH, logger=logger)


def _hour_of(requested_at):
    return datetime.fromisoformat(requested_at).hour


def _round_to_multiple(amount, mode, multiple, log=None):
    value = round(amount, _FLOAT_DECIMALS)
    if mode == "up":
        return int(math.ceil(value / multiple - _FLOAT_EPSILON) * multiple)
    if mode == "down":
        return int(math.floor(value / multiple + _FLOAT_EPSILON) * multiple)
    if mode == "nearest":
        return int(round(value / multiple) * multiple)
    # Ghi log KHONG dieu kien: nguoi goi khong truyen logger thi dung logger
    # du phong, de nhanh bao loi nay khong bao gio chay ma khong de lai log.
    log = log if log is not None else default_logger()
    log.log(
        func="_round_to_multiple",
        event="rounding_mode_unsupported",
        inputs={"mode": mode, "multiple_vnd": multiple, "amount_vnd": amount},
        outputs={},
        decision=None,
        reason="rounding_mode_khong_ho_tro_nen_bao_loi",
    )
    raise ValueError("rounding.mode khong ho tro: %r" % mode)


def fare(distance_km, requested_at, config, logger=None):
    """Tinh gia cuoc khach cho mot quang duong va mot thoi diem yeu cau.

    Tra ve {"fare_vnd": int, "breakdown": list, "time_coef": float, "reason": str}.
    """
    log = logger if logger is not None else default_logger()

    tiers = config["tiers"]
    rounding = config["rounding"]
    default_time_coef = config["default_time_coef"]
    max_time_coef = config["max_time_coef"]

    log.log(
        func="fare",
        event="fare_start",
        inputs={
            "distance_km": distance_km,
            "requested_at": requested_at,
            "config_version": config.get("version"),
            "currency": config.get("currency"),
        },
        outputs={},
        decision=None,
        reason="bat_dau_tinh_gia",
    )

    breakdown = []
    base_fare = 0.0

    for index, tier in enumerate(tiers):
        from_km = tier["from_km"]
        to_km = tier["to_km"]
        upper = distance_km if to_km is None else min(distance_km, to_km)
        km_in_tier = max(0.0, upper - from_km)

        if tier["kind"] == "flat":
            amount = float(tier["amount_vnd"])
            unit = tier["amount_vnd"]
            reason = "tier_flat_applied"
        elif tier["kind"] == "per_km":
            unit = tier["rate_vnd_per_km"]
            amount = km_in_tier * unit
            reason = "tier_charged_per_km" if km_in_tier > 0 else "tier_not_reached"
        else:
            log.log(
                func="fare",
                event="tier_kind_unsupported",
                inputs={
                    "tier_index": index,
                    "tier_id": tier.get("tier_id"),
                    "kind": tier["kind"],
                },
                outputs={},
                decision=None,
                reason="tier_kind_khong_ho_tro_nen_bao_loi",
            )
            raise ValueError("tier.kind khong ho tro: %r" % tier["kind"])

        base_fare += amount
        entry = {
            "step": "tier",
            "tier_index": index,
            "tier_id": tier.get("tier_id"),
            "kind": tier["kind"],
            "from_km": from_km,
            "to_km": to_km,
            "km_in_tier": km_in_tier,
            "amount_vnd": amount,
        }
        breakdown.append(entry)

        log.log(
            func="fare",
            event="fare_tier",
            inputs={
                "distance_km": distance_km,
                "tier_index": index,
                "tier_id": tier.get("tier_id"),
                "kind": tier["kind"],
                "from_km": from_km,
                "to_km": to_km,
                "unit_vnd": unit,
            },
            outputs={
                "km_in_tier": km_in_tier,
                "amount_vnd": amount,
                "base_fare_running_vnd": base_fare,
            },
            decision=None,
            reason=reason,
        )

    breakdown.append({"step": "base_fare", "amount_vnd": base_fare})
    log.log(
        func="fare",
        event="base_fare_computed",
        inputs={"distance_km": distance_km, "n_tiers": len(tiers)},
        outputs={"base_fare_vnd": base_fare},
        decision=None,
        reason="tong_tien_cac_bac_truoc_he_so",
    )

    hour = _hour_of(requested_at)
    raw_coef = default_time_coef
    window_id = None
    for window in config["time_coefficients"]:
        if hour in window["hours"]:
            raw_coef = window["coef"]
            window_id = window.get("window_id")
            break

    log.log(
        func="fare",
        event="time_coef_applied",
        inputs={
            "requested_at": requested_at,
            "hour": hour,
            "default_time_coef": default_time_coef,
        },
        outputs={"raw_time_coef": raw_coef, "window_id": window_id},
        decision=None,
        reason=(
            "hour_in_window_%s" % window_id
            if window_id is not None
            else "hour_not_in_any_window_default_coef"
        ),
    )

    time_coef = min(raw_coef, max_time_coef)
    log.log(
        func="fare",
        event="time_coef_cap",
        inputs={"raw_time_coef": raw_coef, "max_time_coef": max_time_coef},
        outputs={"time_coef": time_coef},
        decision=None,
        reason="cap_applied" if time_coef < raw_coef else "cap_not_binding",
    )

    fare_before_rounding = base_fare * time_coef
    breakdown.append(
        {
            "step": "time_coef",
            "hour": hour,
            "window_id": window_id,
            "time_coef": time_coef,
            "amount_vnd": fare_before_rounding,
        }
    )

    fare_vnd = _round_to_multiple(
        fare_before_rounding, rounding["mode"], rounding["multiple_vnd"], log
    )
    breakdown.append(
        {
            "step": "rounding",
            "mode": rounding["mode"],
            "multiple_vnd": rounding["multiple_vnd"],
            "amount_vnd": fare_vnd,
        }
    )

    log.log(
        func="fare",
        event="fare_rounding",
        inputs={
            "fare_before_rounding_vnd": fare_before_rounding,
            "mode": rounding["mode"],
            "multiple_vnd": rounding["multiple_vnd"],
        },
        outputs={"fare_after_rounding_vnd": fare_vnd},
        decision=None,
        reason="rounded_%s_to_multiple" % rounding["mode"],
    )

    result = {
        "fare_vnd": fare_vnd,
        "breakdown": breakdown,
        "time_coef": time_coef,
        "reason": "fare_computed",
    }
    log.log(
        func="fare",
        event="fare_result",
        inputs={"distance_km": distance_km, "requested_at": requested_at},
        outputs={
            "fare_vnd": fare_vnd,
            "base_fare_vnd": base_fare,
            "time_coef": time_coef,
            "hour": hour,
            "window_id": window_id,
            "fare_before_rounding_vnd": fare_before_rounding,
        },
        decision=fare_vnd,
        reason="fare_computed",
    )
    return result
