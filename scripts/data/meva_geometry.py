#!/usr/bin/env python3
"""MEVA camera geometry: KRTD parsing, ground model, pixel <-> ground mapping.

MEVA KF1 outdoor cameras are registered in one east-north-up (ENU) frame in
meters, origin lat 39.04977294, lon -85.52924953, 205 m above the WGS84
ellipsoid (meva-data-repo/metadata/camera-models/krtd/README.md). The KRTD
files hold K (intrinsics), R (world->camera rotation), T (translation) and D
(OpenCV distortion). A world point X maps to camera coords R @ X + T, so the
camera center is C = -R^T T and the optical axis in world coords is R[2].

The ground is taken from the MEVA 3-D model (mutc-3d-model, same ENU frame):
vertices are binned into a height grid and rays are marched until they drop
below it. That is enough for coarse (meter-level) event locations; it is not
a survey-grade intersection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ENU_ORIGIN = {"lat": 39.04977294, "lon": -85.52924953, "height_m_wgs84": 205.0}

_PLY_TYPES = {
    "float": "<f4",
    "float32": "<f4",
    "double": "<f8",
    "float64": "<f8",
    "uchar": "u1",
    "uint8": "u1",
    "char": "i1",
    "int8": "i1",
    "ushort": "<u2",
    "uint16": "<u2",
    "short": "<i2",
    "int16": "<i2",
    "uint": "<u4",
    "uint32": "<u4",
    "int": "<i4",
    "int32": "<i4",
}


@dataclass(frozen=True)
class Krtd:
    K: np.ndarray
    R: np.ndarray
    T: np.ndarray
    D: np.ndarray

    @property
    def center(self) -> np.ndarray:
        return -self.R.T @ self.T

    @property
    def axis(self) -> np.ndarray:
        return self.R[2].copy()


def load_krtd(path: Path) -> Krtd:
    nums = [float(x) for x in Path(path).read_text().split()]
    K = np.array(nums[0:9]).reshape(3, 3)
    R = np.array(nums[9:18]).reshape(3, 3)
    T = np.array(nums[18:21])
    D = np.array(nums[21:])
    # OpenCV accepts 4, 5, 8, 12 or 14 coefficients; pad short/odd vectors with zeros.
    n = next(k for k in (4, 5, 8, 12, 14) if k >= max(len(D), 4))
    D = np.concatenate([D, np.zeros(n - len(D))])
    return Krtd(K=K, R=R, T=T, D=D)


def compass_heading(vec_enu: np.ndarray) -> float:
    """Compass bearing of the horizontal part of an ENU vector: 0 = north, 90 = east."""
    return math.degrees(math.atan2(float(vec_enu[0]), float(vec_enu[1]))) % 360.0


def horizontal_fov_deg(cam: Krtd, width: int) -> float:
    return math.degrees(2.0 * math.atan((width / 2.0) / cam.K[0, 0]))


def read_ply_vertices(path: Path) -> np.ndarray:
    """Return an (N, 3) float array of vertex xyz from an ascii or binary-LE PLY."""
    raw = Path(path).read_bytes()
    end = raw.index(b"end_header") + len(b"end_header")
    while raw[end : end + 1] in (b"\r", b"\n"):
        end += 1
    header = raw[:end].decode("ascii", "replace").splitlines()
    fmt, n_vert, props, in_vertex = "ascii", 0, [], False
    for line in header:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "format":
            fmt = parts[1]
        elif parts[0] == "element":
            in_vertex = parts[1] == "vertex"
            if in_vertex:
                n_vert = int(parts[2])
        elif parts[0] == "property" and in_vertex:
            if parts[1] == "list":
                raise ValueError("list properties on vertices are not supported")
            props.append((parts[2], _PLY_TYPES[parts[1]]))
    if fmt == "ascii":
        rows = raw[end:].decode("ascii").split("\n")[:n_vert]
        arr = np.array([[float(v) for v in r.split()[: len(props)]] for r in rows])
        names = [p[0] for p in props]
        return arr[:, [names.index("x"), names.index("y"), names.index("z")]]
    if fmt != "binary_little_endian":
        raise ValueError(f"unsupported PLY format {fmt}")
    dtype = np.dtype(props)
    verts = np.frombuffer(raw, dtype=dtype, count=n_vert, offset=end)
    return np.stack([verts["x"], verts["y"], verts["z"]], axis=1).astype(np.float64)


class GroundModel:
    """Height grid over the site. Each cell keeps a low percentile of vertex z,
    which favors the walking surface over roofs and trees."""

    def __init__(self, xyz: np.ndarray, cell_m: float = 1.0, percentile: float = 10.0):
        self.cell = cell_m
        self.x0 = float(np.floor(xyz[:, 0].min()))
        self.y0 = float(np.floor(xyz[:, 1].min()))
        ix = ((xyz[:, 0] - self.x0) / cell_m).astype(int)
        iy = ((xyz[:, 1] - self.y0) / cell_m).astype(int)
        self.nx, self.ny = int(ix.max()) + 1, int(iy.max()) + 1
        grid = np.full((self.ny, self.nx), np.nan)
        order = np.lexsort((xyz[:, 2], iy * self.nx + ix))
        keys = (iy * self.nx + ix)[order]
        zs = xyz[order, 2]
        bounds = np.flatnonzero(np.diff(keys)) + 1
        for chunk_keys, chunk_z in zip(np.split(keys, bounds), np.split(zs, bounds)):
            k = int(chunk_keys[0])
            grid[k // self.nx, k % self.nx] = np.percentile(chunk_z, percentile)
        self.grid = grid
        self.fallback = float(np.nanmedian(grid))

    def height(self, x: float, y: float) -> float:
        i = int((y - self.y0) / self.cell)
        j = int((x - self.x0) / self.cell)
        if 0 <= i < self.ny and 0 <= j < self.nx:
            v = self.grid[i, j]
            if not np.isnan(v):
                return float(v)
            win = self.grid[max(0, i - 3) : i + 4, max(0, j - 3) : j + 4]
            if np.isfinite(win).any():
                return float(np.nanmedian(win))
        return self.fallback


def pixel_ray(cam: Krtd, u: float, v: float) -> np.ndarray:
    """Unit world-frame direction of the ray through pixel (u, v), distortion removed."""
    pts = cv2.undistortPoints(np.array([[[u, v]]], dtype=np.float64), cam.K, cam.D)
    xn, yn = pts[0, 0]
    d = cam.R.T @ np.array([xn, yn, 1.0])
    return d / np.linalg.norm(d)


def ray_to_ground(
    cam: Krtd,
    direction: np.ndarray,
    ground: GroundModel | None,
    max_range_m: float = 400.0,
    step_m: float = 0.25,
    flat_z: float = 0.0,
) -> np.ndarray | None:
    """Intersect a ray with the ground model (or the plane z=flat_z when ground is None)."""
    c = cam.center
    if ground is None:
        if direction[2] >= -1e-6:
            return None
        t = (flat_z - c[2]) / direction[2]
        return c + t * direction if 0 < t <= max_range_m else None
    prev_t, prev_gap = 0.0, c[2] - ground.height(c[0], c[1])
    t = step_m
    while t <= max_range_m:
        p = c + t * direction
        gap = p[2] - ground.height(p[0], p[1])
        if gap <= 0:
            # linear refine between the last above-ground sample and this one
            frac = prev_gap / (prev_gap - gap) if prev_gap != gap else 1.0
            tt = prev_t + frac * (t - prev_t)
            return c + tt * direction
        prev_t, prev_gap = t, gap
        t += step_m if t < 60 else step_m * 4
    return None


def pixel_to_ground(cam: Krtd, u: float, v: float, ground: GroundModel | None) -> np.ndarray | None:
    return ray_to_ground(cam, pixel_ray(cam, u, v), ground)


def project(cam: Krtd, xyz: np.ndarray) -> tuple[float, float, float]:
    """Project a world point; returns (u, v, depth). depth <= 0 means behind the camera."""
    xc = cam.R @ np.asarray(xyz, dtype=np.float64) + cam.T
    rvec, _ = cv2.Rodrigues(cam.R)
    uv, _ = cv2.projectPoints(
        np.asarray(xyz, dtype=np.float64).reshape(1, 1, 3), rvec, cam.T, cam.K, cam.D
    )
    return float(uv[0, 0, 0]), float(uv[0, 0, 1]), float(xc[2])


def in_view(cam: Krtd, xyz: np.ndarray, width: int, height: int, margin_px: float = 0.0) -> bool:
    u, v, depth = project(cam, xyz)
    return (
        depth > 0 and -margin_px <= u < width + margin_px and -margin_px <= v < height + margin_px
    )


def footprint(
    cam: Krtd,
    width: int,
    height: int,
    ground: GroundModel | None,
    n: int = 12,
    max_range_m: float = 120.0,
) -> list[list[float]]:
    """Ground polygon (x, y) seen by the camera, clipped at max_range_m.

    Rays along the image border that miss the ground (sky, horizon) are clipped
    to max_range_m along their horizontal bearing so the polygon stays closed.
    """
    border = (
        [(width * i / n, height - 1) for i in range(n + 1)]
        + [(width - 1, height * (n - i) / n) for i in range(n + 1)]
        + [(width * (n - i) / n, 0) for i in range(n + 1)]
        + [(0, height * i / n) for i in range(n + 1)]
    )
    c = cam.center
    poly = []
    for u, v in border:
        d = pixel_ray(cam, u, v)
        p = ray_to_ground(cam, d, ground, max_range_m=max_range_m)
        if p is None or np.hypot(p[0] - c[0], p[1] - c[1]) > max_range_m:
            h = np.array([d[0], d[1]])
            h = h / (np.linalg.norm(h) or 1.0)
            p = np.array([c[0] + h[0] * max_range_m, c[1] + h[1] * max_range_m, 0.0])
        poly.append([round(float(p[0]), 2), round(float(p[1]), 2)])
    return poly


def camera_summary(cam: Krtd, width: int, height: int, ground: GroundModel | None) -> dict:
    c = cam.center
    gz = ground.height(c[0], c[1]) if ground is not None else 0.0
    return {
        "position_enu_m": [round(float(c[0]), 2), round(float(c[1]), 2), round(float(c[2]), 2)],
        "height_above_ground_m": round(float(c[2] - gz), 2),
        "heading_deg": round(compass_heading(cam.axis), 1),
        "pitch_deg": round(math.degrees(math.asin(float(cam.axis[2]))), 1),
        "fov_deg": round(horizontal_fov_deg(cam, width), 1),
    }
