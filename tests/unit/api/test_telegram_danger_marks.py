"""The ping photo is marked at the top hazard's zone only (sign + zone label)."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from apps.api.services import hazard_telegram as T
from apps.api.services import hazards

pytestmark = pytest.mark.screen_filter


def _jpeg(w: int = 320, h: int = 180) -> bytes:
    out = BytesIO()
    Image.new("RGB", (w, h), (40, 40, 40)).save(out, format="JPEG")
    return out.getvalue()


def test_marks_only_the_top_hazards_zone() -> None:
    report = {
        "status": hazards.REVIEW_COMPLETE,
        "video": {"analysis_width": 100, "analysis_height": 100},
        "zones": [
            {"zone_id": "Z03", "bbox_analysis": [10, 10, 40, 40]},
            {"zone_id": "Z07", "bbox_analysis": [50, 50, 90, 90]},
        ],
        "findings": [
            {
                "finding_id": "H01",
                "severity": "medium",
                "standards": ["1910.176(a)"],
                "zone_ids": ["Z07"],
            },
            {
                "finding_id": "H02",
                "severity": "high",
                "standards": ["1910.22(a)(3)"],
                "zone_ids": ["Z03"],
            },
            {
                "finding_id": "H03",
                "severity": "high",
                "standards": ["1910.212(a)(3)(ii)"],
                "zone_ids": ["Z07"],
            },
        ],
    }
    marks = T.danger_marks(report, hazards.load_wording(), "hazard")
    assert len(marks) == 1
    box, label = marks[0]
    assert label == "SLIP / TRIP · ZONE 3"
    assert box == pytest.approx((0.1, 0.1, 0.4, 0.4))


def test_mark_photo_draws_and_falls_back() -> None:
    data = _jpeg()
    marked = T.mark_photo(data, (((0.1, 0.1, 0.4, 0.4), "SLIP / TRIP · ZONE 3"),))
    assert marked != data and Image.open(BytesIO(marked)).size == (320, 180)
    assert T.mark_photo(data, ()) == data
    assert T.mark_photo(b"not a jpeg", (((0, 0, 1, 1), "X"),)) == b"not a jpeg"
