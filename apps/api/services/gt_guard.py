"""Ground-truth leak guard for anything the API sends outward.

``Scenario.model_view()`` removes the ground-truth camera structurally. This guard
covers the free-text channels the view cannot see: titles, provenance notes,
exception messages and executor payloads. A token matches only as a whole
identifier, so ``cam_0`` does not match inside ``cam_01``.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from apps.api.schemas import Scenario

REDACTED = "[withheld]"
_WORD = r"A-Za-z0-9_\-"


def ground_truth_tokens(scenario: Scenario) -> tuple[str, ...]:
    gt = scenario.ground_truth_camera
    posix_file = gt.file.replace("\\", "/")
    tokens = {gt.id, gt.file, posix_file, PurePosixPath(posix_file).name}
    return tuple(sorted((t for t in tokens if t), key=len, reverse=True))


class GtGuard:
    def __init__(self, tokens: tuple[str, ...]) -> None:
        self.tokens = tokens
        alternatives = "|".join(re.escape(t) for t in tokens)
        self._pattern = (
            re.compile(f"(?<![{_WORD}])(?:{alternatives})(?![{_WORD}])") if tokens else None
        )

    @classmethod
    def for_scenario(cls, scenario: Scenario) -> GtGuard:
        return cls(ground_truth_tokens(scenario))

    # The basename token also catches Windows and JSON-escaped spellings of the path.
    def leaks(self, text: str) -> bool:
        return bool(self._pattern and self._pattern.search(text))

    def redact(self, text: str) -> str:
        return self._pattern.sub(REDACTED, text) if self._pattern else text

    def redact_obj(self, obj: Any) -> Any:
        """Return a copy of a JSON-able structure with every string value redacted."""
        if isinstance(obj, str):
            return self.redact(obj)
        if isinstance(obj, dict):
            return {k: self.redact_obj(v) for k, v in obj.items()}
        if isinstance(obj, list | tuple):
            return [self.redact_obj(v) for v in obj]
        return obj
