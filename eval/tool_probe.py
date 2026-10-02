"""Single-turn tool-call capability probe. NOT an agent loop and NOT the event-day playbook.

Question: shown our tool contract and a transcript of a run so far, does a local reasoning
model reply with a well-formed call to a tool the run can use next? Each case is one
request; the reply is scored and never executed or answered.

* Tools: OpenAI-style function definitions derived from ``contracts/tools.schema.json``
  with every ``$ref`` inlined, so the model sees exactly the argument contract the
  ToolSession validates.
* Transcript: a real fixture run of a prepared scenario through ``ToolSession.call_tool``.
  Each tool message is that call's ``result_summary``, the same compact summary the
  dashboard receives in ``tool.completed``. The ``recovery`` case adds one constructed
  malformed call whose tool message is the session's real rejection text.
* Scoring: the first call must pass ``tool_call_error`` (the session's own validator), name
  a tool that is acceptable in that state, and carry arguments that fit the state (an
  unsampled camera, an in-range frame index, ...). The acceptable set follows the
  prerequisites the tools enforce; any productive order passes, not just the harness's.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from apps.api.schemas.contracts import SCHEMA_FILES, load_schema
from eval.summary import proportion
from tools.session import TOOL_NAMES, tool_call_error

SYSTEM_PROMPT = (
    "You run a multi-camera video analysis by calling tools. "
    "Reply with exactly one tool call that continues the run."
)
RECOVERY_CASE = "recovery"
_FILES = {file: name for name, file in SCHEMA_FILES.items()}
_SCHEMA_META = frozenset({"$schema", "$id", "$defs"})
_MAX_REF_DEPTH = 16

Check = Callable[[dict[str, Any]], bool]


# -- tool definitions ---------------------------------------------------------------------


def _lookup(ref: str, base: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    file, _, pointer = ref.partition("#")
    doc = load_schema(_FILES[file]) if file else base
    node: Any = doc
    for part in (p for p in pointer.split("/") if p):
        node = node[part]
    return node, doc


def _inline(node: Any, base: dict[str, Any], depth: int = 0) -> Any:
    """``node`` with every ``$ref`` replaced by its target (local or another contract)."""
    if depth > _MAX_REF_DEPTH:
        raise ValueError("$ref nesting too deep")
    if isinstance(node, list):
        return [_inline(n, base, depth) for n in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        target, target_base = _lookup(node["$ref"], base)
        merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
        return _inline(merged, target_base, depth + 1)
    return {k: _inline(v, base, depth) for k, v in node.items() if k not in _SCHEMA_META}


def tool_definitions() -> list[dict[str, Any]]:
    """One ``{"type": "function", ...}`` entry per tool, in contract order."""
    doc = load_schema("tool_call")
    tools = []
    for branch in doc["oneOf"]:
        name = branch["properties"]["name"]["const"]
        parameters = _inline(branch["properties"]["arguments"], doc)
        description = branch.get("description") or parameters.pop("description", "")
        parameters.pop("description", None)
        tools.append(
            {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            }
        )
    return tools


# -- cases --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One call in the transcript and the tool message the model sees for it."""

    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass(frozen=True)
class Case:
    name: str
    cameras: list[str]
    messages: list[dict[str, Any]]
    acceptable: dict[str, Check] = field(compare=False)


def acceptable_calls(cameras: list[str], done: list[Step]) -> dict[str, Check]:
    """The calls that make progress after ``done``, each with its argument check."""
    ok_steps = [s for s in done if s.result.get("ok", True)]
    names = {s.name for s in ok_steps}
    frames = {
        s.arguments["camera_id"]: s.result["frames"] for s in ok_steps if s.name == "sample_video"
    }
    inspected = {s.arguments["camera_id"] for s in ok_steps if s.name == "inspect_camera"}
    unsampled = [c for c in cameras if c not in frames]
    uninspected = [c for c in frames if c not in inspected]

    calls: dict[str, Check] = {}
    if unsampled:
        calls["sample_video"] = lambda a: a["camera_id"] in unsampled
    if uninspected:
        calls["inspect_camera"] = lambda a: a["camera_id"] in uninspected
    if calls:
        return calls
    if "correlate_observations" not in names:
        return {"correlate_observations": lambda a: True}
    if "triangulate_region" not in names:
        return {"triangulate_region": lambda a: True}
    if "reason_hypothesis" not in names:
        return {"reason_hypothesis": lambda a: True}

    def in_range(a: dict[str, Any]) -> bool:
        n = frames.get(a["camera_id"])
        return n is not None and all(0 <= int(i) < n for i in a["frame_indices"])

    return {"get_supporting_frames": in_range, "submit_hypothesis": lambda a: True}


