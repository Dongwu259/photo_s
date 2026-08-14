"""
PhotoS - GPX Track Handling

Parses GPX track files (stdlib xml.etree) and interpolates a position for an
arbitrary timestamp, so photos can be geo-tagged from a recorded track.
"""

import math
import xml.etree.ElementTree as ET
from datetime import datetime
from functools import lru_cache
from typing import List, Optional, Tuple

Point = Tuple[datetime, float, float]  # (timestamp, latitude, longitude)


def parse_gpx(path: str) -> List[Point]:
    """Parse a GPX file into sorted (time, lat, lon) points.

    Matches <trkpt lat=".." lon=".."><time>ISO8601</time></trkpt> anywhere in
    the document (namespace-agnostic). Points without a time are skipped.
    Times are normalized to naive local (tzinfo stripped) so they compare
    against camera EXIF datetimes — assume the track and the photos share a
    timezone (typical for phones / action cameras).
    Returns [] for unreadable or empty files.
    """
    points = []
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return []
    for elem in tree.iter():
        tag = elem.tag.rsplit("}", 1)[-1]  # strip namespace prefix
        if tag != "trkpt":
            continue
        lat = elem.attrib.get("lat")
        lon = elem.attrib.get("lon")
        ts = None
        for child in elem:
            ctag = child.tag.rsplit("}", 1)[-1]
            if ctag == "time":
                try:
                    # fromisoformat accepts the trailing 'Z' only on
                    # Python ≥3.11; normalize to '+00:00' so py3.9/3.10 work
                    raw = child.text.strip()
                    if raw.endswith("Z") or raw.endswith("z"):
                        raw = raw[:-1] + "+00:00"
                    ts = datetime.fromisoformat(raw)
                    ts = ts.replace(tzinfo=None)  # naive UTC/local frame
                except (ValueError, AttributeError):
                    ts = None
        if lat is None or lon is None or ts is None:
            continue
        try:
            flat, flon = float(lat), float(lon)
        except ValueError:
            continue
        if not (math.isfinite(flat) and math.isfinite(flon)):
            continue  # "nan"/"inf" parse as float but aren't coordinates
        points.append((ts, flat, flon))
    return sorted(points, key=lambda p: p[0])


@lru_cache(maxsize=4)
def _cached_points(path: str) -> List[Point]:
    """Thread-safe parse cache — batch workers share one parse per GPX file."""
    return parse_gpx(path)


def position_at(path: str, ts: datetime) -> Optional[Tuple[float, float]]:
    """Interpolate (lat, lon) for a timestamp from a GPX file.

    Linear interpolation between the bracketing track points; None when the
    timestamp is outside the recorded range or the file is empty.
    """
    points = _cached_points(path)
    if not points:
        return None
    if ts < points[0][0] or ts > points[-1][0]:
        return None
    if len(points) == 1:
        return (points[0][1], points[0][2])

    for i in range(len(points) - 1):
        t0, lat0, lon0 = points[i]
        t1, lat1, lon1 = points[i + 1]
        if t0 <= ts <= t1:
            if t1 == t0:
                return (lat1, lon1)
            frac = (ts - t0).total_seconds() / (t1 - t0).total_seconds()
            lat = lat0 + (lat1 - lat0) * frac
            lon = lon0 + (lon1 - lon0) * frac
            return (lat, lon)
    return None


def to_dms_rational(deg: float) -> Tuple[Tuple[int, int], Tuple[int, int], Tuple[int, int]]:
    """Convert decimal degrees to piexif DMS rationals: ((d,1),(m,1),(s,100))."""
    # Work in integer centiseconds: a fractional second rounding up to 60.00
    # then carries into minutes (and minutes into degrees) automatically,
    # instead of emitting an invalid DMS like 12° 34' 60.00".
    total_cs = int(round(abs(deg) * 360000))  # 1° = 3600 s = 360000 cs
    d, rem = divmod(total_cs, 360000)
    m, s_cs = divmod(rem, 6000)
    return ((d, 1), (m, 1), (s_cs, 100))
