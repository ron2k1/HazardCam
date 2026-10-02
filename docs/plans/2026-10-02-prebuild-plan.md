# Prebuild execution plan and interface contracts (2026-10-02)

Scope: P00-P16 only. D00-D04 (OpenClaw agent, tool registration, playbook, NemoClaw/OpenShell wiring) are built on event day and are NOT touched here. `agent/` stays templates and READMEs only.

Branch: `feat/prebuild`. The integrator commits after verifying each task. Workers never commit.

## Runtime layout

| Piece | Where | Run |
|---|---|---|
| Python env | `.venv` (uv, CPython 3.12), deps in `pyproject.toml` | `.venv/Scripts/python.exe` (Win) / `.venv/bin/python` (Linux) |
| API | `apps/api` (FastAPI) | `python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8080` |
| Web | `apps/web` (Next.js App Router, TS, Tailwind, shadcn) | `pnpm --dir apps/web dev` on :3000 |
| Local models (lite) | Ollama OpenAI-compatible `http://127.0.0.1:11434/v1` | `qwen3-vl:4b-instruct` + `ministral-3:3b` |
| Closest-full on 8 GB | same endpoint | `qwen3.5:9b` + `ministral-3:8b` |
| Tests | `pytest` (importlib mode), Playwright in `tests/e2e` | `python -m pytest` |

Python packages are imported from the repo root: `apps.api.*`, `tools.*`, `inference.*`, `harness.*`, `eval.*`. Every package directory has an `__init__.py`. Write paths with `pathlib`. The event-day box is ARM64 Linux, so nothing may be Windows-only. Do not add dependencies. If one is truly needed, the integrator adds it to `pyproject.toml`.

## Shared contracts (P01, done first, frozen for workers)

JSON Schemas in `contracts/*.schema.json` are the source of truth. Pydantic mirrors live in `apps/api/schemas` and are importable as `from apps.api.schemas import ...`. Use `validate_json(name, obj)` to check a dict against a schema.

- `Scenario` / `Camera` / `Zone`. Coordinates are a local metric frame `[x_east_m, y_north_m]`. `heading_deg` is a compass bearing (0 = north/+y, 90 = east/+x, clockwise). Each camera has an optional `time_offset_s`, where scenario time = media time + offset.
- `Scenario.model_view() -> ModelScenarioView`. This is the ONLY scenario object that may reach tools, adapters, the harness or prompts. It contains no ground-truth field (`extra=forbid`). `Scenario.require_model_camera(id)` and `ModelScenarioView.camera(id)` raise `GroundTruthAccessError` for the GT camera.
- `MediaManifest` / `FrameRef(index, frame_id, t, path)`. `index` is the position in `frames[]`, and that is what `Observation.supporting_frames` cites. `t` is media seconds and is the UI seek target.
- `ObservationBatch` / `Observation`. `direction` is image-relative (`left|center_left|center|center_right|right|toward_camera|away_from_camera`), compass (`north..northwest`), or null.
- `EvidenceBundle` (status `ok|insufficient`, cameras, evidence, clusters, region_candidates, notes). Referential integrity is validated, and evidence from unknown or withheld cameras is rejected.
- `Hypothesis` / `Alternative`. `event_type == "unknown"` is the abstain path.
- `RunRequest`, `RunRecord`, `SseEnvelope`, `EVENT_TYPES`. SSE payloads are cataloged in `contracts/SSE_EVENTS.md`.

## Tool surface (ordinary functions; the future OpenClaw tools wrap these on event day)

Every tool is a plain, synchronous, deterministic-where-possible Python function. It takes and returns contract models (or JSON-able dicts) and has no global state.

```python
# P04  tools/sample_video.py  (+ helpers in tools/media/)
def sample_video(video_path: Path, camera_id: str, *, out_dir: Path, sample_fps: float = 1.0,
                 max_frames: int = 8, start_s: float = 0.0, end_s: float | None = None,
                 clip: bool = False, jpeg_quality: int = 3, max_width: int = 768) -> MediaManifest
def probe_video(video_path: Path) -> dict   # duration_s, src_fps, width, height, nb_frames

# P07  tools/inspect_camera.py
def inspect_camera(camera_id: str, media_manifest: MediaManifest,
                   perception_options: PerceptionOptions | None = None, *,
                   adapter: PerceptionAdapter | None = None) -> ObservationBatch

# P08  tools/correlate.py
def correlate_observations(batches: list[ObservationBatch], view: ModelScenarioView, *,
                           tolerance_s: float = 1.5, min_confidence: float = 0.3
                           ) -> tuple[list[EvidenceItem], list[EvidenceCluster]]
# P08  tools/triangulate.py
def triangulate_region(evidence: list[EvidenceItem], clusters: list[EvidenceCluster],
                       view: ModelScenarioView) -> list[RegionCandidate]
def build_evidence_bundle(batches, view, **kw) -> EvidenceBundle   # correlate + triangulate + status

# P09  tools/reason_hypothesis.py
def reason_hypothesis(evidence_bundle: EvidenceBundle,
                      reasoning_options: ReasoningOptions | None = None, *,
                      adapter: ReasoningAdapter | None = None) -> Hypothesis

# P10  tools/supporting_frames.py, tools/submit.py
def get_supporting_frames(camera_id: str, frame_indices: list[int], media_manifest: MediaManifest) -> list[FrameRef]
def submit_hypothesis(hypothesis: Hypothesis, evidence_bundle: EvidenceBundle) -> Hypothesis
    # validates evidence_ids is a subset of the bundle, the region is a known candidate or "unknown",
    # and alternatives are sorted; returns the normalized hypothesis
```

