"""P07: perception post-processing, live-adapter request shaping, repair, budget, fixtures."""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from apps.api.schemas import FrameRef, ObservationBatch, validate_json
from inference.base import (
    AdapterError,
    CallInfo,
    PerceptionAdapter,
    PerceptionOptions,
    load_prompt,
)
from inference.frames import FRAME_LABEL_TOKENS, image_tokens, text_tokens
from inference.perception import (
    CONTEXT_SAFETY_TOKENS,
    MAX_OBSERVATIONS,
    PROMPT_FILE,
    FixturePerceptionAdapter,
    OpenAICompatPerceptionAdapter,
    OutputFormatError,
    _header,
    observation_schema,
    postprocess_observations,
)
from inference.profiles import EndpointConfig, ModelProfile
from inference.vocab import CUE_TYPES

FRAMES = [FrameRef(index=i, frame_id=30 * i, t=10.0 + 0.5 * i) for i in range(6)]


def _obs(**kw):
    base = {
        "supporting_frames": [1],
        "cue_type": "traffic_reaction",
        "description": "cars brake",
        "direction": "left",
        "confidence": 0.7,
    }
    return {**base, **kw}


def _post(items, frames=FRAMES):
    return postprocess_observations({"observations": items}, "cam_01", frames)


# --- post-processing ----------------------------------------------------------------------


def test_times_come_from_cited_frames_not_the_model():
    batch, _, _ = _post([_obs(supporting_frames=[3, 1], t_start=99.0, t_end=120.0)])
    (o,) = batch.observations
    assert (o.t_start, o.t_end, o.supporting_frames) == (10.5, 11.5, [1, 3])


def test_ids_are_camera_scoped_sequential_and_time_ordered():
    batch, _, _ = _post(
        [_obs(supporting_frames=[4]), _obs(supporting_frames=[0], cue_type="human_reaction")]
    )
    assert [o.id for o in batch.observations] == ["cam_01.o1", "cam_01.o2"]
    assert [o.supporting_frames for o in batch.observations] == [[0], [4]]
    assert batch.camera_id == "cam_01"


def test_camera_id_is_forced_even_if_the_model_names_another():
    raw = {"camera_id": "cam_gt", "observations": [_obs()]}
    batch, _, _ = postprocess_observations(raw, "cam_01", FRAMES)
    assert batch.camera_id == "cam_01" and batch.observations[0].id.startswith("cam_01.")


@pytest.mark.parametrize("frames", [[7], [0, 6], [-1], ["frame two"], [True]])
def test_observations_citing_unsupplied_frames_are_dropped(frames):
    batch, warnings, dropped = _post([_obs(supporting_frames=frames), _obs()])
    assert len(batch.observations) == 1 and dropped == 1
    assert any("outside the supplied set" in w for w in warnings)


def test_only_frames_actually_sent_are_citable():
    sent = [FRAMES[0], FRAMES[5]]  # budget guard dropped 1..4
    batch, _, dropped = _post([_obs(supporting_frames=[2]), _obs(supporting_frames=[5])], sent)
    assert dropped == 1 and batch.observations[0].supporting_frames == [5]


def test_string_frame_citations_are_parsed():
    batch, _, _ = _post([_obs(supporting_frames=["2", "frame 3", 4.0])])
    assert batch.observations[0].supporting_frames == [2, 3, 4]


def test_uncited_observation_uses_frames_inside_its_stated_window():
    batch, _, _ = _post([_obs(supporting_frames=[], t_start=10.4, t_end=11.1)])
    assert batch.observations[0].supporting_frames == [1, 2]
    assert (batch.observations[0].t_start, batch.observations[0].t_end) == (10.5, 11.0)


@pytest.mark.parametrize("extra", [{}, {"t_start": 50.0}, {"t_start": "soon"}])
def test_uncited_observation_without_a_valid_window_is_dropped(extra):
    item = {k: v for k, v in _obs(**extra).items() if k != "supporting_frames"}
    batch, warnings, dropped = _post([item])
    assert batch.observations == [] and dropped == 1
    assert any("cites no supplied frame" in w for w in warnings)


def test_conclusion_cue_types_are_mapped_to_observation_vocabulary():
    batch, warnings, _ = _post(
        [_obs(cue_type="car crash"), _obs(supporting_frames=[2], cue_type="explosion")]
    )
    assert {o.cue_type for o in batch.observations} == {"other"}
    assert any("normalized to 'other'" in w for w in warnings)


def test_every_output_cue_type_is_in_the_vocabulary():
    raw = ["Vehicles Braking", "fire", "head turn", "???", "smoke", "glare"]
    batch, _, _ = _post([_obs(cue_type=c, supporting_frames=[i]) for i, c in enumerate(raw)])
    assert all(o.cue_type in CUE_TYPES for o in batch.observations)


