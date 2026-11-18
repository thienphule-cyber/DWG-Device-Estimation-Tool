"""Read DWG/DXF files. DWG is converted to DXF with LibreDWG (dwg2dxf)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import ezdxf
from ezdxf import recover

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

# Multiply drawing-unit area by this factor to get square meters
AREA_FACTORS = {"mm": 1e-6, "cm": 1e-4, "m": 1.0}


def load_config(name: str) -> dict:
    """Load a JSON file from the config folder."""
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def area_factor(unit: str) -> float:
    if unit not in AREA_FACTORS:
        raise ValueError(f"Unsupported drawing unit: {unit}")
    return AREA_FACTORS[unit]


def convert_dwg_to_dxf(dwg_path: str | Path, out_dir: str | Path) -> Path:
    """Convert a DWG file to DXF using the dwg2dxf command line tool."""
    exe = shutil.which("dwg2dxf")
    if exe is None:
        raise RuntimeError(
            "dwg2dxf not found. Install it with 'brew install libredwg' "
            "or upload a DXF file instead."
        )

    dwg_path = Path(dwg_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (dwg_path.stem + ".dxf")

    # dwg2dxf may return a non-zero code on warnings, so check the output file instead
    result = subprocess.run(
        [exe, "-y", "-o", str(out_path), str(dwg_path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(
            "DWG conversion failed (output is empty). The DWG version may not be "
            "supported by LibreDWG. Try exporting DXF from CAD.\n" + result.stderr[-500:]
        )
    return out_path


def read_drawing(file_path: str | Path, temp_dir: str | Path = "temp"):
    """Return an ezdxf document from a .dwg or .dxf file."""
    file_path = Path(file_path)
    suffix = file_path.suffix.lower()

    if suffix == ".dwg":
        dxf_path = convert_dwg_to_dxf(file_path, temp_dir)
    elif suffix == ".dxf":
        dxf_path = file_path
    else:
        raise ValueError("Only .dwg and .dxf files are supported.")

    try:
        return ezdxf.readfile(str(dxf_path))
    except (ezdxf.DXFError, IOError):
        # Fall back to recovery mode for slightly damaged files
        doc, _auditor = recover.readfile(str(dxf_path))
        return doc


def drawing_info(doc) -> dict:
    """Basic information used for the Building Summary sheet and for debugging."""
    from collections import Counter

    msp = doc.modelspace()
    counts = Counter(e.dxftype() for e in msp)
    return {
        "layers": len(doc.layers),
        "entities": len(msp),
        "entity_types": dict(counts.most_common(10)),
        "blocks": [b.name for b in doc.blocks if not b.name.startswith("*")],
    }