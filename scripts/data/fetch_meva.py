#!/usr/bin/env python3
"""Fetch the MEVA subset this project uses. No credentials: the bucket is public.

Subcommands (all write under --raw-dir, which must live OUTSIDE OneDrive /
the repo for multi-GB video; default data/raw is gitignored):

  index    list s3://mevadata-public-01/<prefix> over HTTPS -> <raw>/meva/s3_index.json
  repo     shallow, sparse clone of gitlab.kitware.com/meva/meva-data-repo
           (metadata + kitware annotations only; skips the 3.6 GB contrib dir)
  ground   download the coarse 3-D ground mesh used for pixel->ground mapping
  clips    download the 5-minute clips for --slot(s) x --cameras, resumable,
           size-checked against the S3 listing

Example:
  python scripts/data/fetch_meva.py --raw-dir ~/aum-data/raw index
  python scripts/data/fetch_meva.py --raw-dir ~/aum-data/raw clips \
      --slots 2018-03-15.15-35-00 --cameras G341,G436,G506,G340
License: MEVA is CC BY 4.0 (https://mevadata.org/). Attribution:
"'Multiview Extended Video with Activities' (MEVA) dataset by Kitware Inc. and
the Intelligence Advanced Research Projects Activity (IARPA)".
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

BUCKET_URL = "https://mevadata-public-01.s3.amazonaws.com/"
REPO_URL = "https://gitlab.kitware.com/meva/meva-data-repo.git"
GROUND_KEY = "mutc-3d-model/model_segmentations/coarse/background.ply"
VIDEO_PREFIX = "drops-123-r13/"
_NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}

sys.path.insert(0, str(Path(__file__).resolve().parent))
from meva_annotations import load_clip_table, parse_clip_name


def list_bucket(prefix: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    token = None
    with httpx.Client(timeout=60) as client:
        while True:
            params = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                params["continuation-token"] = token
            r = client.get(BUCKET_URL, params=params)
            r.raise_for_status()
            root = ET.fromstring(r.content)
            for ct in root.findall("s:Contents", _NS):
                out.append((ct.find("s:Key", _NS).text, int(ct.find("s:Size", _NS).text)))
            if root.find("s:IsTruncated", _NS).text == "true":
                token = root.find("s:NextContinuationToken", _NS).text
            else:
                return out


def download(url: str, dest: Path, expected_size: int | None = None) -> int:
    """Resumable download. Returns bytes fetched in this call."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    if dest.exists() and (expected_size is None or dest.stat().st_size == expected_size):
        return 0
    have = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    fetched = 0
    with (
        httpx.Client(timeout=httpx.Timeout(60, read=300), follow_redirects=True) as client,
        client.stream("GET", url, headers=headers) as r,
    ):
        if r.status_code == 200 and have:
            have = 0  # server ignored the range; restart
        r.raise_for_status()
        with open(part, "ab" if have else "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
                fetched += len(chunk)
    size = part.stat().st_size
    if expected_size is not None and size != expected_size:
        raise RuntimeError(f"{dest.name}: got {size} bytes, expected {expected_size}")
    part.replace(dest)
    return fetched


def cmd_index(args: argparse.Namespace) -> None:
    keys = list_bucket(args.prefix)
    out = Path(args.raw_dir) / "meva" / "s3_index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(keys))
    print(f"{len(keys)} objects, {sum(s for _, s in keys) / 1e9:.1f} GB -> {out}")


def cmd_repo(args: argparse.Namespace) -> None:
    dest = Path(args.repo_dir) if args.repo_dir else Path(args.raw_dir) / "meva-data-repo"
    if dest.exists():
        print(f"exists: {dest}")
        return
    subprocess.run(
        ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse", REPO_URL, str(dest)],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(dest),
            "sparse-checkout",
            "set",
            "metadata",
            "documents",
            "annotation/DIVA-phase-2/MEVA/kitware",
            "annotation/DIVA-phase-2/MEVA/kitware-meva-training",
        ],
        check=True,
    )
    print(f"cloned -> {dest}")


def cmd_ground(args: argparse.Namespace) -> None:
    dest = Path(args.raw_dir) / "meva" / "ground_background_coarse.ply"
    n = download(BUCKET_URL + GROUND_KEY, dest)
    print(f"{dest} ({n / 1e6:.1f} MB fetched)")


def resolve_clips(
    index: list[tuple[str, int]], repo: Path, slots: list[str], cameras: list[str]
) -> list[tuple[str, int]]:
    table = load_clip_table(repo)
    by_name = {Path(k).name.replace(".r13.avi", ""): (k, s) for k, s in index}
    wanted = []
    for clip, row in table.items():
        cn = parse_clip_name(clip)
        if row.slot in slots and cn.camera in cameras and clip in by_name:
            wanted.append(by_name[clip])
    return sorted(wanted)


def cmd_clips(args: argparse.Namespace) -> None:
    raw = Path(args.raw_dir)
    index = json.loads((raw / "meva" / "s3_index.json").read_text())
    repo = Path(args.repo_dir) if args.repo_dir else raw / "meva-data-repo"
    wanted = resolve_clips(index, repo, args.slots.split(","), args.cameras.split(","))
    total = sum(s for _, s in wanted)
    print(f"{len(wanted)} clips, {total / 1e9:.2f} GB")
    if args.dry_run:
        for k, s in wanted:
            print(f"  {k} {s / 1e6:.0f} MB")
        return
    for key, size in wanted:
        dest = raw / "meva" / "video" / Path(key).name
        n = download(BUCKET_URL + key, dest, size)
        print(f"  {'got' if n else 'have'} {dest.name} {size / 1e6:.0f} MB", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--raw-dir", default="data/raw")
    ap.add_argument(
        "--repo-dir", default=None, help="meva-data-repo checkout (default <raw>/meva-data-repo)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("--prefix", default=VIDEO_PREFIX)
    sub.add_parser("repo")
    sub.add_parser("ground")
    p = sub.add_parser("clips")
    p.add_argument(
        "--slots", required=True, help="comma list of reference slots, e.g. 2018-03-15.15-35-00"
    )
    p.add_argument("--cameras", required=True, help="comma list, e.g. G341,G436,G506,G340")
    p.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    {"index": cmd_index, "repo": cmd_repo, "ground": cmd_ground, "clips": cmd_clips}[args.cmd](args)


if __name__ == "__main__":
    main()
