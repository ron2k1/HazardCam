"""Perception adapters (Qwen role): sampled frames of ONE camera -> ObservationBatch.

The model only proposes observations. Everything the rest of the pipeline relies on is
re-derived here in code: camera id, observation ids, times (from the cited frames'
manifest ``t``), the cue vocabulary, the direction vocabulary and frame citations.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx

from apps.api.schemas import FrameRef, MediaManifest, ObservationBatch

from .base import CallInfo, PerceptionOptions, load_prompt, report
from .client import ChatClient, ChatResult, ModelCallError, extract_json
from .coerce import as_float, as_int, coerce_confidence
from .frames import (
    FRAME_LABEL_TOKENS,
    encode_image,
    frame_label,
    image_tokens,
    resolve_frame_path,
    text_tokens,
    uniform_subset,
)
from .profiles import ModelProfile
from .vocab import (
    CUE_TYPES,
    DIRECTIONS,
    is_conclusion_text,
    normalize_cue_type,
    normalize_direction,
)

log = logging.getLogger(__name__)

PROMPT_FILE = "qwen_perception.txt"
MAX_OBSERVATIONS = 12
DESCRIPTION_MAX_CHARS = 300
CONTEXT_SAFETY_TOKENS = 64
REPAIR_ECHO_CHARS = 4000
_TIME_EPS = 1e-6
_FRAME_KEYS = ("supporting_frames", "frames", "frame_indices", "frame_index", "frame")
_DESC_KEYS = ("description", "desc", "text", "summary", "observation")
_CUE_KEYS = ("cue_type", "type", "cue", "category")


class OutputFormatError(ValueError):
    """Model output is not usable as an observation list (triggers one repair)."""


class _InputError(RuntimeError):
    """Nothing sendable (no readable frame, or the context cannot hold one frame)."""


# --- schema + post-processing (pure, unit-tested) ----------------------------------------


def observation_schema(frame_indices: Sequence[int]) -> dict[str, Any]:
    """Structured-output schema; enums make uncited frames/cues unrepresentable."""
    return {
        "type": "object",
        "properties": {
            "observations": {
                "type": "array",
                "maxItems": MAX_OBSERVATIONS,
                "items": {
                    "type": "object",
                    "properties": {
                        "supporting_frames": {
                            "type": "array",
                            "items": {"type": "integer", "enum": list(frame_indices)},
                        },
                        "cue_type": {"type": "string", "enum": list(CUE_TYPES)},
                        "description": {"type": "string"},
                        "direction": {
                            "anyOf": [
                                {"type": "string", "enum": list(DIRECTIONS)},
                                {"type": "null"},
                            ]
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": [
                        "supporting_frames",
                        "cue_type",
                        "description",
                        "direction",
                        "confidence",
                    ],
                },
            }
        },
        "required": ["observations"],
    }


def postprocess_observations(
    raw: Any, camera_id: str, frames: Sequence[FrameRef]
) -> tuple[ObservationBatch, list[str], int]:
    """Turn parsed model JSON into a contract-valid batch for ``camera_id``.

    ``frames`` are the frames the model actually saw. Returns ``(batch, warnings,
    dropped_count)``. Raises :class:`OutputFormatError` when the shape is unusable.
    """
    items = _observation_items(raw)
    t_of = {f.index: f.t for f in frames}
    warnings: list[str] = []
    dropped = 0
    kept: list[dict[str, Any]] = []
    seen: dict[tuple, int] = {}
    for n, item in enumerate(items):
        if not isinstance(item, dict):
            dropped += 1
            warnings.append(f"item {n}: not an object; dropped")
            continue
        cited, malformed = _cited_frames(item)
        if malformed or any(i not in t_of for i in cited):
            dropped += 1
            warnings.append(
                f"item {n}: cites frames outside the supplied set {sorted(t_of)}; dropped"
            )
            continue
        if not cited:
            cited = _frames_from_times(item, frames)
            if not cited:
                dropped += 1
                warnings.append(f"item {n}: cites no supplied frame or time; dropped")
                continue
        cited = sorted(set(cited))
        raw_cue = next((item[k] for k in _CUE_KEYS if k in item), None)
        cue = normalize_cue_type(raw_cue)
        if isinstance(raw_cue, str) and cue != raw_cue:
            warnings.append(f"item {n}: cue_type {raw_cue!r} normalized to {cue!r}")
        times = [t_of[i] for i in cited]
        obs = {
            "t_start": min(times),
            "t_end": max(times),
            "cue_type": cue,
            "description": _description(item),
            "direction": normalize_direction(item.get("direction")),
            "confidence": coerce_confidence(item.get("confidence")),
            "supporting_frames": cited,
        }
        key = (obs["cue_type"], tuple(cited), obs["direction"])
        if key in seen:
            dropped += 1
            prev = kept[seen[key]]
            prev["confidence"] = max(prev["confidence"], obs["confidence"])
            continue
        seen[key] = len(kept)
        kept.append(obs)

    if len(kept) > MAX_OBSERVATIONS:
        warnings.append(f"kept the {MAX_OBSERVATIONS} most confident of {len(kept)} observations")
        dropped += len(kept) - MAX_OBSERVATIONS
        kept = sorted(kept, key=lambda o: -o["confidence"])[:MAX_OBSERVATIONS]
    kept.sort(key=lambda o: (o["t_start"], o["t_end"]))
    for n, obs in enumerate(kept, start=1):
        obs["id"] = f"{camera_id}.o{n}"
        if is_conclusion_text(obs["description"]):
            warnings.append(f"{obs['id']}: description names a final-event class")
    batch = ObservationBatch.model_validate({"camera_id": camera_id, "observations": kept})
    return batch, warnings, dropped


def _observation_items(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        if isinstance(raw.get("observations"), list):
            return raw["observations"]
        lists = [v for v in raw.values() if isinstance(v, list)]
        if len(lists) == 1 and all(isinstance(x, dict) for x in lists[0]):
            return lists[0]
        if any(k in raw for k in _CUE_KEYS):
            return [raw]
    raise OutputFormatError('expected a JSON object {"observations": [...]}')


def _cited_frames(item: dict[str, Any]) -> tuple[list[int], bool]:
    """``(indices, malformed)`` from the first frame-citation key present."""
    for key in _FRAME_KEYS:
        if item.get(key) is not None:
            value = item[key]
            ints = [as_int(v) for v in (value if isinstance(value, list) else [value])]
            return [i for i in ints if i is not None], any(i is None for i in ints)
    return [], False


def _frames_from_times(item: dict[str, Any], frames: Sequence[FrameRef]) -> list[int]:
    """Frames whose manifest ``t`` lies inside the item's stated window (no snapping)."""
    start = as_float(item.get("t_start", item.get("t")))
    if start is None:
        return []
    end = as_float(item.get("t_end"))
    lo, hi = sorted((start, start if end is None else end))
    return [f.index for f in frames if lo - _TIME_EPS <= f.t <= hi + _TIME_EPS]


