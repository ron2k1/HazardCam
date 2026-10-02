"""Run-scoped tool bindings shared by the dev harness and the event-day agent.

A ``ToolSession`` holds one run's state (sampled frames, observation batches, the
evidence bundle, hypotheses) so callers pass only the small arguments described in
``contracts/tools.schema.json``. Each tool method:

* emits ``tool.started``, its domain events, then ``tool.completed``
  (ordering rules in ``contracts/SSE_EVENTS.md``);
* returns the typed result whose JSON form is ``$defs/<tool>_result``;
* on failure still closes its tool pair (``ok: false``) and raises ``ToolCallError``
  whose ``stage`` is the tool name and whose message says how to correct the call.

The session only binds tools. Which tool runs next is the caller's decision: a fixed
order in ``harness/dev_sequence.py``, the agent's own policy on event day.

Ground-truth rule: the session holds a ``ModelScenarioView`` only, and never echoes a
camera id that is not a visible camera into an event or error message. Messages for a
malformed call are built from the schema, never from the argument values.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from itertools import count
from pathlib import Path
from typing import Any, NoReturn, TypeVar

from jsonschema.exceptions import ValidationError, best_match

from apps.api.schemas import (
    REPO_ROOT,
    EvidenceBundle,
    EvidenceCluster,
    EvidenceItem,
    FrameRef,
    GroundTruthAccessError,
    Hypothesis,
    MediaManifest,
    ModelCamera,
    ModelScenarioView,
    ObservationBatch,
)
from apps.api.schemas.contracts import def_validator
from inference.base import (
    PerceptionAdapter,
    PerceptionOptions,
    ReasoningAdapter,
    ReasoningOptions,
    get_perception_adapter,
    get_reasoning_adapter,
)
from inference.profiles import ModelProfile
from tools.correlate import correlate_observations, fusion_notes
from tools.inspect_camera import inspect_camera
from tools.reason_hypothesis import reason_hypothesis
from tools.sample_video import sample_video
from tools.submit import submit_hypothesis
from tools.supporting_frames import get_supporting_frames
from tools.triangulate import assemble_evidence_bundle, evidence_rays, triangulate_region

TOOL_NAMES = (
    "sample_video",
    "inspect_camera",
    "correlate_observations",
    "triangulate_region",
    "reason_hypothesis",
    "get_supporting_frames",
    "submit_hypothesis",
)
NO_ARGS = frozenset({"correlate_observations", "triangulate_region", "reason_hypothesis"})
TOOL_CONTRACT = "tool_call"
UNKNOWN_TOOL = "unknown_tool"
NOT_VISIBLE = "not_visible"
FRAMES_DIRNAME = "frames"
MAX_ERROR_CHARS = 240

Emit = Callable[[str, dict[str, Any]], None]
FrameUrl = Callable[[str, int], str]
T = TypeVar("T")


class ToolCallError(RuntimeError):
    """A tool call failed. ``stage`` names the tool (the API reports it in run.failed)."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


class ToolOrderError(ValueError):
    """A tool was called before the tool it depends on (the message names that tool)."""


def _short(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}".splitlines()[0]
    return text[:MAX_ERROR_CHARS]


def _reject(message: str) -> NoReturn:
    raise ValueError(message)


def _relative_frame_url(camera_id: str, index: int) -> str:
    return f"{FRAMES_DIRNAME}/{camera_id}/{index:04d}.jpg"


def _hypothesis_summary(h: Hypothesis) -> dict[str, Any]:
    return {"event_type": h.event_type, "region": h.region, "confidence": h.confidence}


def args_def(name: str) -> str:
    """The ``$defs`` entry in ``contracts/tools.schema.json`` for ``name``'s arguments."""
    return "no_args" if name in NO_ARGS else f"{name}_args"


_TYPE_NAMES = {
    "string": "a string",
    "object": "an object",
    "array": "an array",
    "integer": "an integer",
    "number": "a number",
    "boolean": "a boolean",
    "null": "null",
}
_BOUNDS = {"minimum": ">=", "maximum": "<=", "exclusiveMinimum": ">", "exclusiveMaximum": "<"}


