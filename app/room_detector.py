"""Detect rooms from closed polylines / hatches and assign names from text labels."""
from __future__ import annotations

import re
import unicodedata

from shapely.geometry import Point, Polygon

from .models import Room

MIN_ROOM_AREA_M2 = 2.0      # ignore tiny shapes (symbols, furniture)
MAX_ROOM_AREA_M2 = 400.0    # ignore huge shapes (building outline, frames)


def normalize(text: str) -> str:
    """Uppercase and strip Vietnamese diacritics so keyword matching is easier."""
    text = text.replace("\u0111", "d").replace("\u0110", "D")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return text.upper().strip()


def _layer_matches(layer: str, patterns: list) -> bool:
    layer = layer.upper()
    return any(p.upper() in layer for p in patterns)


def _is_ignored_layer(layer: str, ignore_layers: list) -> bool:
    return layer.upper() in {l.upper() for l in ignore_layers}


def _closed_points(points: list, closed_flag: bool, tol: float = 1e-6):
    """Return the point list if the shape is closed, otherwise None."""
    if len(points) < 3:
        return None
    if closed_flag:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    if abs(x0 - x1) < tol and abs(y0 - y1) < tol:
        return points[:-1]
    return None


def _polygons_from_entity(e) -> list:
    """Extract candidate polygons (list of point lists) from one entity. Bulges are ignored."""
    t = e.dxftype()
    result = []
    if t == "LWPOLYLINE":
        pts = [(p[0], p[1]) for p in e.get_points("xy")]
        pts = _closed_points(pts, e.closed)
        if pts:
            result.append(pts)
    elif t == "POLYLINE":
        pts = [(p.x, p.y) for p in e.points()]
        pts = _closed_points(pts, e.is_closed)
        if pts:
            result.append(pts)
    elif t == "HATCH":
        for path in e.paths:
            # Only polyline boundary paths that are external boundaries
            if path.PATH_TYPE == "PolylinePath" and (path.path_type_flags & 1):
                pts = [(v[0], v[1]) for v in path.vertices]
                if len(pts) >= 3:
                    result.append(pts)
    return result


def _guess_room_type(text: str, room_type_keywords: dict) -> str | None:
    """Match text against room type keywords (whole-word match, accent-insensitive)."""
    norm = normalize(text)
    for room_type, keywords in room_type_keywords.items():
        for kw in keywords:
            if re.search(r"\b" + re.escape(normalize(kw)) + r"\b", norm):
                return room_type
    return None


def _collect_texts(msp, ignore_layers: list) -> list:
    """Return [(Point, text)] for all TEXT / MTEXT entities."""
    texts = []
    for e in msp:
        t = e.dxftype()
        if t not in ("TEXT", "MTEXT"):
            continue
        if _is_ignored_layer(e.dxf.layer, ignore_layers):
            continue
        raw = e.dxf.text if t == "TEXT" else e.plain_text()
        raw = (raw or "").strip()
        if not raw:
            continue
        ins = e.dxf.insert
        texts.append((Point(ins.x, ins.y), raw))
    return texts


def detect_rooms(doc, layer_cfg: dict, rules_cfg: dict) -> tuple:
    """Return (rooms, warnings)."""
    warnings = []
    msp = doc.modelspace()
    factor = {"mm": 1e-6, "cm": 1e-4, "m": 1.0}[rules_cfg.get("drawing_unit", "mm")]

    room_layers = layer_cfg.get("room_layers", {})
    boundary_layers = room_layers.get("boundary_layers", [])
    ignore_layers = layer_cfg.get("ignore_layers", [])

    # 1. Collect candidate polygons, preferring dedicated boundary layers
    boundary_candidates, all_candidates = [], []
    for e in msp:
        if e.dxftype() not in ("LWPOLYLINE", "POLYLINE", "HATCH"):
            continue
        layer = e.dxf.layer
        if _is_ignored_layer(layer, ignore_layers):
            continue
        for pts in _polygons_from_entity(e):
            all_candidates.append(pts)
            if _layer_matches(layer, boundary_layers):
                boundary_candidates.append(pts)

    if boundary_candidates:
        candidates = boundary_candidates
    else:
        candidates = all_candidates
        warnings.append(
            "No room boundary layer matched. Using all closed shapes; "
            "check layer_mapping.json -> room_layers.boundary_layers."
        )

    # 2. Build polygons, filter by area, remove duplicates
    polygons, seen = [], set()
    for pts in candidates:
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or poly.geom_type != "Polygon":
            continue
        area_m2 = poly.area * factor
        if not (MIN_ROOM_AREA_M2 <= area_m2 <= MAX_ROOM_AREA_M2):
            continue
        key = (round(poly.centroid.x, 1), round(poly.centroid.y, 1), round(area_m2, 2))
        if key in seen:
            continue
        seen.add(key)
        polygons.append((poly, pts, area_m2))

    polygons.sort(key=lambda item: item[2])  # smallest first

    # 3. Assign text labels to the smallest room containing each text
    texts = _collect_texts(msp, ignore_layers)
    labels = {i: [] for i in range(len(polygons))}
    for point, raw in texts:
        for i, (poly, _pts, _area) in enumerate(polygons):
            if poly.contains(point):
                labels[i].append(raw)
                break

    # 4. Create Room objects
    keywords = rules_cfg.get("room_type_keywords", {})
    rooms = []
    for i, (poly, pts, area_m2) in enumerate(polygons):
        room_type, name = None, None
        for text in labels[i]:
            guessed = _guess_room_type(text, keywords)
            if guessed:
                room_type, name = guessed, text
                break
        if name is None:
            # Use the longest non-numeric text as a name
            names = [t for t in labels[i] if not re.fullmatch(r"[\d\.\,\s]+", t)]
            if names:
                name = max(names, key=len)

        label_found = name is not None
        rooms.append(
            Room(
                id=f"R{i + 1:03d}",
                name=name or f"Room {i + 1}",
                room_type=room_type or "other",
                area_m2=round(area_m2, 2),
                coords=[(round(x, 3), round(y, 3)) for x, y in pts],
                label_found=label_found,
                confidence=0.8 if room_type else (0.5 if label_found else 0.3),
            )
        )

    if not rooms:
        warnings.append("No rooms detected. Check units, layers, or draw rooms manually.")
    return rooms, warnings