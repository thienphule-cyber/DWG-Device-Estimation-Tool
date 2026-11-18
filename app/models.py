"""Shared data models used by all modules."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from shapely.geometry import Polygon


@dataclass
class Room:
    id: str
    name: str
    room_type: str                      # key in estimation_rules.json, e.g. "bedroom"
    area_m2: float
    coords: list                        # [(x, y), ...] in drawing units
    zone: str = "Zone A"
    label_found: bool = False           # True if a text label was found inside the room
    confidence: float = 0.5

    @property
    def polygon(self) -> Polygon:
        poly = Polygon(self.coords)
        return poly if poly.is_valid else poly.buffer(0)


@dataclass
class Device:
    id: str
    device_type: str                    # lighting / switches / sockets / sensors / hvac
    block_name: str
    layer: str
    x: float
    y: float
    room_id: Optional[str] = None
    status: str = "Detected"
    confidence: float = 1.0


@dataclass
class EstimateItem:
    room_id: str
    device_type: str
    detected: int = 0
    estimated: int = 0
    recommended: int = 0
    reason: str = ""
    confidence: float = 0.5
    verified: bool = False              # set to True when the user confirms the item

    @property
    def total(self) -> int:
        return self.detected + self.estimated + self.recommended


@dataclass
class AnalysisResult:
    file_name: str
    rooms: list = field(default_factory=list)       # list[Room]
    devices: list = field(default_factory=list)     # list[Device]
    estimates: list = field(default_factory=list)   # list[EstimateItem]
    warnings: list = field(default_factory=list)    # list[str]
    whole_house: dict = field(default_factory=dict) # {device_type: fixed total}

    def room_by_id(self, room_id: str) -> Optional[Room]:
        return next((r for r in self.rooms if r.id == room_id), None)

    def to_dict(self) -> dict:
        data = asdict(self)
        for est_dict, est in zip(data["estimates"], self.estimates):
            est_dict["total"] = est.total
        return data