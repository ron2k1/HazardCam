#!/usr/bin/env python3
"""Readers for MEVA metadata and KPF annotations (meva-data-repo layout).

Clip names follow ``date.start.end.site.camera`` (e.g.
``2018-03-11.11-25-00.11-30-00.school.G328``); times are local wall-clock
seconds from the recorder. KPF files per clip:
``*.activities.yml`` (activity label, frame span, actor ids),
``*.types.yml`` (actor id -> person/vehicle/...),
``*.geom.yml`` (per-frame boxes ``x1 y1 x2 y2`` per actor id).
Frame numbers (``tsr0``/``ts0``) are 0-based video frame indices.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

_Loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

KITWARE_SUBDIRS = ("kitware", "kitware-meva-training")
_GEOM_ID1 = re.compile(r"'?id1'?:\s*(\d+)")
_GEOM_TS0 = re.compile(r"'?ts0'?:\s*(\d+)")
_GEOM_G0 = re.compile(
    r"'?g0'?:\s*'?(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)"
)


@dataclass(frozen=True)
class ClipName:
    name: str
    date: str
    start: str
    end: str
    site: str
    camera: str

    @property
    def start_dt(self) -> datetime:
        return datetime.strptime(f"{self.date} {self.start}", "%Y-%m-%d %H-%M-%S")

    @property
    def end_dt(self) -> datetime:
        end = datetime.strptime(f"{self.date} {self.end}", "%Y-%m-%d %H-%M-%S")
        return end if end >= self.start_dt else end + timedelta(days=1)


def parse_clip_name(name: str) -> ClipName:
    base = Path(name).name
    for suffix in (".r13.avi", ".avi", ".activities.yml", ".geom.yml", ".types.yml", ".krtd"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    date, start, end, site, camera = base.split(".")[:5]
    return ClipName(f"{date}.{start}.{end}.{site}.{camera}", date, start, end, site, camera)


@dataclass
class ClipTableRow:
    clip: str
    slot: str
    krtd: str | None
    camera_set: str
    ref_clip: str | None
    ref_offset_frames: int
    ref_precision_frames: int


def load_clip_table(repo: Path) -> dict[str, ClipTableRow]:
    rows: dict[str, ClipTableRow] = {}
    text = (repo / "metadata" / "meva-clip-camera-and-time-table.txt").read_text()
    for line in text.splitlines():
        f = line.split()
        if len(f) < 7:
            continue
        rows[f[0]] = ClipTableRow(
            clip=f[0],
            slot=f[1],
            krtd=None if f[2] == "no-camera-model" else f[2],
            camera_set=f[3],
            ref_clip=None
            if f[4].startswith("no-reference")
            else (f[0] if f[4] == "self" else f[4]),
            ref_offset_frames=int(f[5]),
            ref_precision_frames=int(f[6]),
        )
    return rows


def load_exterior_cameras(repo: Path) -> dict[str, set[str]]:
    """date -> set of camera ids that were exterior that day."""
    out: dict[str, set[str]] = {}
    for line in (repo / "metadata" / "meva-camera-daily-status.txt").read_text().splitlines()[1:]:
        parts = line.strip().split("|")
        if len(parts) == 3 and parts[2] == "ext":
            out.setdefault(parts[1], set()).add(parts[0])
    return out


def index_annotations(repo: Path) -> dict[str, Path]:
    """clip name -> path of its activities.yml (kitware eval-level first, then training)."""
    out: dict[str, Path] = {}
    base = repo / "annotation" / "DIVA-phase-2" / "MEVA"
    for sub in reversed(KITWARE_SUBDIRS):  # earlier entries win
        for p in (base / sub).rglob("*.activities.yml"):
            out[p.name[: -len(".activities.yml")]] = p
    return out


@dataclass
class Activity:
    clip: str
    label: str
    act_id: int
    start_frame: int
    end_frame: int
    actors: list[int] = field(default_factory=list)


def load_activities(path: Path) -> list[Activity]:
    clip = Path(path).name[: -len(".activities.yml")]
    docs = yaml.load(Path(path).read_text(), Loader=_Loader) or []
    out = []
    for entry in docs:
        act = entry.get("act") if isinstance(entry, dict) else None
        if not act:
            continue
        label = max(act["act2"].items(), key=lambda kv: kv[1])[0]
        span = act["timespan"][0]["tsr0"]
        actors = [a["id1"] for a in act.get("actors", [])]
        out.append(
            Activity(clip, label, int(act.get("id2", -1)), int(span[0]), int(span[1]), actors)
        )
    return out


def load_types(path: Path) -> dict[int, str]:
    docs = yaml.load(Path(path).read_text(), Loader=_Loader) or []
    out = {}
    for entry in docs:
        t = entry.get("types") if isinstance(entry, dict) else None
        if t:
            out[int(t["id1"])] = max(t["cset3"].items(), key=lambda kv: kv[1])[0]
    return out


def load_geom(
    path: Path, ids: set[int] | None = None
) -> dict[int, dict[int, tuple[float, float, float, float]]]:
    """actor id -> {frame: (x1, y1, x2, y2)}. Regex scan; geom files can be tens of MB."""
    out: dict[int, dict[int, tuple[float, float, float, float]]] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if "geom" not in line:
                continue
            m1, m2, m3 = _GEOM_ID1.search(line), _GEOM_TS0.search(line), _GEOM_G0.search(line)
            if not (m1 and m2 and m3):
                continue
            aid = int(m1.group(1))
            if ids is not None and aid not in ids:
                continue
            box = tuple(float(m3.group(i)) for i in range(1, 5))
            out.setdefault(aid, {})[int(m2.group(1))] = box  # type: ignore[assignment]
    return out


def sibling(path: Path, kind: str) -> Path:
    """activities.yml path -> sibling types.yml / geom.yml path."""
    name = Path(path).name.replace(".activities.yml", f".{kind}.yml")
    return Path(path).with_name(name)