def test_directions_are_normalized_or_nulled():
    batch, _, _ = _post(
        [
            _obs(direction="Center-Left", supporting_frames=[0]),
            _obs(direction="NE", supporting_frames=[1]),
            _obs(direction="somewhere", supporting_frames=[2]),
        ]
    )
    assert [o.direction for o in batch.observations] == ["center_left", "northeast", None]


@pytest.mark.parametrize(
    "raw, expected", [(0.8, 0.8), (85, 0.85), ("70%", 0.7), ("high", 0.8), (-2, 0.0), (None, 0.5)]
)
def test_confidence_is_clamped_and_rescaled(raw, expected):
    batch, _, _ = _post([_obs(confidence=raw)])
    assert batch.observations[0].confidence == pytest.approx(expected)


def test_duplicates_collapse_to_max_confidence():
    batch, _, dropped = _post([_obs(confidence=0.4), _obs(confidence=0.9)])
    assert len(batch.observations) == 1 and dropped == 1
    assert batch.observations[0].confidence == 0.9


def test_observation_count_is_capped_by_confidence():
    frames = [FrameRef(index=i, frame_id=i, t=float(i)) for i in range(20)]
    items = [_obs(supporting_frames=[i], confidence=i / 100) for i in range(20)]
    batch, _, dropped = _post(items, frames)
    assert len(batch.observations) == MAX_OBSERVATIONS and dropped == 20 - MAX_OBSERVATIONS
    assert min(o.confidence for o in batch.observations) == pytest.approx(0.08)


@pytest.mark.parametrize(
    "raw",
    [
        [_obs()],
        {"visible_cues": [_obs()]},
        _obs(),
        {"camera_id": "cam_01", "observations": [_obs()]},
    ],
    ids=["bare-list", "other-key", "single-object", "full-batch"],
)
def test_tolerated_output_shapes(raw):
    batch, _, _ = postprocess_observations(raw, "cam_01", FRAMES)
    assert len(batch.observations) == 1


@pytest.mark.parametrize(
    "raw", [{"visible_motion_cues": ["a person walks"]}, {"a": [], "b": []}, "text", 3, None]
)
def test_unusable_shapes_raise_output_format_error(raw):
    with pytest.raises(OutputFormatError):
        postprocess_observations(raw, "cam_01", FRAMES)


def test_empty_observation_list_is_valid():
    batch, warnings, dropped = _post([])
    assert batch.observations == [] and dropped == 0 and warnings == []


def test_output_satisfies_the_json_schema():
    batch, _, _ = _post([_obs(), _obs(supporting_frames=[2, 3], direction=None)])
    validate_json("observation_batch", batch.model_dump(mode="json"))


def test_description_is_flagged_not_rewritten_when_it_names_an_event():
    batch, warnings, _ = _post([_obs(description="a  car   crash   just\nhappened")])
    assert batch.observations[0].description == "a car crash just happened"
    assert any("names a final-event class" in w for w in warnings)


def test_schema_enumerates_sent_frames_and_vocabularies():
    schema = observation_schema([0, 3, 5])
    item = schema["properties"]["observations"]["items"]["properties"]
    assert item["supporting_frames"]["items"]["enum"] == [0, 3, 5]
    assert item["cue_type"]["enum"] == list(CUE_TYPES)
    assert {"type": "null"} in item["direction"]["anyOf"]


# --- live adapter over a mock OpenAI-compatible server ------------------------------------


def _adapter(profile, server, **endpoint) -> OpenAICompatPerceptionAdapter:
    if endpoint:
        profile = profile.model_copy(
            update={"perception": profile.perception.model_copy(update=endpoint)}
        )
    return OpenAICompatPerceptionAdapter(profile, transport=server.transport, sleep=lambda s: None)


def _images(request) -> list[str]:
    return [
        p["image_url"]["url"]
        for p in request["messages"][1]["content"]
        if p.get("type") == "image_url"
    ]


def test_request_carries_labelled_downscaled_frames(lite_profile, manifest, mock_server, reply):
    server = mock_server(reply({"observations": []}))
    _adapter(lite_profile, server).inspect("cam_01", manifest, PerceptionOptions())
    (req,) = server.requests
    assert req["model"] == "qwen3-vl:4b-instruct"
    assert req["reasoning_effort"] == "none"
    assert req["messages"][0]["role"] == "system"
    assert "visual observation extractor" in req["messages"][0]["content"]
    parts = req["messages"][1]["content"]
    labels = [p["text"] for p in parts if p["type"] == "text"][1:]
    assert labels == [f"Frame index={i} t={float(i):.2f}s" for i in range(6)]
    kinds = [p["type"] for p in parts[1:]]
    assert kinds == ["text", "image_url"] * 6  # every image directly follows its label
    urls = _images(req)
    assert all(u.startswith("data:image/jpeg;base64,") for u in urls)
    width = Image.open(io.BytesIO(base64.b64decode(urls[0].split(",", 1)[1]))).size[0]
    assert width == 512  # 1024-wide source downscaled to max_image_width
    enum = req["response_format"]["json_schema"]["schema"]["properties"]["observations"]
    assert enum["items"]["properties"]["supporting_frames"]["items"]["enum"] == list(range(6))