def _description(item: dict[str, Any]) -> str:
    text = next((item[k] for k in _DESC_KEYS if isinstance(item.get(k), str)), "")
    return " ".join(text.split())[:DESCRIPTION_MAX_CHARS]


# --- adapters ---------------------------------------------------------------------------


class FixturePerceptionAdapter:
    """Deterministic replay: ``<fixture_dir>/<scenario_id>/qwen_observations.json`` when it
    exists, else the profile's fixture file. The file maps camera_id -> ObservationBatch."""

    name = "fixture"

    def __init__(self, profile: ModelProfile) -> None:
        self.profile = profile
        self.last_call: CallInfo | None = None

    def inspect(
        self, camera_id: str, media: MediaManifest, options: PerceptionOptions
    ) -> ObservationBatch:
        start = time.perf_counter()
        scenario_id = options.effective_scenario_id
        path = self.profile.perception.fixture_path(scenario_id)
        info = CallInfo(
            role="perception",
            adapter=self.name,
            model=None,
            camera_id=camera_id,
            scenario_id=scenario_id,
            frames_sent=[f.index for f in media.frames],
        )
        batch = ObservationBatch(camera_id=camera_id, observations=[])
        try:
            if path is None:
                raise FileNotFoundError("no perception fixture configured")
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(data, dict) and "observations" in data:
                data = {data.get("camera_id", camera_id): data}
            entry = data.get(camera_id) if isinstance(data, dict) else None
            if entry is None:
                info.warnings.append(f"fixture {Path(path).name} has no camera {camera_id!r}")
            else:
                batch = ObservationBatch.model_validate({**entry, "camera_id": camera_id})
        except (OSError, ValueError, TypeError) as exc:
            info.ok, info.error = False, f"fixture unreadable: {type(exc).__name__}: {exc}"
        n_frames = len(media.frames)
        stale = sorted(
            {f for o in batch.observations for f in o.supporting_frames if f >= n_frames}
        )
        if stale:
            info.warnings.append(
                f"fixture cites frames {stale} beyond this manifest (0..{n_frames - 1})"
            )
        info.latency_s = time.perf_counter() - start
        self.last_call = info
        report(info, options.telemetry, options.strict)
        return batch


