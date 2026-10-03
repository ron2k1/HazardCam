"""The safety hazard review through the OpenClaw agent seam (event day, 2026-10-03).

``AgentHazardRunner`` leases one clip on the real ``mirror`` MCP server and starts one
agent turn. Here a scripted launcher stands in for ``openclaw agent``: it drives the
``hazard_*`` tool calls over HTTP through the real server, and a fake ``review_clip``
writes the run directory the real pipeline would. ``test_openclaw_live.py`` covers the
real OpenClaw runtime.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from agent.event_day.app import create_agent_app
from agent.event_day.executor import AgentRunError, AgentTurn
from agent.event_day.hazard_runner import RUNNER_NAME, AgentHazardRunner, hazard_brief
from agent.event_day.hazard_tools import SUMMARY_FILE, plain_text_problem
from agent.event_day.mcp_server import NO_RUN, ToolGateway
from agent.event_day.registration import (
    HAZARD_TOOL_NAMES,
    REGISTERED_TOOLS,
    agent_entry,
    hazard_def,
    openclaw_name,
)
from apps.api.settings import Settings
from tools.session import TOOL_NAMES

from .conftest import McpClient, ToolServer, wait_for

CLIP = "hz_01"
SECRET_STEM = "forklift_near_miss_label"  # stands in for a dataset file name / label
NARRATION_BANNED = re.compile(
    r"\d|\b[EZH]\d{2,3}\b|hazard_|mirror__|qwen|sha256|bbox", re.IGNORECASE
)


# -- a fake review_clip ---------------------------------------------------------------


def _report(clip_id: str, *, skip_model: bool, fail: bool) -> dict[str, Any]:
    evidence = [
        {
            "evidence_id": f"E{i:03d}",
            "frame_index": i * 10,
            "timestamp_s": i * 0.5,
            "kind": "full scene" if i < 3 else "zone crop",
            "zone_id": None if i < 3 else "Z01",
            "bbox_source": [0, 0, 1920, 1080],
            "path": f"evidence/E{i:03d}.jpg",
            "sha256": "0" * 64,
        }
        for i in range(1, 7)
    ]
    zones = [
        {"zone_id": "Z01", "kind": "movement"},
        {"zone_id": "Z02", "kind": "movement"},
        {"zone_id": "Z03", "kind": "possible_obstruction"},
    ]
    findings = [
        {
            "finding_id": "H01",
            "title": "Worker close to moving forklift",
            "status": "visible_concern",
            "severity": "high",
            "confidence": "medium",
            "zone_ids": ["Z01"],
            "evidence_ids": ["E004", "E005"],
            "location": "Left aisle near the racking, Z01",
            "observation": "A person walks beside a moving forklift.",
            "risk_interpretation": "Struck-by risk.",
            "standards": ["1910.176(a)"],
            "applicability_reason": "Marked aisle.",
            "unknowns": [],
            "recommended_actions": ["Keep people out of the forklift lane while it moves."],
            "first_observed_s": 2.0,
            "last_observed_s": 2.5,
        },
        {
            "finding_id": "H02",
            "title": "Box near the aisle edge",
            "status": "needs_verification",
            "severity": "low",
            "confidence": "low",
            "zone_ids": ["Z03"],
            "evidence_ids": ["E006"],
            "location": "Aisle edge",
            "observation": "A box sits on the painted line.",
            "risk_interpretation": "Trip risk.",
            "standards": [],
            "applicability_reason": "",
            "unknowns": ["Intended clearance"],
            "recommended_actions": ["Move the box off the line."],
            "first_observed_s": 3.0,
            "last_observed_s": 3.0,
        },
    ]
    if skip_model:
        status = "preprocessing_only"
    else:
        status = "model_review_failed" if fail else "model_review_complete"
    complete = status == "model_review_complete"
    return {
        "title": "Astra video hazard review",
        "status": status,
        "video": {"source_name": clip_id, "duration_s": 7.119, "decoded_frames": 177},
        "model": {"name": "qwen", "audit_sha256": "a" * 64} if complete else {},
        "request_sha256": "b" * 64 if complete else None,
        "model_error": "ModelCallError: boom" if fail and not skip_model else None,
        "findings": findings if complete else [],
        "dismissed": [{"concern": "x", "reason": "y", "evidence_ids": ["E001"]}]
        if complete
        else [],
        "zones": zones,
        "evidence": evidence,
        "pipeline": {"quality_warnings": ["Camera moved slightly during the clip."]},
    }


@dataclass
class FakeReview:
    """Records each call; writes a run dir like ``hazards.pipeline.review_clip``."""

    fail: bool = False
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(
        self,
        video: Path,
        output_root: Path,
        *,
        source_name: str,
        profile: str | None = None,
        skip_model: bool = False,
        refresh: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> Path:
        self.calls.append(
            {"output_root": Path(output_root), "skip_model": skip_model, "refresh": refresh}
        )
        out = Path(output_root) / "0123456789abcdef"
        (out / "evidence").mkdir(parents=True, exist_ok=True)
        for step in range(1, 7):
            if progress:
                progress(step, 6, f"[{step}/6] step {step}")
        report = _report(source_name, skip_model=skip_model, fail=self.fail)
        (out / "hazard_report.json").write_text(json.dumps(report), encoding="utf-8")
        (out / "evidence_manifest.json").write_text(json.dumps(report["evidence"]))
        if report["request_sha256"]:
            draft = {"report": {"findings": [{}, {}, {}]}}
            (out / f"qwen_{report['request_sha256'][:16]}.json").write_text(json.dumps(draft))
        return out


# -- a scripted stand-in for the agent turn -------------------------------------------


Script = Callable[[McpClient, str], str]


def brief_clip(brief: str) -> str:
    return re.search(r"^clip_id: (\S+)$", brief, re.MULTILINE).group(1)


def playbook(summary: dict[str, Any] | None = None) -> Script:
    """Scan, review, submit (the summary defaults to confirming the high finding)."""

    def run(client: McpClient, brief: str) -> str:
        clip = brief_clip(brief)
        client.call(openclaw_tool("scan"), {"clip_id": clip})
        client.call(openclaw_tool("review"), {"clip_id": clip})
        body = summary or {
            "headline": "Forklift passing close to a person in the left aisle",
            "first_action": "Keep people out of the forklift lane while it moves",
            "priority": "high",
            "confirmed_finding_ids": ["H01"],
        }
        reply = client.call(openclaw_tool("submit"), {"clip_id": clip, **body})
        return f"FINAL hazard clip={clip} priority={body['priority']} ok={reply['ok']}"

    return run


def openclaw_tool(short: str) -> str:
    """The contract name (the MCP server names tools without the ``mirror__`` prefix)."""
    return {"scan": "hazard_scan_clip", "review": "hazard_review_clip"}.get(
        short, "hazard_submit_summary"
    )


@dataclass
class HazardLauncher:
    url: str
    token: str
    script: Script | None = None
    fail_before_calls: bool = False
    briefs: list[str] = field(default_factory=list)
    clients: list[McpClient] = field(default_factory=list)
    run_ids: list[str] = field(default_factory=list)

    def __call__(self, brief: str, *, run_id: str, timeout_s: float) -> AgentTurn:
        self.briefs.append(brief)
        self.run_ids.append(run_id)
        started = time.monotonic()
        if self.fail_before_calls:
            return AgentTurn(ok=False, error="exit code 1: sandbox not running", exit_code=1)
        client = McpClient(self.url, self.token)
        self.clients.append(client)
        try:
            client.initialize()
            reply = (self.script or playbook())(client, brief)
        finally:
            client.http.close()
        return AgentTurn(ok=True, reply=reply, duration_s=time.monotonic() - started, exit_code=0)


@dataclass
class Job:
    runner: AgentHazardRunner
    launcher: HazardLauncher
    review: FakeReview
    gateway: ToolGateway
    video: Path
    output_root: Path
    progress: list[tuple[int, int, str]] = field(default_factory=list)

    def run(self, **kwargs: Any) -> Path:
        return self.runner(
            self.video,
            self.output_root,
            source_name=CLIP,
            refresh=False,
            progress=lambda s, t, m: self.progress.append((s, t, m)),
            **kwargs,
        )

    def replies(self) -> list[dict[str, Any]]:
        return [json.loads(r) for c in self.launcher.clients for r in c.replies]


@pytest.fixture
def job(tool_server: ToolServer, tmp_path: Path) -> Job:
    video = tmp_path / "clips" / CLIP / f"{SECRET_STEM}.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"not really a video")
    output_root = tmp_path / "reports" / CLIP
    review = FakeReview()
    launcher = HazardLauncher(tool_server.url, tool_server.token)
    runner = AgentHazardRunner(
        launcher, tool_server.gateway, review_fn=review, timeout_s=30, grace_s=5
    )
    return Job(runner, launcher, review, tool_server.gateway, video, output_root)


def result_validator(tool: str) -> Draft202012Validator:
    return Draft202012Validator(hazard_def(f"{tool}_result"))


# -- the happy path -------------------------------------------------------------------


def test_the_agent_runs_scan_review_and_submit_through_the_mcp_server(job: Job):
    run_dir = job.run()

    assert run_dir == job.output_root / "0123456789abcdef"
    summary = json.loads((run_dir / SUMMARY_FILE).read_text())
    assert summary == {
        "headline": "Forklift passing close to a person in the left aisle",
        "first_action": "Keep people out of the forklift lane while it moves",
        "priority": "high",
        "confirmed_finding_ids": ["H01"],
    }
    # The scan ran into the scratch root, the review into the real one.
    assert [(c["output_root"], c["skip_model"]) for c in job.review.calls] == [
        (job.output_root / "agent_scan", True),
        (job.output_root, False),
    ]
    # Every reply matches its contract result schema.
    replies = job.replies()
    assert [r["ok"] for r in replies] == [True, True, True]
    for tool, reply in zip(HAZARD_TOOL_NAMES, replies, strict=True):
        result_validator(tool).validate(reply["result"])
    scan, review, _ = (r["result"] for r in replies)
    assert scan["zones"] == {"movement": 2, "static": 1, "total": 3}
    assert scan["evidence_pictures"] == 6 and scan["duration_s"] == 7.12
    assert [f["id"] for f in review["findings"]] == ["H01", "H02"]
    assert review["findings"][0]["audit_verdict"] == "visible_concern"
    assert review["findings"][0]["standard_ids"] == ["1910.176(a)"]
    assert review["dismissed_count"] == 1 and review["status"] == "complete"
    assert review["audit"] == {"ran": True, "draft_findings": 3}


def test_progress_carries_the_numbered_steps_and_plain_agent_narration(job: Job):
    job.run()
    numbered = [s for s, _, _ in job.progress if s > 0]
    assert numbered == [1, 2, 3, 4, 5, 6]  # scan steps from the scan, review steps after
    narration = [m for s, total, m in job.progress if s == 0 and total == 6]
    assert "The safety agent asked for the camera scan" in narration
    assert any("summary" in line for line in narration)
    for line in narration:
        assert not NARRATION_BANNED.search(line), line


def test_the_trace_and_turn_files_are_written_in_the_run_dir(job: Job):
    run_dir = job.run()
    trace = json.loads((run_dir / "agent_trace.json").read_text())
    assert trace and all(set(e) <= {"t_s", "kind", "tool", "text"} for e in trace)
    assert {e["kind"] for e in trace} == {"tool", "say"}
    assert all("tool" in e for e in trace if e["kind"] == "tool")
    assert all("tool" not in e for e in trace if e["kind"] == "say")
    assert [e["t_s"] for e in trace] == sorted(e["t_s"] for e in trace)
    tools = [e["tool"] for e in trace if e["kind"] == "tool"]
    assert tools.index("hazard_scan_clip") < tools.index("hazard_review_clip")
    assert tools.index("hazard_review_clip") < tools.index("hazard_submit_summary")
    says = [e["text"] for e in trace if e["kind"] == "say"]
    assert says == [m for s, _, m in job.progress if s == 0]
    turn = json.loads((run_dir / "agent_turn.json").read_text())
    assert turn["harness"] == RUNNER_NAME and turn["submitted"] is True
    assert turn["turn"]["ok"] is True and turn["session"]["calls"] == 3


def test_no_label_file_name_or_host_path_reaches_the_agent(job: Job, tmp_path: Path):
    run_dir = job.run()
    (brief,) = job.launcher.briefs
    assert f"clip_id: {CLIP}" in brief
    texts = [brief, *(r for c in job.launcher.clients for r in c.replies)]
    texts.append((run_dir / "agent_trace.json").read_text())
    for text in texts:
        assert SECRET_STEM not in text
        assert str(tmp_path) not in text
        assert "/reports/" not in text and ".mp4" not in text


# -- least privilege ------------------------------------------------------------------


def test_another_clip_and_the_run_tools_are_refused_during_a_hazard_job(job: Job):
    probes: list[dict[str, Any]] = []

    def script(client: McpClient, brief: str) -> str:
        probes.append(client.call("hazard_review_clip", {"clip_id": CLIP}))  # before scan
        for other in ("hz_02", "hz_00", "../hz_01", "hz_01/../hz_02"):
            probes.append(client.call("hazard_scan_clip", {"clip_id": other}))
        probes.append(client.call("hazard_scan_clip", {"clip_id": CLIP, "path": "/etc/passwd"}))
        for tool in TOOL_NAMES:
            probes.append(client.call(tool, {"camera_id": "cam_01"}))
        return playbook()(client, brief)

    job.launcher.script = script
    run_dir = job.run()
    assert (run_dir / SUMMARY_FILE).is_file()  # the job still completes

    before_scan = probes[0]
    assert before_scan["refused"] is True and "hazard_scan_clip first" in before_scan["error"]
    for reply in probes[1:3]:  # well-formed ids of other clips
        assert reply["refused"] is True and f"Use clip_id '{CLIP}'" in reply["error"]
    for reply in probes[3:6]:  # traversal shapes and extra fields fail the contract
        assert reply["refused"] is False and "invalid hazard_scan_clip arguments" in reply["error"]
    for reply in probes[1:6]:
        assert reply["ok"] is False and "result" not in reply
        text = json.dumps(reply)
        for value in ("hz_02", "hz_00", "../", "/etc/passwd"):
            assert value not in text
    for reply in probes[6:]:
        assert reply["refused"] is True and "not part of the current job" in reply["error"]
    # Only the leased clip was ever scanned or reviewed.
    assert len(job.review.calls) == 2


def test_hazard_tools_are_refused_outside_a_hazard_job(tool_server: ToolServer):
    class RunPolicy:  # stands in for AgentPolicy (no tool_names: the seven run tools)
        run_id = "run_x"

        def call(self, name, arguments=None):
            raise AssertionError("a hazard tool must not reach a run's policy")

    client = tool_server.client()
    try:
        client.initialize()
        assert client.call("hazard_scan_clip", {"clip_id": CLIP})["error"] == NO_RUN
        with tool_server.gateway.bind(RunPolicy()):
            for tool in HAZARD_TOOL_NAMES:
                reply = client.call(tool, {"clip_id": CLIP})
                assert reply["refused"] is True and "not part of the current job" in reply["error"]
    finally:
        client.close()


def test_the_lease_ends_with_the_turn_and_late_calls_are_refused(job: Job):
    job.run()
    assert wait_for(lambda: job.gateway.active_run_id is None)
    late = McpClient(job.launcher.url, job.launcher.token)
    try:
        late.initialize()
        assert late.call("hazard_scan_clip", {"clip_id": CLIP})["error"] == NO_RUN
    finally:
        late.close()


def test_the_server_lists_and_the_agent_is_granted_the_hazard_tools(tool_server: ToolServer):
    client = tool_server.client()
    try:
        client.initialize()
        listed = {t["name"]: t for t in client.list_tools()}
    finally:
        client.close()
    assert list(listed) == list(REGISTERED_TOOLS)
    for tool in HAZARD_TOOL_NAMES:
        schema = listed[tool]["inputSchema"]
        assert "$ref" not in json.dumps(schema)
        assert schema["additionalProperties"] is False and "clip_id" in schema["required"]
        assert listed[tool]["description"]
    allowed = agent_entry()["tools"]["alsoAllow"]
    # the checker agent never gets the site lead's tools
    assert allowed == [openclaw_name(t) for t in (*TOOL_NAMES, *HAZARD_TOOL_NAMES)]


# -- the summary rules ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"headline": "Forklift risk at H01 in the left aisle"}, "finding id"),
        ({"first_action": "Check zone Z01 now"}, "zone id"),
        ({"headline": "Qwen says the forklift is close"}, "model name"),
        ({"first_action": "See https://example.org for steps"}, "link"),
        ({"headline": "Breaks rule 1910.176 in the aisle"}, "standard number"),
        ({"headline": "x" * 161}, "too long"),
        ({"confirmed_finding_ids": ["H09"]}, "unknown finding"),
        ({"priority": "none"}, "none with confirmed findings"),
        ({"priority": "high", "confirmed_finding_ids": ["H02"]}, "priority above the finding"),
        ({"priority": "low", "confirmed_finding_ids": []}, "priority without findings"),
    ],
)
def test_a_bad_summary_gets_a_tool_error_and_a_fixed_one_is_accepted(job: Job, change, why):
    good = {
        "headline": "Forklift passing close to a person in the left aisle",
        "first_action": "Keep people out of the forklift lane while it moves",
        "priority": "high",
        "confirmed_finding_ids": ["H01"],
    }
    replies: list[dict[str, Any]] = []

    def script(client: McpClient, brief: str) -> str:
        client.call("hazard_scan_clip", {"clip_id": CLIP})
        client.call("hazard_review_clip", {"clip_id": CLIP})
        replies.append(client.call("hazard_submit_summary", {"clip_id": CLIP, **good, **change}))
        replies.append(client.call("hazard_submit_summary", {"clip_id": CLIP, **good}))
        return "FINAL hazard"

    job.launcher.script = script
    run_dir = job.run()
    bad, fixed = replies
    assert bad["ok"] is False and bad["error"], why
    assert "H09" not in bad["error"] and "https" not in bad["error"]
    assert fixed["ok"] is True
    assert json.loads((run_dir / SUMMARY_FILE).read_text())["priority"] == "high"


def test_a_failed_review_must_be_submitted_as_priority_none(job: Job):
    job.review.fail = True
    replies: list[dict[str, Any]] = []

    def script(client: McpClient, brief: str) -> str:
        client.call("hazard_scan_clip", {"clip_id": CLIP})
        replies.append(client.call("hazard_review_clip", {"clip_id": CLIP}))
        base = {"clip_id": CLIP, "first_action": "Ask a supervisor to look at this area"}
        replies.append(
            client.call(
                "hazard_submit_summary",
                {
                    **base,
                    "headline": "Forklift risk",
                    "priority": "high",
                    "confirmed_finding_ids": [],
                },
            )
        )
        replies.append(
            client.call(
                "hazard_submit_summary",
                {
                    **base,
                    "headline": "The safety check did not finish for this camera",
                    "priority": "none",
                    "confirmed_finding_ids": [],
                },
            )
        )
        return "FINAL hazard"

    job.launcher.script = script
    run_dir = job.run()
    review, bad, good = replies
    assert review["ok"] is True and review["result"]["status"] == "failed"
    assert review["result"]["findings"] == [] and "priority none" in review["result"]["next"]
    assert bad["ok"] is False and "priority must be none" in bad["error"]
    assert good["ok"] is True
    assert json.loads((run_dir / SUMMARY_FILE).read_text())["priority"] == "none"


def test_plain_text_rule_matches_the_spec():
    for text in ("See E012", "zone Z03", "H01 first", "bbox", "SHA256", "http", "QWEN"):
        assert plain_text_problem(text) is not None, text
    assert plain_text_problem("Forklift close to a person in the left aisle") is None


# -- failure handling -----------------------------------------------------------------


def test_a_turn_without_a_summary_keeps_the_reviewed_run_dir(job: Job):
    stale = job.output_root / "0123456789abcdef" / SUMMARY_FILE
    stale.parent.mkdir(parents=True)
    stale.write_text('{"headline": "from an earlier report"}')

    def script(client: McpClient, brief: str) -> str:
        client.call("hazard_scan_clip", {"clip_id": CLIP})
        client.call("hazard_review_clip", {"clip_id": CLIP})
        return "I am done"

    job.launcher.script = script
    run_dir = job.run()
    assert run_dir == job.output_root / "0123456789abcdef"
    assert not (run_dir / SUMMARY_FILE).exists()  # the earlier job's summary is gone too
    trace = json.loads((run_dir / "agent_trace.json").read_text())
    assert any("no summary" in e["text"] for e in trace if e["kind"] == "tool")
    assert any("did not finish its summary" in e["text"] for e in trace if e["kind"] == "say")
    assert json.loads((run_dir / "agent_turn.json").read_text())["submitted"] is False


def test_a_turn_that_never_ran_raises(job: Job):
    job.launcher.fail_before_calls = True
    with pytest.raises(AgentRunError, match="did not run the hazard review"):
        job.run()
    assert job.review.calls == []
    assert wait_for(lambda: job.gateway.active_run_id is None)


def test_each_job_gets_its_own_session_key_and_a_brief_naming_only_the_clip(job: Job):
    job.run()
    job.run()
    first, second = job.launcher.run_ids
    assert first != second and first.startswith(f"hazard-{CLIP}-")
    brief = hazard_brief(CLIP, first)
    assert brief.startswith("HAZARD BRIEF") and f"clip_id: {CLIP}" in brief
    assert all(openclaw_name(t) in brief for t in HAZARD_TOOL_NAMES)


# -- wiring ---------------------------------------------------------------------------


def test_create_agent_app_sets_the_hazard_review_seam(tmp_path: Path):
    token = secrets.token_hex(24)
    settings = Settings(
        manifests_dir=tmp_path / "m", prepared_dir=tmp_path / "p", runs_dir=tmp_path / "r"
    )
    app = create_agent_app(
        settings,
        launcher=HazardLauncher("", token),
        binds=[("127.0.0.1", 0)],
        token=token,
        env={},
    )
    try:
        runner = app.state.hazard_review_runner
        assert isinstance(runner, AgentHazardRunner)
        assert runner.name == RUNNER_NAME == app.state.hazard_review_runner_name
        assert runner.gateway is app.state.tool_server.gateway
        assert runner.timeout_s == 600
    finally:
        app.state.tool_server.close()
