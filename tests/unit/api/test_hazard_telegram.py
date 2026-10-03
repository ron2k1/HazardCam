"""Hazard Telegram ping (apps/api/services/hazard_telegram.py). Hermetic: no network, a
fake sender records what would be sent."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

import pytest

from apps.api.services import hazard_telegram as tg
from apps.api.services.hazards import REVIEW_COMPLETE, HazardService, is_plain

FAKE_TOKEN = "123456:TEST-not-a-real-token"


def write_clip(root: Path, clip_id: str, title: str, **extra: Any) -> None:
    clip_dir = root / "clips" / clip_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    doc = {"clip_id": clip_id, "title": title, "duration_s": 15.0, **extra}
    (clip_dir / "clip.json").write_text(json.dumps(doc), encoding="utf-8")


def finding(n: int, severity: str, standards: list[str], evidence: list[str], **extra: Any):
    return {
        "finding_id": f"H{n:02d}",
        "title": f"Pallet left in aisle near press {n} (see E00{n}, hz_02)",
        "severity": severity,
        "confidence": "high",
        "status": "confirmed",
        "zone_ids": [f"Z0{n}"],
        "evidence_ids": evidence,
        "standards": standards,
        "observation": "A pallet sits in the marked aisle.",
        "recommended_actions": [
            "Move the pallet out of the aisle and into the marked bay at once, per 1910.176(a)."
        ],
        **extra,
    }


def write_run(
    root: Path, clip_id: str, run_id: str, findings: list[dict[str, Any]], *, pictures: bool
) -> Path:
    run_dir = root / "reports" / clip_id / run_id
    (run_dir / "evidence").mkdir(parents=True, exist_ok=True)
    (run_dir / "evidence_clean").mkdir(parents=True, exist_ok=True)
    evidence = [
        {"evidence_id": "E001", "kind": "zone crop", "zone_id": "Z01", "timestamp_s": 1.0},
        {"evidence_id": "E002", "kind": "full scene", "timestamp_s": 2.0},
        {"evidence_id": "E003", "kind": "full scene", "timestamp_s": 3.0},
    ]
    if pictures:
        for item in evidence:
            name = f"{item['evidence_id']}.jpg"
            (run_dir / "evidence" / name).write_bytes(b"raw" + name.encode())
            (run_dir / "evidence_clean" / name).write_bytes(b"clean" + name.encode())
    report = {
        "status": REVIEW_COMPLETE,
        "generated_at_utc": "2026-10-03T19:00:00+00:00",
        "scene_summary": "A factory floor.",
        "findings": findings,
        "evidence": evidence,
        "zones": [{"zone_id": f"Z0{n}", "bbox_normalized": [0, 0, 1, 1]} for n in range(1, 6)],
    }
    (run_dir / "hazard_report.json").write_text(json.dumps(report), encoding="utf-8")
    (root / "reports" / clip_id / "latest_run.json").write_text(
        json.dumps({"run_id": run_id}), encoding="utf-8"
    )
    return run_dir


@pytest.fixture
def root(tmp_path: Path) -> Path:
    data = tmp_path / "hazards"
    for clip_id, title in (("hz_00", "Press line camera"), ("hz_01", "Floor camera 01")):
        write_clip(data, clip_id, title)
    write_clip(data, "bs_01", "Aisle camera 1", kind="blindspot")
    write_run(
        data,
        "hz_01",
        "ab12cd34ef56ab78",
        [
            finding(1, "medium", ["1910.176(a)"], ["E001", "E003"]),
            finding(2, "high", ["1910.212(a)(3)(ii)"], ["E001", "E002"]),
        ],
        pictures=True,
    )
    write_run(
        data,
        "bs_01",
        "run1",
        [finding(n, "medium", ["1910.178(n)(4)"], ["E001"]) for n in range(1, 6)],
        pictures=False,
    )
    write_clip(data, "hz_02", "Floor camera 02")
    write_run(data, "hz_02", "empty", [], pictures=False)
    return data


@pytest.fixture
def service(root: Path) -> HazardService:
    return HazardService(root, profile="fixture")


@pytest.fixture
def settings(tmp_path: Path) -> tg.TelegramSettings:
    token = tmp_path / "secrets" / "telegram.token"
    chat = tmp_path / "secrets" / "telegram.chat"
    token.parent.mkdir()
    token.write_text(FAKE_TOKEN + "\n", encoding="utf-8")
    chat.write_text("424242\n", encoding="utf-8")
    return tg.TelegramSettings(enabled=True, token_file=token, chat_file=chat)


@pytest.fixture(autouse=True)
def _clean_state():
    tg.reset_dedupe()
    yield
    tg.reset_dedupe()


class FakeSender:
    def __init__(self, fail: int = 0, exc: Exception | None = None) -> None:
        self.calls: list[tuple[str, str, bytes | None]] = []
        self.fail, self.exc = fail, exc

    def __call__(self, chat_id: str, caption: str, photo: bytes | None) -> int:
        self.calls.append((chat_id, caption, photo))
        if len(self.calls) <= self.fail:
            raise self.exc or RuntimeError(f"https://api.telegram.org/bot{FAKE_TOKEN}/x")
        return 77


def send(service: HazardService, settings: tg.TelegramSettings, sender: FakeSender, **kw: Any):
    return tg.notify_job(
        service,
        kw.pop("clip", "hz_01"),
        kw.pop("run", "ab12cd34ef56ab78"),
        settings=settings,
        sender=sender,
        retry_delay_s=0,
        **kw,
    )


# --------------------------------------------------------------------------- gating


def test_disabled_or_missing_files_is_a_no_op(service, settings, tmp_path) -> None:
    sender = FakeSender()
    off = tg.TelegramSettings(
        enabled=False, token_file=settings.token_file, chat_file=settings.chat_file
    )
    assert send(service, off, sender)["status"] == "not_connected"
    no_token = tg.TelegramSettings(
        enabled=True, token_file=tmp_path / "nope", chat_file=settings.chat_file
    )
    assert send(service, no_token, sender)["status"] == "not_connected"
    no_chat = tg.TelegramSettings(
        enabled=True, token_file=settings.token_file, chat_file=tmp_path / "nochat"
    )
    assert send(service, no_chat, sender)["status"] == "not_connected"
    assert sender.calls == []
    assert tg.last_status()["status"] == "not_connected"


def test_chat_id_env_and_config_file(tmp_path) -> None:
    cfg = tmp_path / "telegram.yaml"
    cfg.write_text("enabled: true\nrepeat_after_s: 60\ninclude_photo: false\n", encoding="utf-8")
    s = tg.load_settings(cfg, env={tg.CHAT_ID_ENV: "-1001234", tg.TOKEN_FILE_ENV: "/x/y"})
    assert (s.enabled, s.repeat_after_s, s.include_photo) == (True, 60.0, False)
    assert tg.read_chat_id(s) == "-1001234" and s.token_file == Path("/x/y")
    assert tg.load_settings(tmp_path / "missing.yaml", env={}).enabled is False
    bad = tg.TelegramSettings(enabled=True, chat_id="not a chat; rm -rf")
    assert tg.read_chat_id(bad) is None


def test_repo_config_is_on_and_holds_no_secret() -> None:
    text = tg.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    assert tg.load_settings(env={}).enabled is True
    assert not re.search(r"\d{6,}:[A-Za-z0-9_-]{20,}", text)


def test_no_findings_sends_nothing(service, settings) -> None:
    sender = FakeSender()
    assert send(service, settings, sender, clip="hz_02", run="empty")["status"] == "skipped"
    assert sender.calls == []


# --------------------------------------------------------------------------- message


def test_message_is_plain_and_short(service, settings) -> None:
    sender = FakeSender()
    result = send(service, settings, sender)
    assert result["status"] == "sent" and result["message_id"] == 77
    chat_id, caption, _ = sender.calls[0]
    assert chat_id == "424242"
    lines = caption.splitlines()
    assert lines[0] == "⚠️ HAZARD DETECTED · CAM 2"
    # highest priority first, sign label from the hazards wording, short plain action
    assert lines[1] == "MACHINE GUARD · Zone 2 · high: Move the pallet out of the aisle"
    assert lines[2].startswith("BLOCKED AISLE · Zone 1 · medium: ")
    assert lines[-1].startswith("Floor camera 01 · ")
    for line in lines:
        assert is_plain(line), line
    for leak in ("hz_", "bs_", "E00", "H0", "1910", ".jpg", "http", "ab12cd34", FAKE_TOKEN):
        assert leak not in caption


def test_blind_spot_headline_and_more_line(service, settings) -> None:
    sender = FakeSender()
    assert send(service, settings, sender, clip="bs_01", run="run1")["status"] == "sent"
    lines = sender.calls[0][1].splitlines()
    assert lines[0] == "👁 BLIND SPOT FOUND · CAM 4"
    assert lines[1].startswith("BLIND CORNER · Zone 1 · medium: ")
    assert lines[4] == "+2 more on screen"
    assert lines[5].startswith("Aisle camera 1 · ")
    assert len(lines) == 6


def test_short_action_cuts_at_a_word_boundary() -> None:
    action = tg.short_action(
        ["Install a convex mirror at the blind corner of the racking so drivers see people."]
    )
    assert action == "Install a convex mirror"
    assert len(tg.short_action(["word " * 30])) <= len("word " * 8)
    assert tg.short_action(["See hz_02.mp4"]) == ""


def test_caption_limit(service, root) -> None:
    long = [
        finding(n, "high", [], ["E001"], recommended_actions=["Stop " + "now " * 300])
        for n in range(1, 4)
    ]
    write_clip(root, "hz_00", "Press line camera " + "very " * 300)
    write_run(root, "hz_00", "long", long, pictures=False)
    alert = tg.alert_for_run(service, "hz_00", "long")
    assert alert is not None and len(alert.caption) <= tg.CAPTION_MAX


# --------------------------------------------------------------------------- photo


def test_photo_is_the_first_findings_full_frame_clean_picture(service, root) -> None:
    alert = tg.alert_for_run(service, "hz_01", "ab12cd34ef56ab78")
    assert alert is not None and alert.photo is not None
    # H02 (high) ranks first; it cites E001 (zone crop) and E002 (full scene)
    assert alert.photo.parent.name == "evidence_clean" and alert.photo.name == "E002.jpg"


def test_photo_is_never_the_marked_overview(service, root, settings) -> None:
    """No outlines on the ping: a run with only a crop and the zone overview sends text only."""
    alert = tg.alert_for_run(service, "bs_01", "run1")
    assert alert is not None and alert.photo is None  # E001 is a crop
    (root / "reports" / "bs_01" / "run1" / tg.OVERVIEW_IMAGE).write_bytes(b"overview")
    alert = tg.alert_for_run(service, "bs_01", "run1")
    assert alert is not None and alert.photo is None
    sender = FakeSender()
    send(service, settings, sender, clip="bs_01", run="run1")
    assert sender.calls[0][2] is None  # sendMessage path
    assert tg.alert_for_run(service, "bs_01", "run1", include_photo=False).photo is None


# --------------------------------------------------------------------------- dedupe / failure


def test_dedupe_per_clip_run_window(service, settings) -> None:
    now = [1000.0]
    sender = FakeSender()

    def go(**kw: Any) -> str:
        return send(service, settings, sender, clock=lambda: now[0], **kw)["status"]

    assert go() == "sent"
    assert go() == "skipped"
    assert go(clip="bs_01", run="run1") == "sent"  # another clip pings
    now[0] += settings.repeat_after_s + 1
    assert go() == "sent"
    assert len(sender.calls) == 3


def test_sender_exception_never_propagates_and_is_sanitised(service, settings, caplog) -> None:
    sender = FakeSender(fail=5)
    result = send(service, settings, sender)
    assert result["status"] == "failed"
    assert len(sender.calls) == 2  # one retry
    assert FAKE_TOKEN not in json.dumps(result)
    assert FAKE_TOKEN not in caplog.text and "api.telegram.org" not in caplog.text
    status = tg.last_status()
    assert status["status"] == "failed" and status["at"]
    assert FAKE_TOKEN not in json.dumps(status)


def test_retry_then_success(service, settings) -> None:
    sender = FakeSender(fail=1)
    assert send(service, settings, sender)["status"] == "sent"
    assert len(sender.calls) == 2


def test_client_error_retries_once_as_text_only(service, settings) -> None:
    sender = FakeSender(fail=5, exc=tg.TelegramError("sendPhoto", "HTTPError", 400))
    result = send(service, settings, sender)
    assert result == {**result, "status": "failed", "detail": "sendPhoto: HTTPError 400"}
    assert [c[2] is None for c in sender.calls] == [False, True]  # picture, then text


def test_client_error_without_photo_is_not_retried(service, settings) -> None:
    sender = FakeSender(fail=5, exc=tg.TelegramError("sendMessage", "HTTPError", 400))
    assert send(service, settings, sender, clip="bs_01", run="run1")["status"] == "failed"
    assert len(sender.calls) == 1


def test_async_never_raises(service, settings) -> None:
    class Boom:
        @property
        def store(self):
            raise RuntimeError(FAKE_TOKEN)

        def wording(self):
            raise RuntimeError("x")

    thread = tg.notify_job_async(Boom(), "hz_01", "r", settings=settings, sender=FakeSender())
    assert isinstance(thread, threading.Thread)
    thread.join(5)
    status = tg.last_status()
    assert status["status"] == "failed" and FAKE_TOKEN not in json.dumps(status)


def test_call_api_errors_hide_the_url(monkeypatch) -> None:
    import urllib.error
    import urllib.request

    def boom(request, timeout):
        raise urllib.error.URLError(f"cannot reach {request.full_url}")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(tg.TelegramError) as info:
        tg.call_api(FAKE_TOKEN, "getMe")
    assert str(info.value) == "getMe: URLError"
    assert info.value.__cause__ is None and info.value.__suppress_context__