class OpenAICompatPerceptionAdapter:
    """Live VLM over an OpenAI-compatible ``/chat/completions`` endpoint (Ollama, vLLM, NIM).

    ``last_call`` is a convenience for sequential use; concurrent callers should read
    ``PerceptionOptions.telemetry`` instead.
    """

    def __init__(
        self,
        profile: ModelProfile,
        *,
        transport: httpx.BaseTransport | None = None,
        env: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.profile = profile
        self.endpoint = profile.perception
        self.client = ChatClient(self.endpoint, transport=transport, env=env, sleep=sleep)
        self.name = f"openai_compatible/{self.endpoint.model}"
        self.last_call: CallInfo | None = None

    def inspect(
        self, camera_id: str, media: MediaManifest, options: PerceptionOptions
    ) -> ObservationBatch:
        if media.camera_id != camera_id:
            raise ValueError(f"manifest is for camera {media.camera_id!r}, not {camera_id!r}")
        start = time.perf_counter()
        system, version = load_prompt(PROMPT_FILE)
        info = CallInfo(
            role="perception",
            adapter=self.name,
            model=self.endpoint.model,
            camera_id=camera_id,
            scenario_id=options.effective_scenario_id,
            prompt_version=version,
        )
        batch = ObservationBatch(camera_id=camera_id, observations=[])
        try:
            batch = self._inspect(camera_id, media, options, system, info)
        except (ModelCallError, _InputError) as exc:
            info.ok, info.error = False, str(exc)
            info.attempts += getattr(exc, "attempts", 0)
        info.latency_s = time.perf_counter() - start
        self.last_call = info
        log.info(
            "perception camera=%s model=%s ok=%s obs=%d latency=%.2fs frames=%s",
            camera_id,
            self.endpoint.model,
            info.ok,
            len(batch.observations),
            info.latency_s,
            info.frames_sent,
        )
        report(info, options.telemetry, options.strict)
        return batch

    def _inspect(
        self,
        camera_id: str,
        media: MediaManifest,
        options: PerceptionOptions,
        system: str,
        info: CallInfo,
    ) -> ObservationBatch:
        max_tokens = options.max_tokens or self.endpoint.max_tokens
        max_frames = options.max_frames or self.profile.media.max_frames_per_camera
        chosen = uniform_subset(list(media.frames), max_frames)
        chosen_ids = {f.index for f in chosen}
        info.frames_skipped = [f.index for f in media.frames if f.index not in chosen_ids]

        loaded: list[tuple[FrameRef, str, int]] = []  # (frame, data_url, est_tokens)
        for frame in chosen:
            path = resolve_frame_path(frame.path)
            try:
                if path is None:
                    raise FileNotFoundError("image file not found")
                data_url, w, h = encode_image(path, self.endpoint.max_image_width)
            except OSError as exc:
                info.frames_skipped.append(frame.index)
                info.warnings.append(f"frame {frame.index}: unreadable ({type(exc).__name__})")
                continue
            tokens = image_tokens(w, h, self.endpoint.image_token_px) + FRAME_LABEL_TOKENS
            loaded.append((frame, data_url, tokens))
        if not loaded:
            raise _InputError(f"camera {camera_id!r}: no readable frames to inspect")

        sent = self._fit_context(loaded, system, camera_id, max_tokens, info)
        frames = [f for f, _, _ in sent]
        info.frames_sent = [f.index for f in frames]
        content: list[dict[str, Any]] = [{"type": "text", "text": _header(camera_id, frames)}]
        for frame, data_url, _ in sent:
            content.append({"type": "text", "text": frame_label(frame)})
            content.append({"type": "image_url", "image_url": {"url": data_url}})
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
        ]
        schema = observation_schema(info.frames_sent)
        result = self._call(messages, schema, max_tokens, options, info)
        try:
            batch, warnings, dropped = postprocess_observations(
                extract_json(result.content), camera_id, frames
            )
        except ValueError as first:  # includes OutputFormatError and pydantic errors
            info.warnings.append(f"invalid output, repairing: {first}")
            info.repaired = True
            repair = [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": _repair_prompt(result.content, first, info.frames_sent),
                },
            ]
            result = self._call(repair, schema, max_tokens, options, info)
            try:
                batch, warnings, dropped = postprocess_observations(
                    extract_json(result.content), camera_id, frames
                )
            except ValueError as second:
                info.ok, info.error = False, f"invalid JSON after repair: {second}"
                return ObservationBatch(camera_id=camera_id, observations=[])
        info.warnings.extend(warnings)
        info.dropped_items = dropped
        return batch

    def _call(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        max_tokens: int,
        options: PerceptionOptions,
        info: CallInfo,
    ) -> ChatResult:
        result = self.client.chat(
            messages,
            response_schema=schema,
            schema_name="observation_batch",
            max_tokens=max_tokens,
            temperature=options.temperature,
        )
        info.attempts += result.attempts
        info.model = result.model
        info.usage = result.usage
        info.finish_reason = result.finish_reason
        ctx = self.endpoint.context_tokens
        if ctx and int(result.usage.get("total_tokens") or 0) >= ctx:
            info.warnings.append("context window saturated; prompt may have been truncated")
        return result

    def _fit_context(
        self,
        loaded: list[tuple[FrameRef, str, int]],
        system: str,
        camera_id: str,
        max_tokens: int,
        info: CallInfo,
    ) -> list[tuple[FrameRef, str, int]]:
        """Uniformly drop frames until the estimated prompt fits the context window.

        Some servers (Ollama) silently truncate an oversized prompt from the front,
        which removes the instructions; an explicit, recorded subsample is safer.
        """
        ctx = self.endpoint.context_tokens
        if not ctx:
            return loaded
        header = _header(camera_id, [f for f, _, _ in loaded])
        available = (
            ctx - max_tokens - CONTEXT_SAFETY_TOKENS - text_tokens(system) - text_tokens(header)
        )
        for k in range(len(loaded), 0, -1):
            subset = uniform_subset(loaded, k)
            if sum(t for _, _, t in subset) <= available:
                kept = {f.index for f, _, _ in subset}
                skipped = [f.index for f, _, _ in loaded if f.index not in kept]
                if skipped:
                    info.frames_skipped.extend(skipped)
                    info.warnings.append(f"context budget {ctx}: sent {k} of {len(loaded)} frames")
                return subset
        raise _InputError(f"context window {ctx} cannot fit one frame with max_tokens={max_tokens}")


def _header(camera_id: str, frames: Sequence[FrameRef]) -> str:
    indices = ", ".join(str(f.index) for f in frames)
    return (
        f"Camera: {camera_id}\n"
        f"{len(frames)} frames from this one camera follow in time order. Each image is "
        'preceded by its label "Frame index=<index> t=<seconds>s". '
        f"Valid supporting_frames values: [{indices}].\n"
        "Return only the JSON object."
    )


def _repair_prompt(previous: str, error: Exception, indices: Sequence[int]) -> str:
    return (
        f"Your previous reply could not be used ({error}). Rewrite it as ONLY the required "
        'JSON object {"observations": [...]} following the system rules, citing only '
        f"supporting_frames from {list(indices)}. If it held no usable observation, return "
        '{"observations": []}.\n\nPrevious reply:\n'
        f"{previous[:REPAIR_ECHO_CHARS]}"
    )