def test_code_fenced_reply_is_parsed_and_post_processed(lite_profile, manifest, mock_server, reply):
    body = "```json\n" + json.dumps({"observations": [_obs(supporting_frames=[2, 4])]}) + "\n```"
    server = mock_server(reply(body))
    batch = _adapter(lite_profile, server).inspect("cam_01", manifest, PerceptionOptions())
    (o,) = batch.observations
    assert (o.id, o.t_start, o.t_end) == ("cam_01.o1", 2.0, 4.0)


def test_invalid_json_triggers_one_text_only_repair(lite_profile, manifest, mock_server, reply):
    server = mock_server(reply("I see a car braking."), reply({"observations": [_obs()]}))
    adapter = _adapter(lite_profile, server)
    batch = adapter.inspect("cam_01", manifest, PerceptionOptions())
    assert len(batch.observations) == 1
    assert adapter.last_call.repaired and adapter.last_call.ok
    assert len(server.requests) == 2
    repair = server.requests[1]["messages"]
    assert all(isinstance(m["content"], str) for m in repair)  # no images re-sent
    assert "I see a car braking." in repair[1]["content"]


def test_invalid_twice_returns_empty_batch_and_surfaces_failure(
    lite_profile, manifest, mock_server, reply
):
    server = mock_server(reply("nope"), reply("still nope"))
    infos: list[CallInfo] = []
    adapter = _adapter(lite_profile, server)
    batch = adapter.inspect("cam_01", manifest, PerceptionOptions(telemetry=infos.append))
    assert batch == ObservationBatch(camera_id="cam_01", observations=[])
    validate_json("observation_batch", batch.model_dump(mode="json"))
    (info,) = infos
    assert not info.ok and "after repair" in info.error and info.repaired
    assert len(server.requests) == 2


def test_strict_mode_raises_instead_of_degrading(lite_profile, manifest, mock_server, reply):
    server = mock_server(reply("nope"))
    with pytest.raises(AdapterError, match="after repair"):
        _adapter(lite_profile, server).inspect("cam_01", manifest, PerceptionOptions(strict=True))


def test_endpoint_down_degrades_to_empty_batch(lite_profile, manifest, mock_server):
    server = mock_server(500)
    adapter = _adapter(lite_profile, server)
    batch = adapter.inspect("cam_01", manifest, PerceptionOptions())
    assert batch.observations == []
    assert not adapter.last_call.ok and "HTTP 500" in adapter.last_call.error
    assert adapter.last_call.attempts == lite_profile.perception.retries + 1


def test_context_budget_subsamples_frames_uniformly(lite_profile, manifest, mock_server, reply):
    server = mock_server(reply({"observations": []}))
    system, _ = load_prompt(PROMPT_FILE)
    fixed = text_tokens(system) + text_tokens(_header("cam_01", manifest.frames))
    per_frame = image_tokens(512, 288, 32) + FRAME_LABEL_TOKENS  # 1024x576 downscaled to 512
    budget = fixed + 512 + CONTEXT_SAFETY_TOKENS + 3 * per_frame + per_frame // 2  # 3, not 4
    adapter = _adapter(lite_profile, server, context_tokens=budget, max_tokens=512)
    adapter.inspect("cam_01", manifest, PerceptionOptions())
    info = adapter.last_call
    assert info.frames_sent == [0, 3, 5] and info.frames_skipped == [1, 2, 4]
    assert len(_images(server.requests[0])) == 3
    assert any("sent 3 of 6 frames" in w for w in info.warnings)


def test_context_too_small_for_one_frame_fails_without_a_call(
    lite_profile, manifest, mock_server, reply
):
    server = mock_server(reply({"observations": []}))
    adapter = _adapter(lite_profile, server, context_tokens=1200, max_tokens=900)
    batch = adapter.inspect("cam_01", manifest, PerceptionOptions())
    assert batch.observations == [] and not adapter.last_call.ok
    assert "cannot fit one frame" in adapter.last_call.error and server.requests == []


def test_max_frames_option_limits_frames(lite_profile, manifest, mock_server, reply):
    server = mock_server(reply({"observations": []}))
    adapter = _adapter(lite_profile, server)
    adapter.inspect("cam_01", manifest, PerceptionOptions(max_frames=3))
    assert adapter.last_call.frames_sent == [0, 3, 5]  # 2.5 rounds half-up; ends always kept


