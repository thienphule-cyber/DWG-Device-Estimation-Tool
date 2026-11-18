"""Generate the Excel report with pandas + openpyxl."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

UNASSIGNED = "(Unassigned)"


def _room_lookup(result) -> dict:
    return {r.id: r for r in result.rooms}


def _whole_building_df(result) -> "pd.DataFrame":
    """Sum all rooms by device type: Detected / Estimated / Recommended / Total."""
    totals = {}
    for e in result.estimates:
        row = totals.setdefault(e.device_type, {"Detected": 0, "Estimated": 0, "Recommended": 0})
        row["Detected"] += e.detected
        row["Estimated"] += e.estimated
        row["Recommended"] += e.recommended

    rows = [{"Device": t, **v, "Total": sum(v.values())} for t, v in totals.items()]
    df = pd.DataFrame(rows)
    if not df.empty:
        grand = {"Device": "TOTAL"}
        for col in ("Detected", "Estimated", "Recommended", "Total"):
            grand[col] = int(df[col].sum())
        df = pd.concat([df, pd.DataFrame([grand])], ignore_index=True)
    return df

def build_dataframes(result) -> dict:
    rooms = _room_lookup(result)

    # Sheet 2: Zone / Room summary (main sheet)
    summary_rows = []
    for e in result.estimates:
        room = rooms[e.room_id]
        summary_rows.append(
            {
                "Zone": room.zone,
                "Room": room.name,
                "Room Type": room.room_type,
                "Area (m2)": room.area_m2,
                "Device": e.device_type,
                "Detected": e.detected,
                "Estimated": e.estimated,
                "Recommended": e.recommended,
                "Total": e.total,
            }
        )
    summary_df = pd.DataFrame(summary_rows)
    if not summary_df.empty:
        summary_df = summary_df.sort_values(["Zone", "Room", "Device"]).reset_index(drop=True)

    # Sheet 3: Device inventory
    inventory_rows = []
    for d in result.devices:
        room = rooms.get(d.room_id)
        inventory_rows.append(
            {
                "Device ID": d.id,
                "Device Type": d.device_type,
                "Block": d.block_name,
                "Layer": d.layer,
                "Zone": room.zone if room else UNASSIGNED,
                "Room": room.name if room else UNASSIGNED,
                "X": d.x,
                "Y": d.y,
                "Status": d.status,
                "Confidence": d.confidence,
            }
        )
    inventory_df = pd.DataFrame(inventory_rows)

    # Sheet 4: AI estimation details (only rows with estimated/recommended items)
    detail_rows = []
    for e in result.estimates:
        if e.estimated == 0 and e.recommended == 0:
            continue
        room = rooms[e.room_id]
        detail_rows.append(
            {
                "Zone": room.zone,
                "Room": room.name,
                "Device": e.device_type,
                "Estimated": e.estimated,
                "Recommended": e.recommended,
                "Reason": e.reason,
                "Confidence": e.confidence,
                "Verified": "Yes" if e.verified else "No",
            }
        )
    details_df = pd.DataFrame(detail_rows)

    # Sheet 1: Building summary
    totals = {
        "Detected": sum(e.detected for e in result.estimates),
        "Estimated": sum(e.estimated for e in result.estimates),
        "Recommended": sum(e.recommended for e in result.estimates),
    }
    building_rows = [
        ("Drawing file", result.file_name),
        ("Generated at", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Total zones", len({r.zone for r in result.rooms})),
        ("Total rooms", len(result.rooms)),
        ("Total detected devices", totals["Detected"]),
        ("Total estimated devices", totals["Estimated"]),
        ("Total recommended devices", totals["Recommended"]),
        ("Total devices", sum(totals.values())),
        ("Note", "Estimates are for support only and must be reviewed by a qualified engineer."),
    ]
    for i, w in enumerate(result.warnings, 1):
        building_rows.append((f"Warning {i}", w))
    building_df = pd.DataFrame(building_rows, columns=["Item", "Value"])

    return {
        "Building Summary": building_df,
        "Whole Building Devices": _whole_building_df(result),
        "Zone-Room Summary": summary_df,
        "Device Inventory": inventory_df,
        "AI Estimation Details": details_df,
    }


def _style_sheet(ws) -> None:
    header_fill = PatternFill("solid", fgColor="DDEBF7")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
    ws.freeze_panes = "A2"
    for col_idx, column in enumerate(ws.columns, 1):
        longest = max((len(str(c.value)) for c in column if c.value is not None), default=8)
        ws.column_dimensions[get_column_letter(col_idx)].width = min(longest + 2, 70)


def generate_report(result, out_path: str | Path) -> Path:
    """Write the Excel report and return its path."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    sheets = build_dataframes(result)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name, index=False)
            _style_sheet(writer.sheets[name])
    return out_path