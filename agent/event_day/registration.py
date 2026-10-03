"""OpenClaw tool registration for the event-day agent ``urban-mirror`` (D01).

Written on event day (2026-10-03, task D01). The seven contract tools reach OpenClaw as
one MCP server, ``mirror``, served by ``agent.event_day.mcp_server`` from the host
process that owns the run. OpenClaw 2026.7.1 names MCP tools ``<server>__<tool>``, so
the agent sees ``mirror__sample_video`` and so on.

The safety hazard review adds three tools from ``contracts/hazard_tools.schema.json``
(``hazard_scan_clip``, ``hazard_review_clip``, ``hazard_submit_summary``), served by the
same server as ``mirror__hazard_*`` (event day, hazard agent task). The seven contract
tools are unchanged; ``REGISTERED_TOOLS`` is both sets, contract tools first.

This module holds the parts that do not need a socket:

* ``tool_specs``: each tool's MCP ``name``, ``description`` and ``inputSchema``, read
  from ``contracts/tools.schema.json``. Every ``$ref`` is inlined, so the schema the
  model sees is the contract's own ``$defs/<tool>_args``, without references.
* ``agent_reply``: the agent-facing form of one ``AgentPolicy`` outcome. It nulls the
  host paths a media manifest carries, which the contract allows, and replaces absolute
  paths in error text. A reply that names the withheld camera is refused instead.
* ``registration``/``merge_registration``: the OpenClaw config for the server and the
  agents, merged into an existing ``openclaw.json``. The ``main`` agent is denied the
  ``mirror__*`` tools: NemoClaw's global ``tools.alsoAllow: ["bundle-mcp"]`` would
  otherwise hand them to it.

Nothing here imports from ``eval/``. The only ground-truth data it sees is the leak
guard's token list (``apps.api.services.gt_guard``), which it uses only to block.
"""

from __future__ import annotations

import copy
import json
import re
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from referencing import Registry, Resource

from apps.api.schemas.contracts import SCHEMA_FILES, load_schema
from apps.api.services.gt_guard import GtGuard
from tools.session import TOOL_NAMES, args_def

from .policy import AGENT_ID

if TYPE_CHECKING:
    from referencing._core import Resolver

SERVER_NAME = "mirror"
TOOL_PREFIX = f"{SERVER_NAME}__"
MCP_PATH = "/mcp"
DEFAULT_PORT = 8090
# The sandbox reaches host services through OpenShell's alias for the bridge gateway.
SANDBOX_HOST = "host.openshell.internal"
TOKEN_ENV = "AUM_TOOLS_TOKEN"
# One inspect_camera fits in 300 s; one hazard_review_clip (a repeat CV scan, the Qwen
# review and its audit on the shared vLLM) needs more room.
REQUEST_TIMEOUT_S = 600
CONNECT_TIMEOUT_S = 10

HAZARD_TOOL_NAMES: tuple[str, ...] = (
    "hazard_scan_clip",
    "hazard_review_clip",
    "hazard_submit_summary",
)
# The site lead's tools (agent "site-lead", event day 14:30): fan out the six wall
# checkers, read their reports, submit the alert list. See site_lead.py.
SITE_TOOL_NAMES: tuple[str, ...] = (
    "site_start_checks",
    "site_check_status",
    "site_submit_alerts",
)
_SITE_RUN_ID = {"type": "string", "minLength": 1, "maxLength": 64}
SITE_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "site_start_checks": {
        "description": (
            "Start the six camera checkers (one urban-mirror agent turn per wall camera) "
            "concurrently for this site run. Call once."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["site_run_id"],
            "properties": {"site_run_id": _SITE_RUN_ID},
        },
    },
    "site_check_status": {
        "description": (
            "Per-camera checker state; for each finished checker its validated summary and "
            "findings (id, title, severity, zones). Poll until every camera is done or failed."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["site_run_id"],
            "properties": {"site_run_id": _SITE_RUN_ID},
        },
    },
    "site_submit_alerts": {
        "description": (
            "Submit the notification list: which cameras to alert, highest priority first, "
            "one short plain line each. Every alert must cite finding ids from that camera's "
            "checker report and that report's severity; invented findings, cameras, zones or "
            "severities are refused. An empty list means no alerts. Closes the site run."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["site_run_id", "alerts"],
            "properties": {
                "site_run_id": _SITE_RUN_ID,
                "alerts": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["cam", "severity", "finding_ids", "line"],
                        "properties": {
                            "cam": {"type": "integer", "minimum": 1, "maximum": 6},
                            "severity": {"enum": ["high", "medium", "low"]},
                            "finding_ids": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string", "minLength": 1, "maxLength": 32},
                            },
                            "line": {"type": "string", "minLength": 3, "maxLength": 120},
                        },
                    },
                },
            },
        },
    },
}
REGISTERED_TOOLS: tuple[str, ...] = (*TOOL_NAMES, *HAZARD_TOOL_NAMES, *SITE_TOOL_NAMES)
HAZARD_CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "hazard_tools.schema.json"

