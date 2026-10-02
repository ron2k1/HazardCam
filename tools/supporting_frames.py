"""get_supporting_frames: resolve cited frame indices to seekable frame references."""

from __future__ import annotations

from apps.api.schemas import FrameRef, MediaManifest


def get_supporting_frames(
    camera_id: str, frame_indices: list[int], media_manifest: MediaManifest
) -> list[FrameRef]:
    """Return the FrameRefs for ``frame_indices`` (deduplicated, in first-cited order).

    Raises ``ValueError`` for a camera/manifest mismatch or any index the manifest does
    not contain, so a caller (harness or event-day agent) gets a precise correction
    instead of silently missing evidence.
    """
    if camera_id != media_manifest.camera_id:
        raise ValueError(
            f"manifest belongs to camera {media_manifest.camera_id!r}, not {camera_id!r}"
        )
    bad = [i for i in frame_indices if not 0 <= i < len(media_manifest.frames)]
    if bad:
        raise ValueError(
            f"camera {camera_id!r} has frames 0..{len(media_manifest.frames) - 1}; "
            f"invalid indices {bad}"
        )
    return [media_manifest.frames[i] for i in dict.fromkeys(frame_indices)]