def _call_id(k: int) -> str:
    return f"call{k:05d}"  # 9 alphanumerics: the id shape Mistral chat templates require


def transcript(scenario_id: str, cameras: list[str], done: list[Step]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Scenario {scenario_id}. Visible cameras: {', '.join(cameras)}.",
        },
    ]
    for k, step in enumerate(done):
        call = {"name": step.name, "arguments": json.dumps(step.arguments)}
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": _call_id(k), "type": "function", "function": call}],
            }
        )
        messages.append(
            {"role": "tool", "tool_call_id": _call_id(k), "content": json.dumps(step.result)}
        )
    return messages


def build_cases(scenario_id: str, cameras: list[str], steps: list[Step]) -> list[Case]:
    """One case per prefix of the real run (before each call), plus the recovery case."""
    cases = [
        Case(
            f"{k:02d}_next_after_{steps[k - 1].name if k else 'start'}",
            cameras,
            transcript(scenario_id, cameras, steps[:k]),
            acceptable_calls(cameras, steps[:k]),
        )
        for k in range(len(steps))
    ]
    first = steps[0]
    if first.name == "sample_video":
        bad_args = {"camera_id": [first.arguments["camera_id"]]}
        rejected = Step(
            "inspect_camera",
            bad_args,
            {"ok": False, "error": tool_call_error("inspect_camera", bad_args)},
        )
        done = [first, rejected]
        cases.append(
            Case(
                RECOVERY_CASE,
                cameras,
                transcript(scenario_id, cameras, done),
                acceptable_calls(cameras, done),
            )
        )
    return cases


# -- scoring ------------------------------------------------------------------------------


def _arguments(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def score_reply(case: Case, message: dict[str, Any]) -> dict[str, Any]:
    """Score one assistant message. ``outcome`` is ``ok`` or the first thing that failed."""
    calls = message.get("tool_calls") or []
    content = message.get("content") or ""
    row: dict[str, Any] = {
        "case": case.name,
        "tool_calls": len(calls),
        "content_chars": len(content) if isinstance(content, str) else 0,
        "tool": None,
        "outcome": "no_tool_call",
        "error": None,
        "invisible_camera": False,
    }
    if not calls:
        return row
    function = calls[0].get("function") or {}
    name = str(function.get("name") or "")
    row["tool"] = name if name in TOOL_NAMES else "unknown_tool"
    args = _arguments(function.get("arguments"))
    if args is None:
        row["outcome"] = "bad_json"
        return row
    camera = args.get("camera_id")
    row["invisible_camera"] = camera is not None and camera not in case.cameras
    error = tool_call_error(name, args)
    if error is not None:
        row.update(outcome="invalid_call", error=error)
    elif name not in case.acceptable:
        row["outcome"] = "wrong_tool"
    elif not case.acceptable[name](args):
        row["outcome"] = "bad_arguments"
    else:
        row["outcome"] = "ok"
    return row


def summarize_probe(rows: list[dict[str, Any]], *, meta: dict[str, Any]) -> dict[str, Any]:
    latency = sorted(r["latency_s"] for r in rows if r.get("latency_s") is not None)
    return {
        "meta": meta,
        "n": len(rows),
        "pass": proportion([r["outcome"] == "ok" for r in rows]),
        "schema_valid": proportion(
            [r["outcome"] not in ("no_tool_call", "bad_json", "invalid_call") for r in rows]
        ),
        "outcomes": dict(sorted(Counter(r["outcome"] for r in rows).items())),
        "parallel_calls": sum(r["tool_calls"] > 1 for r in rows),
        "invisible_camera_calls": sum(r["invisible_camera"] for r in rows),
        "recovered": next((r["outcome"] == "ok" for r in rows if r["case"] == RECOVERY_CASE), None),
        "median_latency_s": latency[len(latency) // 2] if latency else None,
        "rows": rows,
    }
