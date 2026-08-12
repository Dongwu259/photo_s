"""
PhotoS - Preset Configuration Management

Save, load, list, and delete named preset configurations.
Presets are stored as JSON files in ~/.photos/presets/.
"""

import json
import os
from pathlib import Path
from typing import List, Optional
from dataclasses import asdict

from .engine import ProcessOptions

PRESETS_DIR = Path.home() / ".photos" / "presets"


def _ensure_dir():
    """Ensure the presets directory exists."""
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)


def _preset_path(name: str) -> Path:
    """Get the file path for a preset name."""
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
    return PRESETS_DIR / f"{safe}.json"


def list_presets() -> List[str]:
    """Return sorted list of available preset names."""
    if not PRESETS_DIR.exists():
        return []
    presets = []
    for f in PRESETS_DIR.glob("*.json"):
        name = f.stem
        try:
            data = json.loads(f.read_text())
            desc = data.get("_description", "")
            presets.append((name, desc))
        except Exception:
            pass
    return [f"{n} — {d}" if d else n for n, d in sorted(presets)]


def save_preset(name: str, options: ProcessOptions, description: str = ""):
    """Save a ProcessOptions config as a named preset."""
    _ensure_dir()
    data = asdict(options)
    data["_description"] = description
    data["_version"] = "1.0"
    # Remove non-serializable fields
    data.pop("output_sizes", None)  # handled separately
    if options.output_sizes:
        data["output_sizes"] = options.output_sizes
    _preset_path(name).write_text(json.dumps(data, indent=2, ensure_ascii=False))


def load_preset(name: str) -> Optional[ProcessOptions]:
    """Load a named preset and return a ProcessOptions instance.

    Returns None if the preset doesn't exist.
    """
    path = _preset_path(name)
    if not path.exists():
        # Try fuzzy match
        for f in PRESETS_DIR.glob("*.json"):
            if f.stem.lower() == name.lower().replace(" ", "_"):
                path = f
                break
        else:
            return None

    try:
        data = json.loads(path.read_text())
    except Exception:
        return None

    # Extract known fields; ignore metadata
    data.pop("_description", None)
    data.pop("_version", None)

    return ProcessOptions(**{
        k: v for k, v in data.items()
        if k in ProcessOptions.__dataclass_fields__
    })


def delete_preset(name: str) -> bool:
    """Delete a named preset. Returns True if deleted, False if not found."""
    path = _preset_path(name)
    if path.exists():
        path.unlink()
        return True
    return False


def import_presets_from_json(json_path: str) -> int:
    """Import presets from a JSON file (one object per preset name)."""
    data = json.loads(Path(json_path).read_text())
    count = 0
    for name, fields in data.items():
        if isinstance(fields, dict):
            save_preset(name, ProcessOptions(**{
                k: v for k, v in fields.items()
                if k in ProcessOptions.__dataclass_fields__
            }))
            count += 1
    return count
