"""
PhotoS - Batch Rename

Rename (in place) or copy-rename image files using smart rename templates
({date}, {camera}, {seq}, ...) without re-compressing the image.
"""

import os
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .engine import _extract_exif_metadata, _has_path_traversal, _render_rename_pattern


def _load_meta(path: str) -> dict:
    """Extract EXIF metadata for rename templates, tolerating any open failure."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            return _extract_exif_metadata(img, path)
    except Exception:
        return {}


def _unique_target(target: str, overwrite: bool) -> str:
    """Return a target path that won't clobber an existing file."""
    if overwrite:
        return target
    p = Path(target)
    counter = 1
    while p.exists():
        p = p.with_name(f"{p.stem}_{counter}{p.suffix}")
        counter += 1
    return str(p)


def rename_files(
    paths: List[str],
    pattern: str,
    output_dir: Optional[str] = None,
    overwrite: bool = False,
    dry_run: bool = False,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> List[Dict]:
    """Rename (in place) or copy-rename a list of image files.

    Args:
        paths: Source image paths.
        pattern: Rename template (see _render_rename_pattern placeholders).
        output_dir: If set, copy each file to this directory with the new name
                    instead of renaming in place (copy2 preserves mtime).
        overwrite: Allow clobbering an existing target (otherwise _N suffix).
        dry_run: Compute the mapping without touching any file.
        progress_callback: Optional callback(current, total, path).

    Returns:
        List of dicts: {"input", "output", "status": "ok"|"error", "error"}.
    """
    results: List[Dict] = []
    total = len(paths)
    seq = 1

    for idx, path in enumerate(paths):
        meta = _load_meta(path)
        new_stem = _render_rename_pattern(pattern, meta, seq)
        seq += 1

        if _has_path_traversal(new_stem):
            # Defense-in-depth: EXIF-derived values are sanitized at the
            # source, but never let a rendered stem escape the target dir.
            results.append({"input": path, "output": "",
                            "status": "error",
                            "error": "pattern produced an unsafe filename"})
            continue

        src = Path(path)
        if not new_stem.strip():
            # A pure-EXIF template ({date}, {year}{month}{day}, ...) on a
            # file without EXIF renders an empty stem — that would produce
            # hidden ".png"/".png_1" files reported as ok. Fall back to the
            # original name (same fallback semantics as engine rename mode).
            new_stem = src.stem

        if output_dir:
            target = str(Path(output_dir) / f"{new_stem}{src.suffix}")
        else:
            target = str(src.with_name(f"{new_stem}{src.suffix}"))

        # Avoid clobbering (and never map a file onto itself via collision)
        target = _unique_target(target, overwrite)

        if progress_callback:
            progress_callback(idx + 1, total, path)

        if dry_run:
            results.append({"input": path, "output": target,
                            "status": "ok", "error": ""})
            continue

        try:
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                shutil.copy2(path, target)  # copy2 preserves mtime
            else:
                # os.replace: same-FS atomic, and overwrites an existing
                # target on every platform (os.rename raises FileExistsError
                # on Windows, silently breaking --overwrite there).
                os.replace(path, target)
            results.append({"input": path, "output": target,
                            "status": "ok", "error": ""})
        except Exception as e:
            results.append({"input": path, "output": target,
                            "status": "error", "error": str(e)})

    return results
