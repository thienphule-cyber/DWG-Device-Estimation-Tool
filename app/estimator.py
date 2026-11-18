"""Compute Estimated and Recommended quantities per room and device type."""
from __future__ import annotations

import math

from .models import EstimateItem

DEVICE_TYPES = ["lighting", "switches", "sockets", "sensors", "hvac"]


def _confidence(room) -> float:
    """Confidence depends on how reliable the room type and area are."""
    if room.label_found and room.room_type != "other":
        conf = 0.7
    elif room.label_found:
        conf = 0.5
    else:
        conf = 0.4
    if room.area_m2 < 3 or room.area_m2 > 100:
        conf -= 0.15
    return round(max(conf, 0.2), 2)


def estimate_room(room, devices: list, rules_cfg: dict) -> list:
    """Return a list of EstimateItem for one room."""
    rules = rules_cfg["rules"].get(room.room_type, rules_cfg["rules"]["other"])
    items = []

    for device_type in DEVICE_TYPES:
        detected = sum(
            1 for d in devices if d.room_id == room.id and d.device_type == device_type
        )
        rule = rules.get(device_type)
        if rule is None:
            items.append(EstimateItem(room.id, device_type, detected=detected))
            continue

        apu = rule.get("area_per_unit", 0)
        expected = rule.get("min", 0)
        if apu > 0:
            expected = max(math.ceil(room.area_m2 / apu), expected)

        estimated = max(expected - detected, 0)
        recommended = rule.get("recommended", 0)

        reason = (
            f"{room.room_type} {room.area_m2} m2: 1 per {apu} m2 (min {rule.get('min', 0)}) "
            f"-> expected {expected}, detected {detected}"
        )
        if recommended:
            reason += f"; +{recommended} recommended by room purpose"

        items.append(
            EstimateItem(
                room_id=room.id,
                device_type=device_type,
                detected=detected,
                estimated=estimated,
                recommended=recommended,
                reason=reason,
                confidence=_confidence(room),
            )
        )
    return items


def estimate_all(rooms: list, devices: list, rules_cfg: dict) -> list:
    items = []
    for room in rooms:
        items.extend(estimate_room(room, devices, rules_cfg))
    return items


def recalculate_room(result, room_id: str, rules_cfg: dict) -> None:
    """Recalculate one room after the user changed its type (keeps other rooms untouched)."""
    room = result.room_by_id(room_id)
    if room is None:
        return
    result.estimates = [e for e in result.estimates if e.room_id != room_id]
    result.estimates.extend(estimate_room(room, result.devices, rules_cfg))