"""TEMPORARY fixture replay executor (P03). P10 replaces it with the dev-sequence harness.

Replays the recorded fixture observations and hypothesis through the full SSE
catalog so the API and dashboard can be exercised before the real harness lands.
It makes no model calls and samples no video: ``camera.frames.sampled`` carries an
empty frame list, the single evidence cluster spans all fixture observations, and
the region candidate is the fixture hypothesis region when it names a scenario
zone. Every event is labelled ``fixture-replay`` so it cannot pass for a real run.

Fixtures resolve like the fixture adapters: ``data/fixtures/<scenario_id>/<name>``
first, then ``data/fixtures/<name>``. Observation batches are matched to visible
cameras by camera id; a camera with no recorded batch replays zero observations.
"""

from __future__ import annotations

import itertools
import json
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from statistics import fmean
from typing import Any

from apps.api.schemas import (
    REPO_ROOT,
    EvidenceCluster,
    EvidenceItem,
    Hypothesis,
    ObservationBatch,
    RegionCandidate,
    Scenario,
)

HARNESS = "fixture-replay"
FIXTURES_DIR = REPO_ROOT / "data" / "fixtures"
OBSERVATIONS_FILE = "qwen_observations.json"
HYPOTHESIS_FILE = "final_hypothesis.json"
SEQUENCE = ("inspect_camera", "build_evidence_bundle", "reason_hypothesis", "submit_hypothesis")


class FixtureReplayExecutor:
    def __init__(self, fixtures_dir: Path = FIXTURES_DIR, sample_fps: float = 1.0) -> None:
        self.fixtures_dir = fixtures_dir
        self.sample_fps = sample_fps

    def _fixture(self, scenario_id: str, name: str) -> Path:
        scoped = self.fixtures_dir / scenario_id / name
        return scoped if scoped.is_file() else self.fixtures_dir / name

    def __call__(
        self,
        scenario: Scenario,
        profile_name: str,
        emit: Callable[[str, dict[str, Any]], None],
        run_dir: Path,
        pace_s: float,
    ) -> Hypothesis:
        view = scenario.model_view()  # nothing below touches the ground-truth camera
        raw_batches = json.loads(
            self._fixture(view.id, OBSERVATIONS_FILE).read_text(encoding="utf-8")
        )
        hypothesis = Hypothesis.model_validate_json(
            self._fixture(view.id, HYPOTHESIS_FILE).read_bytes()
        )
        call_ids = itertools.count(1)

        def step(event_type: str, payload: dict[str, Any]) -> None:
            emit(event_type, payload)
            if pace_s:
                time.sleep(pace_s)

        @contextmanager
        def tool(name: str, args_summary: str) -> Iterator[dict[str, str]]:
            call_id = f"call_{next(call_ids):03d}"
            step("tool.started", {"call_id": call_id, "tool": name, "args_summary": args_summary})
            started, result = time.perf_counter(), {"summary": ""}
            done = {"call_id": call_id, "tool": name}
            try:
                yield result
            except Exception as exc:
                latency = int((time.perf_counter() - started) * 1000)
                failed = {"ok": False, "latency_ms": latency, "result_summary": ""}
                step("tool.completed", done | failed | {"error": type(exc).__name__})
                raise
            latency = int((time.perf_counter() - started) * 1000)
            step(
                "tool.completed",
                done | {"ok": True, "latency_ms": latency, "result_summary": result["summary"]},
            )

        step(
            "run.started",
            {
                "scenario_id": view.id,
                "profile": profile_name,
                "camera_ids": [cam.id for cam in view.cameras],
                "harness": HARNESS,
            },
        )
        step("orchestrator.started", {"harness": HARNESS, "agent": False, "sequence": SEQUENCE})

        evidence: list[EvidenceItem] = []
        for cam in view.cameras:
            with tool("inspect_camera", f"camera_id={cam.id}") as result:
                started = time.perf_counter()
                step("camera.started", {"camera_id": cam.id})
                step(
                    "camera.frames.sampled",
                    {"camera_id": cam.id, "sample_fps": self.sample_fps, "frames": []},
                )
                batch = ObservationBatch.model_validate(
                    raw_batches.get(cam.id) or {"camera_id": cam.id}
                )
                for obs in batch.observations:
                    step("camera.observation", {"camera_id": cam.id, "observation": obs})
                    evidence.append(EvidenceItem(camera_id=cam.id, **obs.model_dump()))
                count = len(batch.observations)
                step(
                    "camera.complete",
                    {
                        "camera_id": cam.id,
                        "observation_count": count,
                        "latency_ms": int((time.perf_counter() - started) * 1000),
                        "adapter": HARNESS,
                    },
                )
                result["summary"] = f"{count} observation(s)"

        with tool("build_evidence_bundle", f"{len(evidence)} evidence item(s)") as result:
            step("fusion.started", {"evidence_count": len(evidence)})
            cluster = _single_cluster(evidence)
            if cluster:
                step("evidence.linked", {"cluster": cluster, "evidence": evidence})
            candidates = _zone_candidate(view.zones, hypothesis, cluster)
            step("triangulation.updated", {"candidates": candidates, "rays": []})
            result["summary"] = (
                f"{len(evidence)} evidence, {int(cluster is not None)} cluster, "
                f"{len(candidates)} region candidate(s)"
            )

        summary = f"{hypothesis.event_type} @ {hypothesis.region} ({hypothesis.confidence:.2f})"
        with tool("reason_hypothesis", f"{len(evidence)} evidence item(s)") as result:
            step("hypothesis.updated", {"hypothesis": hypothesis, "final": False})
            result["summary"] = summary
        with tool("submit_hypothesis", f"{len(hypothesis.evidence_ids)} cited evidence") as result:
            step("hypothesis.updated", {"hypothesis": hypothesis, "final": True})
            result["summary"] = summary
        return hypothesis


def _single_cluster(evidence: list[EvidenceItem]) -> EvidenceCluster | None:
    if not evidence:
        return None
    return EvidenceCluster(
        id="clu_fixture_01",
        t_start=min(e.t_start for e in evidence),
        t_end=max(e.t_end for e in evidence),
        evidence_ids=[e.id for e in evidence],
        camera_ids=sorted({e.camera_id for e in evidence}),
        score=round(fmean(e.confidence for e in evidence), 2),
    )


def _zone_candidate(zones, hypothesis: Hypothesis, cluster: EvidenceCluster | None) -> list:
    zone = next((z for z in zones if z.id == hypothesis.region), None)
    if zone is None:
        return []
    known = set(cluster.evidence_ids) if cluster else set()
    return [
        RegionCandidate(
            id=zone.id,
            label=zone.label,
            center=zone.center,
            radius_m=zone.radius_m,
            score=hypothesis.confidence,
            camera_ids=cluster.camera_ids if cluster else [],
            evidence_ids=[e for e in hypothesis.evidence_ids if e in known],
            method="zone_prior",
        )
    ]
