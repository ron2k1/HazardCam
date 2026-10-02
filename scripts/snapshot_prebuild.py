#!/usr/bin/env python3
"""Record the exact pre-event state in ``artifacts/PREBUILD_SNAPSHOT.json``.

Hashes every git-tracked file as it is on disk, plus the gitignored media the demo
needs (``data/prepared/**/*.mp4``), and records the commit and whether the tree was
clean. ``verify_event_delta.sh`` diffs event-day work against ``git_commit``.

Tracked files come from ``git ls-files``, so virtualenvs, node_modules, build output and
run directories are never walked, and paths are POSIX on every OS.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "PREBUILD_SNAPSHOT.json"
MEDIA_GLOB = "data/prepared/**/*.mp4"
CHUNK = 1 << 20


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _row(rel: str) -> dict[str, object] | None:
    path = ROOT / rel
    if not path.is_file():  # tracked but deleted in the working tree
        return None
    return {"path": rel, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def main() -> int:
    out_rel = OUT.relative_to(ROOT).as_posix()
    tracked = [p for p in _git("ls-files", "-z").split("\0") if p and p != out_rel]
    media = sorted(p.relative_to(ROOT).as_posix() for p in ROOT.glob(MEDIA_GLOB))
    status = [line for line in _git("status", "--porcelain").splitlines() if line]
    files = [r for r in map(_row, tracked) if r]
    media_rows = [r for r in map(_row, media) if r]
    snapshot = {
        "captured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD").strip(),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD").strip(),
        "worktree_clean": not status,
        "uncommitted": status,
        "files": sorted(files, key=lambda r: str(r["path"])),
        "untracked_media": media_rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        f"Wrote {out_rel}: {len(files)} tracked files, {len(media_rows)} media files, "
        f"commit {snapshot['git_commit'][:10]}, clean={snapshot['worktree_clean']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