Ground-truth rule for tools: the tools receive `ModelScenarioView` or `MediaManifest`, never `Scenario`. The harness builds media manifests only for `view.cameras`. `inspect_camera` checks that `media_manifest.camera_id` is in the view when a view is supplied.

## Inference package (P06/P07/P09)

```python
# inference/profiles.py
def load_profile(name: str | None = None) -> ModelProfile   # name defaults to $MODEL_PROFILE, else "fixture"
# reads config/models/<name>.yaml; env overrides QWEN_BASE_URL/QWEN_MODEL/MISTRAL_BASE_URL/MISTRAL_MODEL;
# never reads secrets; an api_key, if ever needed, comes from env var named in the profile (api_key_env)

# inference/base.py
class PerceptionAdapter(Protocol):
    name: str
    def inspect(self, camera_id: str, media: MediaManifest, options: PerceptionOptions) -> ObservationBatch: ...
class ReasoningAdapter(Protocol):
    name: str
    def reason(self, bundle: EvidenceBundle, options: ReasoningOptions) -> Hypothesis: ...
def get_perception_adapter(profile: ModelProfile) -> PerceptionAdapter
def get_reasoning_adapter(profile: ModelProfile) -> ReasoningAdapter
```

Fixture adapters read `data/fixtures/<scenario_id>/qwen_observations.json` and `final_hypothesis.json` when those exist, otherwise `data/fixtures/*.json` (the path from the profile). The OpenAI-compatible adapters use `httpx` against `<base_url>/chat/completions` with JSON-mode or schema-constrained output where the server supports it, plus timeout, bounded retries, a repair-and-validate pass, and an explicit thinking toggle. Thinking models can return empty content under token caps, so prefer `-instruct` tags.

## Harness (P10): NON-AGENT, fixed sequence

```python
# harness/dev_sequence.py
def run_dev_sequence(scenario: Scenario, profile: ModelProfile, emit: Callable[[str, dict], None], *,
                     run_dir: Path, pace_s: float = 0.0) -> Hypothesis
```

It calls `scenario.model_view()` exactly once at the top and never touches `scenario.ground_truth_camera` afterwards. The fixed order is: per visible camera `sample_video` then `inspect_camera`, followed by `correlate_observations`, `triangulate_region` / `build_evidence_bundle`, `get_supporting_frames`, `reason_hypothesis`, and `submit_hypothesis`. It emits the SSE events in `contracts/SSE_EVENTS.md`. `emit` is thread-safe. The API runs the harness in a worker thread.

## API (P03)

Spec: `docs/BACKEND_SPEC.md`. Additions:
- Scenarios are loaded from `data/manifests/*.json` and validated with `Scenario`. Public responses use the model view plus judge-safe display fields. They never include GT paths.
- `GET /api/judge/scenarios/{id}` returns GT camera metadata plus `expected.json`. `GET /api/judge/scenarios/{id}/video` streams the GT mp4. Both routes are clearly judge-only and only the UI calls them.
- `GET /media/scenarios/{id}/cameras/{camera_id}` streams visible-camera mp4 with HTTP Range support. It returns 403 for the GT camera id.
- `GET /media/runs/{run_id}/frames/{camera_id}/{index}.jpg` serves sampled frames.
- `GET /api/models/health` reports the active profile and pings each endpoint's `/models`.
- CORS allows `http://127.0.0.1:3000` and `http://localhost:3000`.
- Runs live in memory and are also written to `data/runs/<run_id>/{run.json,events.jsonl}`.

## Waves

1. P00 + P01 (integrator), with P05 data running in the background.
2. In parallel: P02 web shell, P03 API, P04 media, P06+P07+P09 inference, P08 fusion.
3. P10 harness (integrator), then P11 dashboard and P12 eval in parallel.
4. P13 fixture E2E, P14 lite-local E2E, P15 closest-full benchmark.
5. P16 offline bundle, script fixes, boundary check, snapshot. Then the non-optional code review.

## Known script bugs to fix in P16

- `scripts/task_status.py` reads `state`, but the file uses `status`.
- `event_day_task_runner.sh` checks for `EVENT_DAY_START.json`, but `event_day_start.sh` writes `START.txt`.
- `snapshot_prebuild.sh` hardcodes `python3` and uses `/` prefix checks.
- `make` is absent on the Windows dev box, so a `scripts/run.sh` wrapper is needed.
- The `fixture-e2e`, `lite-e2e` and `eval` Makefile targets are placeholders.
