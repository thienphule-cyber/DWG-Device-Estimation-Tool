"""Detect existing devices from block references (INSERT) and assign them to rooms."""
from __future__ import annotations

from shapely.geometry import Point

from .models import Device


def _match_type(name: str, mapping: dict, mode: str = "contains"):
    """Return the first device type whose pattern matches the name."""
    name = name.upper()
    for device_type, patterns in mapping.items():
        for p in patterns:
            p = p.upper()
            if (mode == "contains" and p in name) or (mode == "exact" and p == name):
                return device_type
    return None


def detect_devices(doc, rooms: list, block_cfg: dict, layer_cfg: dict) -> tuple:
    """Return (devices, warnings)."""
    warnings = []
    msp = doc.modelspace()

    block_map = block_cfg.get("device_types", {})
    block_mode = block_cfg.get("match_mode", "contains")
    ignore_blocks = {b.upper() for b in block_cfg.get("ignore_blocks", [])}

    layer_map = layer_cfg.get("device_layers", {})
    layer_mode = layer_cfg.get("match_mode", "contains")
    ignore_layers = {l.upper() for l in layer_cfg.get("ignore_layers", [])}

    # Smallest rooms first so nested rooms win over large outer shapes
    sorted_rooms = sorted(rooms, key=lambda r: r.area_m2)
    polygons = [(r.id, r.polygon) for r in sorted_rooms]

    devices = []
    unmatched_blocks = {}

    for e in msp:
        if e.dxftype() != "INSERT":
            continue

        block_name = e.dxf.name
        layer = e.dxf.layer
        if block_name.upper() in ignore_blocks or layer.upper() in ignore_layers:
            continue

        # Block name has priority, layer is the fallback
        device_type = _match_type(block_name, block_map, block_mode)
        if device_type is None:
            device_type = _match_type(layer, layer_map, layer_mode)
        if device_type is None:
            unmatched_blocks[block_name] = unmatched_blocks.get(block_name, 0) + 1
            continue

        ins = e.dxf.insert
        point = Point(ins.x, ins.y)
        room_id = next((rid for rid, poly in polygons if poly.contains(point)), None)

        devices.append(
            Device(
                id=f"D{len(devices) + 1:04d}",
                device_type=device_type,
                block_name=block_name,
                layer=layer,
                x=round(ins.x, 3),
                y=round(ins.y, 3),
                room_id=room_id,
            )
        )

    if unmatched_blocks:
        top = sorted(unmatched_blocks.items(), key=lambda kv: -kv[1])[:10]
        warnings.append(
            "Unmapped blocks (top 10 by count): "
            + ", ".join(f"{name} x{n}" for name, n in top)
            + ". Add them to block_mapping.json if they are devices."
        )
    if not devices:
        warnings.append("No devices detected. Check block_mapping.json against real block names.")
    outside = sum(1 for d in devices if d.room_id is None)
    if outside:
        warnings.append(f"{outside} device(s) are outside any detected room.")
    return devices, warnings