def test_missing_frame_files_are_skipped(lite_profile, manifest, mock_server, reply):
    manifest.frames[1].path = "does/not/exist.jpg"
    server = mock_server(reply({"observations": []}))
    adapter = _adapter(lite_profile, server)
    adapter.inspect("cam_01", manifest, PerceptionOptions())
    assert 1 not in adapter.last_call.frames_sent and 1 in adapter.last_call.frames_skipped


def test_latency_and_model_go_to_the_side_channel_only(lite_profile, manifest, mock_server, reply):
    server = mock_server(reply({"observations": [_obs()]}, model="qwen3-vl:4b-instruct"))
    infos: list[CallInfo] = []
    adapter = _adapter(lite_profile, server)
    batch = adapter.inspect(
        "cam_01", manifest, PerceptionOptions(scenario_id="s1", telemetry=infos.append)
    )
    assert set(batch.model_dump()) == {"camera_id", "observations"}
    (info,) = infos
    assert info is adapter.last_call
    assert info.model == "qwen3-vl:4b-instruct" and info.latency_s > 0
    assert info.scenario_id == "s1" and info.prompt_version and info.usage["total_tokens"] == 120


def test_manifest_for_another_camera_is_rejected(lite_profile, manifest, mock_server, reply):
    with pytest.raises(ValueError, match="manifest is for camera"):
        _adapter(lite_profile, mock_server(reply("{}"))).inspect(
            "cam_02", manifest, PerceptionOptions()
        )


# --- fixture adapter ----------------------------------------------------------------------


def test_fixture_adapter_returns_schema_valid_batch(fixture_profile, manifest):
    adapter = FixturePerceptionAdapter(fixture_profile)
    batch = adapter.inspect("cam_01", manifest, PerceptionOptions())
    validate_json("observation_batch", batch.model_dump(mode="json"))
    assert batch.camera_id == "cam_01" and batch.observations


def test_fixture_and_live_adapters_share_the_interface(fixture_profile, lite_profile):
    assert isinstance(FixturePerceptionAdapter(fixture_profile), PerceptionAdapter)
    assert isinstance(OpenAICompatPerceptionAdapter(lite_profile), PerceptionAdapter)


def test_fixture_camera_missing_gives_empty_batch_with_warning(fixture_profile, manifest):
    manifest = manifest.model_copy(update={"camera_id": "cam_09"})
    adapter = FixturePerceptionAdapter(fixture_profile)
    batch = adapter.inspect("cam_09", manifest, PerceptionOptions())
    assert batch.observations == [] and adapter.last_call.ok
    assert any("no camera" in w for w in adapter.last_call.warnings)


def test_fixture_flags_frames_beyond_the_manifest(fixture_profile, manifest):
    adapter = FixturePerceptionAdapter(fixture_profile)
    adapter.inspect("cam_01", manifest, PerceptionOptions())  # fixture cites frame 8; 6 frames
    assert any("beyond this manifest" in w for w in adapter.last_call.warnings)


def test_per_scenario_fixture_is_preferred(tmp_path, manifest):
    shared = tmp_path / "qwen_observations.json"
    shared.write_text(json.dumps({"cam_01": {"camera_id": "cam_01", "observations": []}}))
    (tmp_path / "scen").mkdir()
    per = {
        "cam_01": {
            "camera_id": "cam_01",
            "observations": [
                {
                    "id": "x1",
                    "t_start": 1.0,
                    "t_end": 2.0,
                    "cue_type": "human_reaction",
                    "description": "d",
                    "confidence": 0.5,
                    "supporting_frames": [1, 2],
                }
            ],
        }
    }
    (tmp_path / "scen" / "qwen_observations.json").write_text(json.dumps(per))
    ep = EndpointConfig(backend="fixture", fixture=str(shared), fixture_dir=str(tmp_path))
    profile = ModelProfile(profile="t", mode="fixture", perception=ep, reasoning=ep)
    adapter = FixturePerceptionAdapter(profile)
    assert adapter.inspect("cam_01", manifest, PerceptionOptions(scenario_id="scen")).observations
    assert not adapter.inspect("cam_01", manifest, PerceptionOptions(scenario_id="x")).observations


def test_unreadable_fixture_degrades_and_strict_raises(tmp_path, manifest):
    ep = EndpointConfig(backend="fixture", fixture=str(tmp_path / "missing.json"))
    adapter = FixturePerceptionAdapter(
        ModelProfile(profile="t", mode="fixture", perception=ep, reasoning=ep)
    )
    assert adapter.inspect("cam_01", manifest, PerceptionOptions()).observations == []
    assert not adapter.last_call.ok
    with pytest.raises(AdapterError):
        adapter.inspect("cam_01", manifest, PerceptionOptions(strict=True))
