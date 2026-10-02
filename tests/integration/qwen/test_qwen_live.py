"""Live Qwen perception on real footage through Ollama (skips when unavailable).

Asserts contract validity, side-channel telemetry and the thinking toggle; it does not
score what the model saw. Latencies print with ``-s`` and are recorded in P07.md.
"""

from __future__ import annotations

import pytest

from apps.api.schemas import validate_json
from inference.base import CallInfo, PerceptionOptions
from inference.client import ChatClient, ModelCallError
from inference.perception import OpenAICompatPerceptionAdapter
from inference.profiles import load_profile
from tests.integration.qwen.footage import extract_manifest, first_clip, require_model

pytestmark = [pytest.mark.live_model, pytest.mark.media]


@pytest.fixture(scope="module")
def footage(tmp_path_factory):
    camera_id, clip = first_clip()
    return extract_manifest(clip, camera_id, tmp_path_factory.mktemp("frames"))


@pytest.mark.parametrize("profile_name", ["lite-local", "full-local"])
def test_perception_on_real_footage(profile_name, footage):
    profile = load_profile(profile_name, env={})
    require_model(profile.perception)
    infos: list[CallInfo] = []
    adapter = OpenAICompatPerceptionAdapter(profile)
    batch = adapter.inspect(
        footage.camera_id, footage, PerceptionOptions(strict=True, telemetry=infos.append)
    )
    validate_json("observation_batch", batch.model_dump(mode="json"))
    (info,) = infos
    assert info.ok and info.latency_s > 0 and info.finish_reason == "stop"
    assert info.model == profile.perception.model
    sent = {f.index: f.t for f in footage.frames if f.index in info.frames_sent}
    for obs in batch.observations:
        assert set(obs.supporting_frames) <= set(sent)
        assert obs.t_start == min(sent[i] for i in obs.supporting_frames)
        assert obs.id.startswith(f"{footage.camera_id}.o")
    print(
        f"\nLIVE perception {profile_name} {info.model}: {info.latency_s:.2f}s "
        f"attempts={info.attempts} repaired={info.repaired} frames={len(info.frames_sent)} "
        f"usage={info.usage} observations={len(batch.observations)} "
        f"cues={[o.cue_type for o in batch.observations]} warnings={info.warnings}"
    )


def test_qwen35_needs_thinking_disabled_explicitly():
    """qwen3.5 is hybrid-thinking: unset, it reasons first and can return empty content."""
    endpoint = load_profile("full-local", env={}).perception
    require_model(endpoint)
    endpoint = endpoint.model_copy(update={"retries": 0, "structured_output": "none"})
    messages = [{"role": "user", "content": "In one short sentence: what is a traffic queue?"}]

    off = ChatClient(endpoint.model_copy(update={"think": False})).chat(messages, max_tokens=96)
    assert off.content.strip() and off.reasoning_chars == 0

    try:
        on = ChatClient(endpoint.model_copy(update={"think": None})).chat(messages, max_tokens=96)
    except ModelCallError as exc:
        assert "empty content" in str(exc)
        outcome = f"empty content within 96 tokens ({exc})"
    else:
        assert on.reasoning_chars > 0
        outcome = f"content after {on.reasoning_chars} reasoning chars"
    print(f"\nLIVE thinking qwen3.5:9b off: {off.latency_s:.2f}s, 0 reasoning chars; on: {outcome}")
