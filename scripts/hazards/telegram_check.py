"""Set up and test the hazard Telegram ping (apps/api/services/hazard_telegram.py).

Never prints the bot token; it is read from its 0600 file inside the code.

    # 1. press Start in the bot chat on the phone, then:
    .venv/bin/python scripts/hazards/telegram_check.py --discover-chat --wait 600
    # 2. print the message that would be sent (no network):
    .venv/bin/python scripts/hazards/telegram_check.py --preview
    # 3. send real pings built from stored runs (hz_02 and one blind-spot clip):
    .venv/bin/python scripts/hazards/telegram_check.py --test
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.services import hazard_telegram as tg
from apps.api.services.hazards import HazardService, data_dir_from_env

CHAT_TYPES = ("private", "group", "supergroup")
TEST_HAZARD_CLIP = "hz_02"
LONG_POLL_S = 50


def _chat_of(update: dict) -> dict | None:
    for key in ("message", "edited_message", "my_chat_member", "channel_post"):
        item = update.get(key)
        if isinstance(item, dict) and isinstance(item.get("chat"), dict):
            return item["chat"]
    return None


def write_private(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def discover_chat(settings: tg.TelegramSettings, wait_s: float) -> int:
    token = tg.read_token(settings)
    if not token:
        print("no token file; nothing to do")
        return 2
    deadline = time.monotonic() + max(wait_s, 1.0)
    offset = None
    print(f"waiting up to {int(wait_s)} s for someone to press Start in the bot chat ...")
    while time.monotonic() < deadline:
        poll = int(min(LONG_POLL_S, max(deadline - time.monotonic(), 1.0)))
        fields = {"timeout": poll, "allowed_updates": '["message","my_chat_member"]'}
        if offset is not None:
            fields["offset"] = offset
        try:
            updates = tg.call_api(token, "getUpdates", fields, timeout_s=poll + 10)
        except tg.TelegramError as exc:
            print(f"getUpdates failed: {exc}")
            if exc.status == 409:  # a webhook is set: getUpdates cannot work
                return 1
            time.sleep(3)
            continue
        for update in updates or []:
            offset = int(update.get("update_id", 0)) + 1
            chat = _chat_of(update)
            if not chat or chat.get("type") not in CHAT_TYPES or "id" not in chat:
                continue
            write_private(settings.chat_file, str(int(chat["id"])))
            name = chat.get("first_name") or chat.get("title") or "?"
            try:  # acknowledge the update so it is not returned again
                tg.call_api(token, "getUpdates", {"offset": offset, "timeout": 0}, timeout_s=10)
            except tg.TelegramError:
                pass
            print(f"chat found: type={chat['type']} name={name}")
            print(f"chat id saved to {settings.chat_file} (0600)")
            return 0
    print("no chat appeared within the wait")
    return 1


def test_clips(service: HazardService) -> list[str]:
    clips = [TEST_HAZARD_CLIP]
    for clip in service.clips():
        if clip.get("kind") == "blindspot":
            alert = tg.alert_for_run(service, clip["clip_id"], None)
            if alert is not None and alert.findings:
                clips.append(clip["clip_id"])
                break
    return clips


def preview(service: HazardService) -> int:
    for clip_id in test_clips(service):
        alert = tg.alert_for_run(service, clip_id, None)
        if alert is None:
            print(f"[{clip_id}] no completed run")
            continue
        photo = alert.photo.name if alert.photo else "none (text only)"
        print(f"[{clip_id}] findings={alert.findings} photo={photo} chars={len(alert.caption)}")
        print(alert.caption)
        print("---")
    return 0


def send_test(service: HazardService, settings: tg.TelegramSettings) -> int:
    if not tg.connected(settings):
        print(f"not connected: {tg.last_status(settings)['status']}")
        return 2
    failures = 0
    for clip_id in test_clips(service):
        result = tg.notify_job(service, clip_id, None, settings=settings, dedupe=False)
        if result.get("status") == "sent":
            print(f"[{clip_id}] ok message_id={result.get('message_id')} photo={result['photo']}")
        else:
            failures += 1
            print(
                f"[{clip_id}] {result.get('status')}: {result.get('detail') or result.get('reason', '')}"
            )
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--discover-chat", action="store_true")
    group.add_argument("--preview", action="store_true")
    group.add_argument("--test", action="store_true")
    parser.add_argument("--wait", type=float, default=600.0)
    args = parser.parse_args(argv)
    settings = tg.load_settings()
    if args.discover_chat:
        return discover_chat(settings, args.wait)
    service = HazardService(data_dir_from_env(), profile="fixture")
    if args.preview:
        return preview(service)
    return send_test(service, settings)


if __name__ == "__main__":
    raise SystemExit(main())
