"""Wire contracts shared by the API, tools, inference adapters, harness and eval."""

from ._base import CONTRACTS_DIR, REPO_ROOT, Contract
from .contracts import is_valid, load_schema, validate_json
from .evidence import (
    BundleCamera,
    EvidenceBundle,
    EvidenceCluster,
    EvidenceItem,
    RegionCandidate,
)
from .hypothesis import UNKNOWN, Alternative, Hypothesis
from .media import FrameRef, MediaManifest
from .observation import COMPASS_DIRECTIONS, IMAGE_DIRECTIONS, Observation, ObservationBatch
from .run import (
    EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    EventType,
    RunRecord,
    RunRequest,
    RunState,
    SseEnvelope,
)
from .scenario import (
    Camera,
    GroundTruthAccessError,
    ModelCamera,
    ModelScenarioView,
    Scenario,
    Zone,
)

__all__ = [
    "COMPASS_DIRECTIONS",
    "CONTRACTS_DIR",
    "EVENT_TYPES",
    "IMAGE_DIRECTIONS",
    "REPO_ROOT",
    "TERMINAL_EVENT_TYPES",
    "UNKNOWN",
    "Alternative",
    "BundleCamera",
    "Camera",
    "Contract",
    "EventType",
    "EvidenceBundle",
    "EvidenceCluster",
    "EvidenceItem",
    "FrameRef",
    "GroundTruthAccessError",
    "Hypothesis",
    "MediaManifest",
    "ModelCamera",
    "ModelScenarioView",
    "Observation",
    "ObservationBatch",
    "RegionCandidate",
    "RunRecord",
    "RunRequest",
    "RunState",
    "Scenario",
    "SseEnvelope",
    "Zone",
    "is_valid",
    "load_schema",
    "validate_json",
]
