"""Group rooms into zones (floors or user-defined groups)."""
from __future__ import annotations

import re

DEFAULT_ZONE = "Zone A"

# Detect floor markers in a room name, e.g. "L2", "F3", "FLOOR 2", "TANG 1"
FLOOR_PATTERN = re.compile(r"\b(?:L|F|FLOOR|LEVEL|TANG)\s?-?(\d{1,2})\b", re.IGNORECASE)


def assign_zones(rooms: list) -> list:
    """Assign a zone to each room automatically. Rooms without a floor marker go to the default zone."""
    for room in rooms:
        match = FLOOR_PATTERN.search(room.name)
        room.zone = f"Floor {match.group(1)}" if match else DEFAULT_ZONE
    return rooms


def set_room_zone(rooms: list, room_id: str, zone_name: str) -> bool:
    """Manually move one room to a zone (used by the edit UI)."""
    for room in rooms:
        if room.id == room_id:
            room.zone = zone_name.strip() or DEFAULT_ZONE
            return True
    return False


def rename_zone(rooms: list, old_name: str, new_name: str) -> int:
    """Rename a zone for all its rooms. Returns the number of rooms changed."""
    count = 0
    for room in rooms:
        if room.zone == old_name:
            room.zone = new_name
            count += 1
    return count


def list_zones(rooms: list) -> list:
    return sorted({room.zone for room in rooms})