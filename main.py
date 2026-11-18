"""Flask entry point: upload, edit, and export endpoints. State is kept in RAM (single user)."""
from __future__ import annotations

import os
import threading
import socket
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from werkzeug.utils import secure_filename

from app.device_detector import detect_devices
from app.dwg_reader import load_config, read_drawing
from app.estimator import DEVICE_TYPES, estimate_all, recalculate_room
from app.models import AnalysisResult
from app.report_generator import generate_report
from app.room_detector import detect_rooms
from app.zone_manager import assign_zones, set_room_zone

BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".dwg", ".dxf"}

app = Flask(__name__, static_folder="frontend", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB upload limit

# Single-user session state kept in RAM
_lock = threading.Lock()
_current: AnalysisResult | None = None
_rules_cfg: dict = {}


# ---------- Helpers ----------

def clear_temp() -> None:
    """Delete everything in temp/ (previous upload, DXF and report)."""
    for item in TEMP_DIR.iterdir():
        if item.is_file() and item.name != ".gitkeep":
            item.unlink()


def run_pipeline(file_path: Path, display_name: str) -> AnalysisResult:
    """Run the full analysis: read -> rooms -> zones -> devices -> estimates."""
    global _rules_cfg
    block_cfg = load_config("block_mapping.json")
    layer_cfg = load_config("layer_mapping.json")
    _rules_cfg = load_config("estimation_rules.json")

    doc = read_drawing(file_path, TEMP_DIR)
    rooms, room_warnings = detect_rooms(doc, layer_cfg, _rules_cfg)
    assign_zones(rooms)
    devices, device_warnings = detect_devices(doc, rooms, block_cfg, layer_cfg)
    estimates = estimate_all(rooms, devices, _rules_cfg)
    result = AnalysisResult(display_name, rooms, devices, estimates, room_warnings + device_warnings)
    # Freeze the whole-house totals at analysis time; later room edits do not change them
    result.whole_house = {
        t: sum(e.total for e in estimates if e.device_type == t) for t in DEVICE_TYPES
    }
    return result


def payload() -> dict:
    """Response format expected by frontend/app.js."""
    return {
        "result": _current.to_dict(),
        "room_types": list(_rules_cfg.get("rules", {}).keys()),
        "device_types": DEVICE_TYPES,
    }


def error(message: str, status: int = 400):
    return jsonify({"error": message}), status


def find_estimate(room_id: str, device_type: str):
    return next(
        (e for e in _current.estimates if e.room_id == room_id and e.device_type == device_type),
        None,
    )


# ---------- Routes ----------

@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/upload")
def upload():
    global _current
    file = request.files.get("file")
    if file is None or not file.filename:
        return error("No file uploaded.")

    safe_name = secure_filename(file.filename)
    if Path(safe_name).suffix.lower() not in ALLOWED_EXTENSIONS:
        return error("Only .dwg and .dxf files are supported.")

    with _lock:
        _current = None
        clear_temp()
        saved_path = TEMP_DIR / safe_name
        file.save(saved_path)
        try:
            _current = run_pipeline(saved_path, file.filename)
        except Exception as exc:  # report any parsing/conversion problem to the UI
            app.logger.exception("Analysis failed")
            return error(f"Analysis failed: {exc}", 500)
        return jsonify(payload())


@app.get("/results")
def results():
    with _lock:
        if _current is None:
            return error("No analysis yet.", 404)
        return jsonify(payload())


@app.post("/update")
def update():
    """Apply one edit. Supported payloads (all include room_id):
    - {name}                                  rename room
    - {zone}                                  move room to a zone
    - {room_type}                             change room type and recalculate that room
    - {device_type, estimated|recommended|verified}   edit one estimate row
    """
    data = request.get_json(silent=True) or {}
    room_id = data.get("room_id")

    with _lock:
        if _current is None:
            return error("No analysis yet.", 404)
        # Edit a whole-house total directly (independent of the rooms)
        if data.get("whole_house"):
            device_type = data.get("device_type")
            if device_type not in _current.whole_house:
                return error(f"Unknown device type: {device_type}")
            _current.whole_house[device_type] = max(0, int(data.get("value", 0)))
            return jsonify(payload())
        room = _current.room_by_id(room_id)
        if room is None:
            return error(f"Unknown room: {room_id}", 404)

        if "name" in data:
            room.name = str(data["name"]).strip() or room.name

        if "zone" in data:
            set_room_zone(_current.rooms, room_id, str(data["zone"]))

        if "room_type" in data:
            new_type = data["room_type"]
            if new_type not in _rules_cfg.get("rules", {}):
                return error(f"Unknown room type: {new_type}")
            room.room_type = new_type
            # A type chosen by the user is more reliable than a guessed one
            room.label_found = True
            room.confidence = 0.9
            recalculate_room(_current, room_id, _rules_cfg)

        if "device_type" in data:
            item = find_estimate(room_id, data["device_type"])
            if item is None:
                return error(f"Unknown device type: {data['device_type']}")
            for field in ("estimated", "recommended"):
                if field in data:
                    setattr(item, field, max(0, int(data[field])))
            if "verified" in data:
                item.verified = bool(data["verified"])

        return jsonify(payload())


@app.get("/export")
def export():
    with _lock:
        if _current is None:
            return error("No analysis yet.", 404)
        out_path = generate_report(_current, TEMP_DIR / "report.xlsx")
        download_name = Path(_current.file_name).stem + "_device_report.xlsx"
    return send_file(out_path, as_attachment=True, download_name=download_name)


# ---------- Run ----------

def find_free_port(start: int = 5001, attempts: int = 50) -> int:
    """Return the first free port starting from `start`."""
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            # Without SO_REUSEADDR, bind fails if the port is in use
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError(f"No free port found in range {start}-{start + attempts - 1}")

if __name__ == "__main__":
    preferred = int(os.environ.get("PORT", 5001))
    port = find_free_port(preferred)
    if port != preferred:
        print(f"Port {preferred} is busy, using {port} instead.")
    print(f"Open: http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)