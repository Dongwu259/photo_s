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

# Built-in presets (name → options dict). Always available with zero setup —
# no user files written. A user-saved preset of the same name overrides the
# builtin (user wins), and delete_preset on a builtin is a no-op.
BUILTIN_PRESETS = {
    "lr-look": {
        "_description": (
            "LR 风格出片：S 曲线（提黑位/压高光）+ 自然饱和 + 导出锐化，"
            "在 rawpy 平淡基线之上接近 Lightroom 默认渲染"),
        # gentle S-curve: raised blacks, lifted midtones, soft highlight
        # compression — the contrast lives in the curve, not a linear slider
        "curves": "0,0;24,30;64,76;128,138;192,204;236,244;255,255",
        "contrast": 1.0,
        "saturation": 1.06,
        "vibrance": 0.08,
        # LR-style output-stage USM (radius scales with output resolution),
        # instead of the mid-pipeline ImageEnhance sharpen
        "export_sharpen": 1.0,
    },
}


def _builtin_options(name: str) -> Optional[ProcessOptions]:
    """Resolve a built-in preset to ProcessOptions, or None if unknown."""
    data = BUILTIN_PRESETS.get(name)
    if data is None:
        return None
    return ProcessOptions(**{
        k: v for k, v in data.items()
        if k in ProcessOptions.__dataclass_fields__
    })


def _ensure_dir():
    """Ensure the presets directory exists."""
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)


def _preset_path(name: str) -> Path:
    """Get the file path for a preset name."""
    safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
    return PRESETS_DIR / f"{safe}.json"


def list_presets() -> List[str]:
    """Return sorted list of available preset names (user + built-in).

    A user-saved preset shadows a built-in of the same name.
    """
    user = []
    if PRESETS_DIR.exists():
        for f in PRESETS_DIR.glob("*.json"):
            name = f.stem
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                desc = data.get("_description", "")
                user.append((name, desc))
            except Exception:
                pass
    user_names = {n for n, _ in user}
    builtin = [(n, d.get("_description", ""))
               for n, d in BUILTIN_PRESETS.items() if n not in user_names]
    return [f"{n} — {d}" if d else n for n, d in sorted(user + builtin)]


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
    _preset_path(name).write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                  encoding="utf-8")


def load_preset(name: str) -> Optional[ProcessOptions]:
    """Load a named preset and return a ProcessOptions instance.

    User-saved presets win; built-in presets are the fallback. Returns None
    if neither exists.
    """
    path = _preset_path(name)
    if not path.exists():
        # Try fuzzy match
        for f in PRESETS_DIR.glob("*.json"):
            if f.stem.lower() == name.lower().replace(" ", "_"):
                path = f
                break
        else:
            return _builtin_options(name)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _builtin_options(name)

    if not isinstance(data, dict):
        return _builtin_options(name)

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
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    count = 0
    for name, fields in data.items():
        if isinstance(fields, dict):
            save_preset(name, ProcessOptions(**{
                k: v for k, v in fields.items()
                if k in ProcessOptions.__dataclass_fields__
            }))
            count += 1
    return count