def _schema_message(error: ValidationError) -> str:
    """What the schema requires at the failing spot, without quoting the bad value.

    jsonschema's own messages embed the instance (``['cam_gt'] is not of type
    'string'``), so a malformed call could echo the withheld camera id.
    """
    rule, value = error.validator, error.validator_value
    what = "field(s)" if error.absolute_path else "argument(s)"
    if rule == "type":
        kinds = [value] if isinstance(value, str) else list(value)
        return "must be " + " or ".join(_TYPE_NAMES.get(k, k) for k in kinds)
    if rule == "required":
        missing = [k for k in value if k not in error.instance]
        return f"missing required {what}: {', '.join(missing)}"
    if rule == "additionalProperties":
        allowed = sorted(error.schema.get("properties", {}))
        if not allowed:
            return f"takes no {what.removesuffix('(s)')}s"
        return f"unexpected {what}; allowed: {', '.join(allowed)}"
    if rule in _BOUNDS:
        return f"must be {_BOUNDS[rule]} {value}"
    if rule in ("minItems", "maxItems"):
        return f"must have at {'least' if rule == 'minItems' else 'most'} {value} item(s)"
    if rule in ("minLength", "maxLength"):
        return f"must be at {'least' if rule == 'minLength' else 'most'} {value} character(s)"
    if rule == "enum":
        return f"must be one of: {', '.join(map(str, value))}"
    if rule == "const":
        return f"must be {value!r}"
    return f"does not satisfy {rule!r}"


def tool_call_error(name: str, arguments: Any) -> str | None:
    """Why ``{name, arguments}`` is not a valid tool call, or ``None`` when it is."""
    if name not in TOOL_NAMES:
        return f"unknown tool; tools are: {', '.join(TOOL_NAMES)}"
    error = best_match(def_validator(TOOL_CONTRACT, args_def(name)).iter_errors(arguments))
    if error is None:
        return None
    where = "/".join(str(p) for p in error.absolute_path) or "arguments"
    return f"{name}: {where}: {_schema_message(error)}"


class _Trace:
    """Wraps one tool call in a tool.started / tool.completed pair.

    ``before`` and ``after(result)`` emit the call's domain events inside the pair.
    Calls are serialized, so pairs never interleave even when a runtime calls tools
    from several threads.
    """

    def __init__(self, emit: Emit) -> None:
        self._emit = emit
        self._ids = count(1)
        self._lock = threading.Lock()
        self.latency_ms: dict[str, list[float]] = {}

    def _failed(self, call_id: str, tool: str, started: float, error: str) -> None:
        self._emit(
            "tool.completed",
            {
                "call_id": call_id,
                "tool": tool,
                "ok": False,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "result_summary": {},
                "error": error,
            },
        )

    def call(
        self,
        tool: str,
        args_summary: dict[str, Any],
        fn: Callable[[], T],
        summarize: Callable[[T], dict[str, Any]],
        *,
        before: Callable[[], None] | None = None,
        after: Callable[[T], None] | None = None,
    ) -> T:
        with self._lock:
            return self._call(tool, args_summary, fn, summarize, before, after)

    def _call(
        self,
        tool: str,
        args_summary: dict[str, Any],
        fn: Callable[[], T],
        summarize: Callable[[T], dict[str, Any]],
        before: Callable[[], None] | None,
        after: Callable[[T], None] | None,
    ) -> T:
        call_id = f"call_{next(self._ids):03d}"
        self._emit("tool.started", {"call_id": call_id, "tool": tool, "args_summary": args_summary})
        started = time.perf_counter()
        try:
            if before:
                before()
            result = fn()
            if after:
                after(result)
            summary = summarize(result)
        except Exception as exc:
            error = _short(exc)
            try:
                self._failed(call_id, tool, started, error)
            except GroundTruthAccessError:
                # The detail named the withheld camera: close the pair without it.
                error = f"{type(exc).__name__}: details withheld"
                self._failed(call_id, tool, started, error)
                raise ToolCallError(tool, error) from None
            raise ToolCallError(tool, error) from exc
        latency = round((time.perf_counter() - started) * 1000, 1)
        self.latency_ms.setdefault(tool, []).append(latency)
        self._emit(
            "tool.completed",
            {
                "call_id": call_id,
                "tool": tool,
                "ok": True,
                "latency_ms": latency,
                "result_summary": summary,
            },
        )
        return result