OPENCLAW_DIR = Path(__file__).resolve().parent / "openclaw"
AGENT_FILE = OPENCLAW_DIR / "agent.json"
WORKSPACE_DIR = OPENCLAW_DIR / "workspace"

PATH_PLACEHOLDER = "<path>"
WITHHELD = "refused by the tool surface: the reply was withheld"
_ABS_PATH = re.compile(r"(?<![\w.~-])(?:/[\w.@+~-]+){2,}/?")
_INLINE_DROP = frozenset({"$id", "$schema", "$comment"})
_MAX_DEPTH = 32


def openclaw_name(tool: str) -> str:
    """The name OpenClaw gives the contract tool ``tool``."""
    return f"{TOOL_PREFIX}{tool}"


def contract_name(name: str) -> str:
    """The contract tool behind an OpenClaw name (unprefixed names pass through)."""
    return name.removeprefix(TOOL_PREFIX)


# -- tool specs from the contract -----------------------------------------------------


@cache
def _registry() -> Registry:
    schemas = [load_schema(n) for n in SCHEMA_FILES]
    return Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas)


def _inline(node: Any, resolver: Resolver, depth: int = 0) -> Any:
    """``node`` with every ``$ref`` replaced by its target, looked up from ``resolver``."""
    if depth > _MAX_DEPTH:
        raise ValueError("contract schema nests too deeply to inline")
    if isinstance(node, list):
        return [_inline(item, resolver, depth + 1) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        resolved = resolver.lookup(node["$ref"])
        target = _inline(resolved.contents, resolved.resolver, depth + 1)
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        return {**target, **_inline(siblings, resolver, depth + 1)}
    return {
        key: _inline(value, resolver, depth + 1)
        for key, value in node.items()
        if key not in _INLINE_DROP
    }


@cache
def _contract() -> dict[str, Any]:
    return load_schema("tool_call")


def input_schema(tool: str) -> dict[str, Any]:
    """``$defs/<tool>_args`` of the tool contract, with its references inlined."""
    contract = _contract()
    resolver = _registry().resolver(contract["$id"])
    schema = _inline(contract["$defs"][args_def(tool)], resolver)
    schema.pop("description", None)  # it is the tool's description
    return schema


def tool_description(tool: str) -> str:
    """The contract's description: the ``oneOf`` branch's, else the arguments'."""
    contract = _contract()
    for branch in contract["oneOf"]:
        if branch["properties"]["name"].get("const") == tool and branch.get("description"):
            return branch["description"]
    return contract["$defs"][args_def(tool)]["description"]


def tool_specs() -> list[dict[str, Any]]:
    """The MCP ``tools/list`` entries: the seven contract tools in contract order, then
    the three hazard tools (fresh copies)."""
    return [copy.deepcopy(_spec(tool)) for tool in REGISTERED_TOOLS]


@cache
def _spec(tool: str) -> dict[str, Any]:
    if tool in SITE_TOOL_NAMES:
        return {"name": tool, **SITE_TOOL_SPECS[tool]}
    if tool in HAZARD_TOOL_NAMES:
        return {
            "name": tool,
            "description": hazard_tool_description(tool),
            "inputSchema": hazard_input_schema(tool),
        }
    return {"name": tool, "description": tool_description(tool), "inputSchema": input_schema(tool)}


# -- hazard tool specs from contracts/hazard_tools.schema.json -------------------------


@cache
def hazard_contract() -> dict[str, Any]:
    return json.loads(HAZARD_CONTRACT.read_text(encoding="utf-8"))


@cache
def _hazard_registry() -> Registry:
    schema = hazard_contract()
    return Registry().with_resources([(schema["$id"], Resource.from_contents(schema))])


def hazard_def(name: str) -> dict[str, Any]:
    """``$defs/<name>`` of the hazard contract with its references inlined."""
    contract = hazard_contract()
    resolver = _hazard_registry().resolver(contract["$id"])
    return _inline(contract["$defs"][name], resolver)


def hazard_input_schema(tool: str) -> dict[str, Any]:
    schema = hazard_def(f"{tool}_args")
    schema.pop("description", None)
    return schema


def hazard_tool_description(tool: str) -> str:
    for branch in hazard_contract()["oneOf"]:
        if branch["properties"]["name"].get("const") == tool:
            return branch["description"]
    raise KeyError(tool)


# -- what the agent gets back ---------------------------------------------------------


def _without_frame_paths(frames: Any) -> Any:
    if not isinstance(frames, list):
        return frames
    return [{**f, "path": None} if isinstance(f, dict) and "path" in f else f for f in frames]


def _strip_host_paths(tool: str, result: Any) -> Any:
    """Null the host paths in a media manifest or frame list (the contract allows it)."""
    if not isinstance(result, dict):
        return result
    if tool == "sample_video":
        out = dict(result)
        if "source" in out:
            out["source"] = f"camera:{out.get('camera_id', 'unknown')}"
        if "clip_path" in out:
            out["clip_path"] = None
        if "frames" in out:
            out["frames"] = _without_frame_paths(out["frames"])
        return out
    if tool == "get_supporting_frames" and "frames" in result:
        return {**result, "frames": _without_frame_paths(result["frames"])}
    return result


def scrub_paths(text: str) -> str:
    """``text`` with absolute filesystem paths replaced by ``<path>``."""
    return _ABS_PATH.sub(PATH_PLACEHOLDER, text)


def agent_reply(tool: str, outcome: dict[str, Any], guard: GtGuard | None = None) -> dict[str, Any]:
    """The agent-facing form of ``ToolOutcome.to_json()`` for contract tool ``tool``."""
    reply = dict(outcome)
    if reply.get("ok") and "result" in reply:
        reply["result"] = _strip_host_paths(tool, reply["result"])
    if isinstance(reply.get("error"), str):
        reply["error"] = scrub_paths(reply["error"])
    if guard is not None and guard.leaks(json.dumps(reply)):
        return {"ok": False, "error": WITHHELD, "refused": True}
    return reply


# -- OpenClaw configuration -----------------------------------------------------------


def agent_entry() -> dict[str, Any]:
    """``agent.json``: the ``agents.list[]`` entry for ``urban-mirror``."""
    return json.loads(AGENT_FILE.read_text(encoding="utf-8"))


LEAD_AGENT_ID = "site-lead"
LEAD_AGENT_FILE = OPENCLAW_DIR / "site-lead.json"
LEAD_WORKSPACE_DIR = OPENCLAW_DIR / "workspace-site-lead"


def lead_agent_entry() -> dict[str, Any]:
    """``site-lead.json``: the ``agents.list[]`` entry for the site lead."""
    return json.loads(LEAD_AGENT_FILE.read_text(encoding="utf-8"))


def server_url(host: str = SANDBOX_HOST, port: int = DEFAULT_PORT) -> str:
    return f"http://{host}:{port}{MCP_PATH}"


def server_entry(url: str, *, token_env: str | None = TOKEN_ENV) -> dict[str, Any]:
    """The ``mcp.servers.mirror`` entry. The bearer token stays an env reference
    (``${AUM_TOOLS_TOKEN}``), resolved by OpenClaw at load time; it is never written."""
    entry: dict[str, Any] = {
        "enabled": True,
        "url": url,
        "transport": "streamable-http",
        "toolFilter": {"include": list(REGISTERED_TOOLS)},
        "connectTimeout": CONNECT_TIMEOUT_S,
        "timeout": REQUEST_TIMEOUT_S,
        "supportsParallelToolCalls": False,
    }
    if token_env:
        entry["headers"] = {"Authorization": f"Bearer ${{{token_env}}}"}
    return entry


def registration(url: str, *, token_env: str | None = TOKEN_ENV) -> dict[str, Any]:
    """The OpenClaw config fragment D01 adds: the server and the agent entry."""
    return {
        "mcp": {"servers": {SERVER_NAME: server_entry(url, token_env=token_env)}},
        "agents": {"list": [agent_entry(), lead_agent_entry()]},
    }


def merge_registration(
    config: dict[str, Any],
    url: str,
    *,
    token_env: str | None = TOKEN_ENV,
    workspace: str | None = None,
) -> dict[str, Any]:
    """``config`` (an ``openclaw.json``) with the registration merged in.

    Replaces ``mcp.servers.mirror`` and the ``urban-mirror`` agent entry, and adds
    ``mirror__*`` to every other agent's ``tools.deny``. Any other key is left as is.
    ``workspace`` overrides the agent's workspace path (for a host-side check).
    """
    out = copy.deepcopy(config)
    servers = out.setdefault("mcp", {}).setdefault("servers", {})
    servers[SERVER_NAME] = server_entry(url, token_env=token_env)
    agents = out.setdefault("agents", {}).setdefault("list", [])
    entry = agent_entry()
    if workspace is not None:
        entry["workspace"] = workspace
    lead = lead_agent_entry()
    others = [a for a in agents if a.get("id") not in (AGENT_ID, LEAD_AGENT_ID)]
    if not others:
        others = [{"id": "main", "default": True}]
    for other in others:
        deny = other.setdefault("tools", {}).setdefault("deny", [])
        if f"{TOOL_PREFIX}*" not in deny:
            deny.append(f"{TOOL_PREFIX}*")
    agents[:] = [*others, entry, lead]
    return out


__all__ = [
    "DEFAULT_PORT",
    "HAZARD_TOOL_NAMES",
    "LEAD_AGENT_ID",
    "LEAD_WORKSPACE_DIR",
    "MCP_PATH",
    "REGISTERED_TOOLS",
    "SANDBOX_HOST",
    "SERVER_NAME",
    "SITE_TOOL_NAMES",
    "SITE_TOOL_SPECS",
    "TOKEN_ENV",
    "TOOL_PREFIX",
    "agent_entry",
    "agent_reply",
    "contract_name",
    "hazard_def",
    "hazard_input_schema",
    "hazard_tool_description",
    "input_schema",
    "lead_agent_entry",
    "merge_registration",
    "openclaw_name",
    "registration",
    "scrub_paths",
    "server_entry",
    "server_url",
    "tool_description",
    "tool_specs",
]
