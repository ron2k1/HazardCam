"""inspect_camera: one camera's sampled frames -> observation-only ObservationBatch.

Thin tool wrapper over the perception adapter selected by the active model profile. The
ground-truth rule is enforced here before any frame reaches a model: when the options
carry the model scenario view, only cameras in that view may be inspected.
"""

from __future__ import annotations

from apps.api.schemas import (
    GroundTruthAccessError,
    MediaManifest,
    ModelScenarioView,
    ObservationBatch,
    Scenario,
)
from inference.base import PerceptionAdapter, PerceptionOptions, get_perception_adapter
from inference.profiles import load_profile


def inspect_camera(
    camera_id: str,
    media_manifest: MediaManifest | dict,
    perception_options: PerceptionOptions | None = None,
    *,
    adapter: PerceptionAdapter | None = None,
) -> ObservationBatch:
    """Return schema-valid observations for ``camera_id`` (never a final-event label).

    Raises ``GroundTruthAccessError`` for a camera outside the supplied model view (or if
    a raw ``Scenario`` is smuggled in as the view) and ``ValueError`` when the manifest
    belongs to another camera. Model failures degrade to an empty batch; details go to
    ``perception_options.telemetry`` / ``adapter.last_call`` (or raise with ``strict``).
    """
    options = perception_options or PerceptionOptions()
    manifest = (
        media_manifest
        if isinstance(media_manifest, MediaManifest)
        else MediaManifest.model_validate(media_manifest)
    )
    if manifest.camera_id != camera_id:
        raise ValueError(f"manifest belongs to camera {manifest.camera_id!r}, not {camera_id!r}")
    view = options.scenario_view
    if isinstance(view, Scenario):
        raise GroundTruthAccessError("pass Scenario.model_view(), never the raw Scenario")
    if view is not None:
        if not isinstance(view, ModelScenarioView):
            raise TypeError(f"scenario_view must be ModelScenarioView, got {type(view).__name__}")
        view.camera(camera_id)  # raises GroundTruthAccessError for withheld/unknown ids
    if adapter is None:
        adapter = get_perception_adapter(load_profile())
    batch = adapter.inspect(camera_id, manifest, options)
    if batch.camera_id != camera_id:
        raise RuntimeError(f"adapter {adapter.name} returned camera {batch.camera_id!r}")
    return batch