class ToolSession:
    def __init__(
        self,
        view: ModelScenarioView,
        profile: ModelProfile,
        emit: Emit,
        *,
        run_dir: Path,
        frame_url: FrameUrl | None = None,
        media_root: Path = REPO_ROOT,
        perception: PerceptionAdapter | None = None,
        reasoning: ReasoningAdapter | None = None,
    ) -> None:
        if not isinstance(view, ModelScenarioView):
            raise TypeError("ToolSession takes a ModelScenarioView, never a full Scenario")
        self.view = view
        self.profile = profile
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.media_root = media_root
        self._emit = emit
        self._url = frame_url or _relative_frame_url
        self._trace = _Trace(emit)
        self.perception = perception or get_perception_adapter(profile)
        self.reasoning = reasoning or get_reasoning_adapter(profile)
        self.adapter_calls: list[dict[str, Any]] = []
        self.manifests: dict[str, MediaManifest] = {}
        self.batches: dict[str, ObservationBatch] = {}
        self.evidence: list[EvidenceItem] | None = None
        self.clusters: list[EvidenceCluster] | None = None
        self.bundle: EvidenceBundle | None = None
        self.raw_hypothesis: Hypothesis | None = None
        self.hypothesis: Hypothesis | None = None
        self.supporting_frames: dict[str, list[FrameRef]] = {}

    @property
    def tool_latency_ms(self) -> dict[str, list[float]]:
        return self._trace.latency_ms

    @property
    def camera_ids(self) -> list[str]:
        return [c.id for c in self.view.cameras]

    def ordered_batches(self) -> list[ObservationBatch]:
        """Observation batches in the scenario's camera order."""
        return [self.batches[c] for c in self.camera_ids if c in self.batches]

    def _record(self, info: Any) -> None:
        self.adapter_calls.append(info.to_dict())

    def _shown(self, camera_id: Any) -> str:
        """The camera id as it may appear in an event: never a non-visible id."""
        return camera_id if camera_id in self.camera_ids else NOT_VISIBLE

    def _camera(self, camera_id: str) -> ModelCamera:
        try:
            return self.view.camera(camera_id)
        except GroundTruthAccessError:
            raise GroundTruthAccessError(
                f"not an allowed input camera; use one of: {', '.join(self.camera_ids)}"
            ) from None

    def _manifest(self, camera_id: str) -> MediaManifest:
        self._camera(camera_id)
        if camera_id not in self.manifests:
            raise ToolOrderError(f"call sample_video for {camera_id!r} first")
        return self.manifests[camera_id]

    def _require_bundle(self) -> EvidenceBundle:
        if self.bundle is None:
            raise ToolOrderError("call triangulate_region first")
        return self.bundle

    def _reset_fusion(self) -> None:
        """New or changed observations make every fused result stale."""
        self.evidence = self.clusters = None
        self._reset_bundle()

    def _reset_bundle(self) -> None:
        self.bundle = self.raw_hypothesis = None
        self._reset_hypothesis()

    def _reset_hypothesis(self) -> None:
        """A new claim makes the submitted one, and the frames fetched for it, stale."""
        self.hypothesis = None
        self.supporting_frames = {}

    # -- tools ------------------------------------------------------------------------

    def sample_video(self, camera_id: str) -> MediaManifest:
        media = self.profile.media

        def started() -> None:
            self._camera(camera_id)
            self._emit("camera.started", {"camera_id": camera_id})

        def run() -> MediaManifest:
            cam = self._camera(camera_id)
            video = Path(cam.file) if Path(cam.file).is_absolute() else self.media_root / cam.file
            return sample_video(
                video,
                camera_id,
                out_dir=self.run_dir / FRAMES_DIRNAME,
                sample_fps=media.sample_fps,
                max_frames=media.max_frames_per_camera,
                max_width=media.max_width,
            )

        def sampled(m: MediaManifest) -> None:
            frames = [
                {
                    "index": f.index,
                    "frame_id": f.frame_id,
                    "t": f.t,
                    "url": self._url(camera_id, f.index),
                }
                for f in m.frames
            ]
            self._emit(
                "camera.frames.sampled",
                {"camera_id": camera_id, "sample_fps": m.sample_fps, "frames": frames},
            )
            self.manifests[camera_id] = m
            self.batches.pop(camera_id, None)
            self._reset_fusion()

        return self._trace.call(
            "sample_video",
            {
                "camera_id": self._shown(camera_id),
                "sample_fps": media.sample_fps,
                "max_frames": media.max_frames_per_camera,
            },
            run,
            lambda m: {"frames": len(m.frames), "duration_s": m.duration_s},
            before=started,
            after=sampled,
        )

    def inspect_camera(self, camera_id: str) -> ObservationBatch:
        calls_before = len(self.adapter_calls)
        sampled = self.manifests.get(camera_id)

        def run() -> ObservationBatch:
            options = PerceptionOptions(
                scenario_id=self.view.id, scenario_view=self.view, telemetry=self._record
            )
            return inspect_camera(
                camera_id, self._manifest(camera_id), options, adapter=self.perception
            )

        def observed(b: ObservationBatch) -> None:
            for obs in b.observations:
                self._emit(
                    "camera.observation",
                    {"camera_id": camera_id, "observation": obs.model_dump(mode="json")},
                )
            calls = self.adapter_calls[calls_before:]
            self._emit(
                "camera.complete",
                {
                    "camera_id": camera_id,
                    "observation_count": len(b.observations),
                    "latency_ms": round(sum(c.get("latency_s", 0.0) for c in calls) * 1000, 1),
                    "adapter": self.perception.name,
                },
            )
            self.batches[camera_id] = b
            self._reset_fusion()

        return self._trace.call(
            "inspect_camera",
            {"camera_id": self._shown(camera_id), "frames": len(sampled.frames) if sampled else 0},
            run,
            lambda b: {"observations": len(b.observations)},
            after=observed,
        )

    def correlate_observations(self) -> tuple[list[EvidenceItem], list[EvidenceCluster]]:
        observations = sum(len(b.observations) for b in self.batches.values())

        def started() -> None:
            if not self.batches:
                raise ToolOrderError("call inspect_camera for at least one camera first")
            self._emit("fusion.started", {"evidence_count": observations})

        def linked(result: tuple[list[EvidenceItem], list[EvidenceCluster]]) -> None:
            evidence, clusters = result
            by_id = {e.id: e for e in evidence}
            for cluster in clusters:
                self._emit(
                    "evidence.linked",
                    {
                        "cluster": cluster.model_dump(mode="json"),
                        "evidence": [
                            by_id[i].model_dump(mode="json") for i in cluster.evidence_ids
                        ],
                    },
                )
            self.evidence, self.clusters = evidence, clusters
            self._reset_bundle()

        return self._trace.call(
            "correlate_observations",
            {"cameras": len(self.batches), "observations": observations},
            lambda: correlate_observations(self.ordered_batches(), self.view),
            lambda r: {"evidence": len(r[0]), "clusters": len(r[1])},
            before=started,
            after=linked,
        )

    def triangulate_region(self) -> EvidenceBundle:
        def run() -> EvidenceBundle:
            if self.evidence is None or self.clusters is None:
                raise ToolOrderError("call correlate_observations first")
            candidates = triangulate_region(self.evidence, self.clusters, self.view)
            notes = fusion_notes(self.ordered_batches(), self.view)
            return assemble_evidence_bundle(
                self.view, self.evidence, self.clusters, candidates, notes=notes
            )

        def updated(bundle: EvidenceBundle) -> None:
            self._emit(
                "triangulation.updated",
                {
                    "candidates": [c.model_dump(mode="json") for c in bundle.region_candidates],
                    "rays": [ray.to_dict() for ray in evidence_rays(bundle.evidence, self.view)],
                },
            )
            self._reset_bundle()
            self.bundle = bundle

        return self._trace.call(
            "triangulate_region",
            {"evidence": len(self.evidence or []), "clusters": len(self.clusters or [])},
            run,
            lambda b: {
                "status": b.status,
                "candidates": len(b.region_candidates),
                "best": b.region_candidates[0].id if b.region_candidates else None,
            },
            after=updated,
        )

    def reason_hypothesis(self) -> Hypothesis:
        bundle = self.bundle

        def run() -> Hypothesis:
            options = ReasoningOptions(telemetry=self._record)
            return reason_hypothesis(self._require_bundle(), options, adapter=self.reasoning)

        def updated(h: Hypothesis) -> None:
            self._emit(
                "hypothesis.updated", {"hypothesis": h.model_dump(mode="json"), "final": False}
            )
            self._reset_hypothesis()
            self.raw_hypothesis = h

        return self._trace.call(
            "reason_hypothesis",
            {
                "status": bundle.status if bundle else None,
                "evidence": len(bundle.evidence) if bundle else 0,
            },
            run,
            _hypothesis_summary,
            after=updated,
        )

    def get_supporting_frames(self, camera_id: str, frame_indices: list[int]) -> list[FrameRef]:
        def stored(frames: list[FrameRef]) -> None:
            known = self.supporting_frames.setdefault(camera_id, [])
            known.extend(f for f in frames if f not in known)

        return self._trace.call(
            "get_supporting_frames",
            {"camera_id": self._shown(camera_id), "frame_indices": len(frame_indices)},
            lambda: get_supporting_frames(camera_id, frame_indices, self._manifest(camera_id)),
            lambda frames: {"frames": len(frames)},
            after=stored,
        )

    def submit_hypothesis(self, hypothesis: Hypothesis | dict | None = None) -> Hypothesis:
        def run() -> Hypothesis:
            bundle = self._require_bundle()
            claim = hypothesis if hypothesis is not None else self.raw_hypothesis
            if claim is None:
                raise ToolOrderError("call reason_hypothesis first or pass a hypothesis")
            return submit_hypothesis(claim, bundle)

        def updated(h: Hypothesis) -> None:
            self._emit(
                "hypothesis.updated", {"hypothesis": h.model_dump(mode="json"), "final": True}
            )
            self.hypothesis = h

        source = "argument" if hypothesis is not None else "reason_hypothesis"
        return self._trace.call(
            "submit_hypothesis", {"source": source}, run, _hypothesis_summary, after=updated
        )

    # -- JSON form --------------------------------------------------------------------

    def call_tool(self, name: str, arguments: Any) -> dict[str, Any]:
        """Run a ``{name, arguments}`` call (``contracts/tools.schema.json``) and return
        the JSON form of its result (``$defs/<name>_result``).

        An invalid call still produces a failed tool pair, so it shows in the trace."""
        error = tool_call_error(name, arguments)
        if error is not None:
            tool = name if name in TOOL_NAMES else UNKNOWN_TOOL
            return self._trace.call(tool, {"rejected": True}, lambda: _reject(error), lambda _: {})
        if name == "get_supporting_frames":
            # JSON Schema counts 1.0 as an integer; list indexing does not.
            indices = [int(i) for i in arguments["frame_indices"]]
            arguments = {**arguments, "frame_indices": indices}
        result = getattr(self, name)(**arguments)
        if name == "correlate_observations":
            evidence, clusters = result
            return {
                "evidence": [e.model_dump(mode="json") for e in evidence],
                "clusters": [c.model_dump(mode="json") for c in clusters],
            }
        if name == "get_supporting_frames":
            return {
                "camera_id": arguments["camera_id"],
                "frames": [f.model_dump(mode="json") for f in result],
            }
        return result.model_dump(mode="json")
