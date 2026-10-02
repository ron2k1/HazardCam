#!/usr/bin/env python3
"""Candidate-window finder skeleton.

Worker T05 should implement:
- sample synchronized videos at low FPS
- calculate grayscale frame-difference or optical-flow energy
- normalize per camera
- cross-correlate timelines
- rank windows where multiple cameras react within a configurable tolerance

Keep this CPU-friendly so it can run on the optional 16 GB SSH worker.
"""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario-dir', required=True)
    ap.add_argument('--fps', type=float, default=2.0)
    ap.add_argument('--window', type=float, default=2.0)
    ap.parse_args()
    raise SystemExit('T05 TODO: implement candidate scoring')


if __name__ == '__main__':
    main()
