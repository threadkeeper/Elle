import argparse
import base64
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from private_tools import build_automatic_turn_arguments


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_FIXTURE = _REPO_ROOT / "app" / "demo" / "dragons-den-history.json"
_DEFAULT_RUST_BINARY = (
    _REPO_ROOT / "rust" / "target" / "debug" / ("elle.exe" if os.name == "nt" else "elle")
)
_PROTOCOL_VERSION = "2025-03-26"
_TEST_KEY = base64.b64encode(bytes(range(32))).decode("ascii")
_DATA_MARKER = ".elle-dragons-den-public-evidence-v3"
_LEGACY_DATA_MARKER = ".elle-dragons-den-public-evidence-v2"
_OLDER_DATA_MARKER = ".elle-dragons-den-" + "syn" + "thetic-demo"
_TOP_LEVEL_KEYS = {
    "schema_version",
    "research_notice",
    "elle_rewrite",
    "range",
    "public_sources",
    "users",
    "days",
    "questions",
}
_QUESTION_DATES = {
    "scarce resources": "2026-08-01",
    "locked dependencies": "2026-08-03",
    "cheap test": "2026-08-11",
    "explicit fallback": "2026-08-29",
    "broken push": "2026-09-11",
}
_ROLE_CONTRACTS = {
    "private": {
        "server_name": "elle",
        "tools": (
            "elle_context",
            "elle_list_memories",
            "elle_remember",
            "elle_correct",
            "elle_forget",
            "elle_personality",
            "elle_set_personality",
        ),
    },
    "wisdom": {
        "server_name": "elle-shared-wisdom",
        "tools": ("elle_shared_wisdom", "elle_contribute_wisdom"),
    },
}
_YOUTUBE_CHANNEL_ID = "UCMNEVbszv8ZyvSXoTn3yhpQ"
_YOUTUBE_UPLOADER_ID = "@TheBurntPeanut"
_YOUTUBE_UPLOADER = "TheBurntPeanut"
_TWITCH_OWNER_LOGIN = "TheBurntPeanut"
_TWITCH_OWNER_ID = "472066926"
_LOCAL_TIMEZONE = "America/Chicago"
_FORBIDDEN_WISDOM_TERMS = {
    "account",
    "address",
    "biometric",
    "birthday",
    "credential",
    "diagnosis",
    "disease",
    "email",
    "execute",
    "finance",
    "health",
    "identifier",
    "ignore previous",
    "instruction",
    "legal",
    "location",
    "medical",
    "medication",
    "name",
    "password",
    "phone",
    "prompt",
    "purchase",
    "relationship",
    "secret",
    "send message",
    "social security",
    "system message",
    "tool call",
    "transaction",
    "unique event",
    "user id",
    "userid",
    "username",
    "wire money",
    "you must",
    "your task",
}


class FixtureValidationError(ValueError):
    pass


class McpProtocolError(RuntimeError):
    pass


class McpToolError(RuntimeError):
    pass


def _exact_keys(value: Any, expected: set[str], path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise FixtureValidationError(f"{path} must contain exactly {sorted(expected)}")
    return value


def _nonempty_text(value: Any, path: str, maximum: int) -> str:
    if not isinstance(value, str) or value.strip() != value or not value or len(value) > maximum:
        raise FixtureValidationError(f"{path} must be nonempty trimmed text up to {maximum} characters")
    return value


def _tokens(value: str) -> set[str]:
    return {word for word in re.split(r"[^a-z0-9]+", value.lower()) if word}


def _validate_wisdom(text: Any, path: str) -> str:
    text = _nonempty_text(text, path, 360)
    if len(text) < 40 or not text.isascii():
        raise FixtureValidationError(f"{path} must be ASCII text from 40 through 360 characters")
    if any(character.isdigit() or ord(character) < 32 or ord(character) == 127 for character in text):
        raise FixtureValidationError(f"{path} contains a digit or control character")
    lowered = text.lower()
    if any(signal in text for signal in ("@", "`", '"', "'")):
        raise FixtureValidationError(f"{path} contains a disallowed identifier signal")
    if any(signal in lowered for signal in ("http://", "https://", "www.")):
        raise FixtureValidationError(f"{path} contains a link")
    if any(term in lowered for term in _FORBIDDEN_WISDOM_TERMS):
        raise FixtureValidationError(f"{path} contains a term rejected by Wisdom screening")
    for word in text.split()[1:]:
        trimmed = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", word)
        if trimmed and trimmed[0].isupper():
            raise FixtureValidationError(f"{path} contains an identifier-like capitalized word")
    return text


def _utc_from_timestamp(value: int) -> str:
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local_from_timestamp(value: int) -> datetime:
    instant = datetime.fromtimestamp(value, timezone.utc)
    year = instant.year
    march_first = date(year, 3, 1)
    first_march_sunday = march_first + timedelta(days=(6 - march_first.weekday()) % 7)
    dst_start = datetime.combine(first_march_sunday + timedelta(days=7), datetime.min.time(), timezone.utc) + timedelta(hours=8)
    november_first = date(year, 11, 1)
    first_november_sunday = november_first + timedelta(days=(6 - november_first.weekday()) % 7)
    dst_end = datetime.combine(first_november_sunday, datetime.min.time(), timezone.utc) + timedelta(hours=7)
    offset_hours = -5 if dst_start <= instant < dst_end else -6
    return instant.astimezone(timezone(timedelta(hours=offset_hours)))


def _snapshot_reference(value: Any, path: str, expected_file: str) -> dict[str, Any]:
    value = _exact_keys(value, {"file", "sha256"}, path)
    if value["file"] != expected_file:
        raise FixtureValidationError(f"{path}.file must be {expected_file}")
    if not isinstance(value["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", value["sha256"]):
        raise FixtureValidationError(f"{path}.sha256 must be lowercase SHA-256")
    return value


def validate_fixture(fixture: Any) -> dict[str, Any]:
    fixture = _exact_keys(fixture, _TOP_LEVEL_KEYS, "fixture")
    if fixture["schema_version"] != 3 or type(fixture["schema_version"]) is not int:
        raise FixtureValidationError("schema_version must be 3")
    notice = _nonempty_text(fixture["research_notice"], "research_notice", 1200).lower()
    for required in (
        "reviewed public-source evidence",
        "no transcript or media files are committed",
        "automatic captions",
        "archive-created",
        "not a proven stream start",
        "unsupported dates",
        "occurrence unknown",
    ):
        if required not in notice:
            raise FixtureValidationError(f"research_notice must include {required!r}")

    rewrite = _exact_keys(
        fixture["elle_rewrite"],
        {"status", "prompt", "acceptance_criteria", "local_runner_executes_gate"},
        "elle_rewrite",
    )
    if rewrite["status"] != "awaiting_authorized_hosted_run" or rewrite["local_runner_executes_gate"] is not False:
        raise FixtureValidationError("elle_rewrite must preserve the pending hosted-run gate")
    prompt = _nonempty_text(rewrite["prompt"], "elle_rewrite.prompt", 2200)
    for required in ("hosted Elle", "Return only", "reviewed public-source evidence", "does not load Shared Wisdom"):
        if required not in prompt:
            raise FixtureValidationError(f"elle_rewrite.prompt must include {required!r}")
    criteria = rewrite["acceptance_criteria"]
    if not isinstance(criteria, list) or len(criteria) != 4 or len(set(criteria)) != 4:
        raise FixtureValidationError("elle_rewrite.acceptance_criteria must contain four unique steps")
    for index, criterion in enumerate(criteria):
        _nonempty_text(criterion, f"elle_rewrite.acceptance_criteria[{index}]", 500)

    range_value = _exact_keys(fixture["range"], {"start", "end", "timezone"}, "range")
    if range_value["timezone"] != _LOCAL_TIMEZONE:
        raise FixtureValidationError(f"range.timezone must be {_LOCAL_TIMEZONE}")
    try:
        first_day = date.fromisoformat(range_value["start"])
        last_day = date.fromisoformat(range_value["end"])
    except (TypeError, ValueError) as error:
        raise FixtureValidationError("range start and end must be ISO calendar dates") from error
    if last_day < first_day:
        raise FixtureValidationError("range end must not precede range start")
    expected_dates = [
        (first_day + timedelta(days=offset)).isoformat()
        for offset in range((last_day - first_day).days + 1)
    ]

    public_sources = _exact_keys(fixture["public_sources"], {"twitch", "youtube"}, "public_sources")
    expected_youtube = {
        "channel_id": _YOUTUBE_CHANNEL_ID,
        "uploader_id": _YOUTUBE_UPLOADER_ID,
        "uploader": _YOUTUBE_UPLOADER,
    }
    expected_twitch = {
        "owner_id": _TWITCH_OWNER_ID,
        "owner_login": _TWITCH_OWNER_LOGIN.lower(),
        "owner_display_name": _TWITCH_OWNER_LOGIN,
    }
    if public_sources["youtube"] != expected_youtube or public_sources["twitch"] != expected_twitch:
        raise FixtureValidationError("public_sources must identify the validated YouTube and Twitch owners")

    users = _exact_keys(fixture["users"], {"demo_user_1", "demo_user_2"}, "users")
    identity_pairs = set()
    for key, user in users.items():
        user = _exact_keys(user, {"label", "tenant_id", "user_id"}, f"users.{key}")
        expected_label = "DemoUser1" if key == "demo_user_1" else "DemoUser2"
        if user["label"] != expected_label:
            raise FixtureValidationError(f"users.{key}.label must be {expected_label}")
        try:
            pair = (str(uuid.UUID(user["tenant_id"])), str(uuid.UUID(user["user_id"])))
        except (AttributeError, TypeError, ValueError) as error:
            raise FixtureValidationError(f"users.{key} must contain canonical UUID strings") from error
        if pair != (user["tenant_id"], user["user_id"]):
            raise FixtureValidationError(f"users.{key} UUID strings must be canonical")
        identity_pairs.add(pair)
    if len(identity_pairs) != 2 or users["demo_user_1"]["tenant_id"] != users["demo_user_2"]["tenant_id"]:
        raise FixtureValidationError("demo users must be distinct within one tenant")

    days = fixture["days"]
    if not isinstance(days, list) or [day.get("calendar_date") for day in days if isinstance(day, dict)] != expected_dates:
        raise FixtureValidationError("days must be contiguous, ordered, and cover the configured range")
    summaries = set()
    lessons = set()
    lesson_by_date = {}
    video_ids = set()
    twitch_ids = set()
    source_intervals = []
    for index, day in enumerate(days):
        path = f"days[{index}]"
        if not isinstance(day, dict):
            raise FixtureValidationError(f"{path} must be an object")
        calendar_date = day["calendar_date"]
        status = day.get("status")
        if status == "caption-grounded":
            day = _exact_keys(
                day,
                {"calendar_date", "status", "date_basis", "turn_prompt", "summary", "evidence", "wisdom"},
                path,
            )
            if day["date_basis"] != "youtube-live-broadcast-start":
                raise FixtureValidationError(f"{path}.date_basis must identify the YouTube actual start")
            _nonempty_text(day["turn_prompt"], f"{path}.turn_prompt", 360)
            summary = _nonempty_text(day["summary"], f"{path}.summary", 700)
            evidence = _exact_keys(day["evidence"], {"basis", "source_parts"}, f"{path}.evidence")
            if evidence["basis"] != "official-youtube-json3-captions-and-live-metadata":
                raise FixtureValidationError(f"{path}.evidence.basis is invalid")
            parts = evidence["source_parts"]
            if not isinstance(parts, list) or not parts:
                raise FixtureValidationError(f"{path}.evidence.source_parts must not be empty")
            previous_start = None
            row_by_video = {}
            for part_index, part in enumerate(parts, start=1):
                part_path = f"{path}.evidence.source_parts[{part_index - 1}]"
                base_keys = {
                    "part", "video_id", "url", "youtube_metadata", "broadcast_started_at_utc",
                    "broadcast_started_at_local", "stream_local_date", "local_timezone", "caption",
                }
                if not isinstance(part, dict) or set(part) not in (base_keys, base_keys | {"reconnects_video_id"}):
                    raise FixtureValidationError(f"{part_path} contains invalid source fields")
                if part["part"] != part_index:
                    raise FixtureValidationError(f"{part_path}.part must be contiguous and one-based")
                video_id = _nonempty_text(part["video_id"], f"{part_path}.video_id", 11)
                if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id) or video_id in video_ids:
                    raise FixtureValidationError(f"{part_path}.video_id must be globally unique and valid")
                if part["url"] != f"https://www.youtube.com/watch?v={video_id}":
                    raise FixtureValidationError(f"{part_path}.url does not match its video ID")
                metadata = _exact_keys(
                    part["youtube_metadata"],
                    {
                        "channel_id", "uploader_id", "uploader", "live_status", "release_timestamp",
                        "timestamp", "upload_date", "title", "duration_seconds", "snapshot",
                    },
                    f"{part_path}.youtube_metadata",
                )
                if any(metadata[key] != expected_youtube[key] for key in expected_youtube) or metadata["live_status"] != "was_live":
                    raise FixtureValidationError(f"{part_path}.youtube_metadata has an invalid owner or live status")
                release_timestamp = metadata["release_timestamp"]
                publication_timestamp = metadata["timestamp"]
                if type(release_timestamp) is not int or release_timestamp <= 0:
                    raise FixtureValidationError(f"{part_path}.youtube_metadata.release_timestamp is invalid")
                if type(publication_timestamp) is not int or publication_timestamp <= 0:
                    raise FixtureValidationError(f"{part_path}.youtube_metadata.timestamp is invalid")
                if not isinstance(metadata["upload_date"], str) or not re.fullmatch(r"\d{8}", metadata["upload_date"]):
                    raise FixtureValidationError(f"{part_path}.youtube_metadata.upload_date is invalid")
                _nonempty_text(metadata["title"], f"{part_path}.youtube_metadata.title", 400)
                duration = metadata["duration_seconds"]
                if type(duration) is not int or duration <= 0:
                    raise FixtureValidationError(f"{part_path}.youtube_metadata.duration_seconds is invalid")
                _snapshot_reference(
                    metadata["snapshot"],
                    f"{part_path}.youtube_metadata.snapshot",
                    f"youtube/{video_id}.info.json",
                )
                local_start = _local_from_timestamp(release_timestamp)
                expected_local = local_start.isoformat(timespec="seconds")
                if part["broadcast_started_at_utc"] != _utc_from_timestamp(release_timestamp):
                    raise FixtureValidationError(f"{part_path}.broadcast_started_at_utc is not derived from release_timestamp")
                if part["broadcast_started_at_local"] != expected_local:
                    raise FixtureValidationError(f"{part_path}.broadcast_started_at_local is not derived from release_timestamp")
                if part["stream_local_date"] != local_start.date().isoformat() or part["stream_local_date"] != calendar_date:
                    raise FixtureValidationError(f"{part_path} crosses its grouped local start date")
                if part["local_timezone"] != _LOCAL_TIMEZONE:
                    raise FixtureValidationError(f"{part_path}.local_timezone is invalid")
                caption = _exact_keys(
                    part["caption"],
                    {"file", "language", "kind", "sha256", "bytes", "evidence_event_start_ms"},
                    f"{part_path}.caption",
                )
                if caption["file"] != f"{video_id}.en-orig.json3" or caption["language"] != "en" or caption["kind"] != "youtube-automatic-original":
                    raise FixtureValidationError(f"{part_path}.caption identity is invalid")
                if not isinstance(caption["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", caption["sha256"]):
                    raise FixtureValidationError(f"{part_path}.caption.sha256 is invalid")
                if type(caption["bytes"]) is not int or caption["bytes"] <= 0:
                    raise FixtureValidationError(f"{part_path}.caption.bytes is invalid")
                offsets = caption["evidence_event_start_ms"]
                if not isinstance(offsets, list) or not offsets or offsets != sorted(set(offsets)) or any(type(offset) is not int or offset < 0 or offset >= duration * 1000 for offset in offsets):
                    raise FixtureValidationError(f"{part_path}.caption.evidence_event_start_ms is invalid")
                if previous_start is not None and release_timestamp <= previous_start:
                    raise FixtureValidationError(f"{part_path} is not ordered by actual start")
                reconnects = part.get("reconnects_video_id")
                if reconnects is not None:
                    previous = row_by_video.get(reconnects)
                    if previous is None:
                        raise FixtureValidationError(f"{part_path}.reconnects_video_id must identify an earlier same-date source")
                    gap = release_timestamp - previous["end"]
                    if gap < 0 or gap > 30 * 60 or metadata["title"] != previous["title"]:
                        raise FixtureValidationError(f"{part_path} reconnect timing or title is unsupported")
                end_timestamp = release_timestamp + duration
                source_intervals.append((release_timestamp, end_timestamp, video_id))
                row_by_video[video_id] = {"end": end_timestamp, "title": metadata["title"]}
                previous_start = release_timestamp
                video_ids.add(video_id)
            wisdom = _exact_keys(day["wisdom"], {"text", "explicitly_reviewed"}, f"{path}.wisdom")
            if wisdom["explicitly_reviewed"] is not True:
                raise FixtureValidationError(f"{path}.wisdom must be explicitly reviewed")
            lesson = _validate_wisdom(wisdom["text"], f"{path}.wisdom.text")
            if lesson == summary or lesson in summary or summary in lesson:
                raise FixtureValidationError(f"{path}.wisdom must be standalone")
            summaries.add(summary)
            lessons.add(lesson)
            lesson_by_date[calendar_date] = lesson
        elif status == "metadata-only":
            day = _exact_keys(
                day,
                {"calendar_date", "status", "date_basis", "turn_prompt", "summary", "evidence"},
                path,
            )
            if day["date_basis"] != "twitch-archive-created-at":
                raise FixtureValidationError(f"{path}.date_basis must identify Twitch archive creation")
            evidence = _exact_keys(
                day["evidence"],
                {"basis", "vod_id", "url", "twitch_metadata", "archive_created_at_utc", "archive_created_at_local", "archive_local_date", "local_timezone"},
                f"{path}.evidence",
            )
            if evidence["basis"] != "public-twitch-vod-archive-metadata":
                raise FixtureValidationError(f"{path}.evidence.basis is invalid")
            vod_id = evidence["vod_id"]
            if not isinstance(vod_id, str) or not vod_id.isdigit() or vod_id in twitch_ids:
                raise FixtureValidationError(f"{path}.evidence.vod_id is invalid")
            if evidence["url"] != f"https://www.twitch.tv/videos/{vod_id}":
                raise FixtureValidationError(f"{path}.evidence.url does not match its VOD ID")
            metadata = _exact_keys(
                evidence["twitch_metadata"],
                {
                    "id", "created_at", "published_at", "broadcast_type", "title", "length_seconds", "owner_id",
                    "owner_login", "owner_display_name", "snapshot", "yt_dlp_timestamp",
                    "yt_dlp_upload_date", "yt_dlp_snapshot",
                },
                f"{path}.evidence.twitch_metadata",
            )
            if metadata["id"] != vod_id or metadata["broadcast_type"] != "ARCHIVE" or any(metadata[key] != expected_twitch[key] for key in expected_twitch):
                raise FixtureValidationError(f"{path}.evidence.twitch_metadata has invalid archive ownership")
            _nonempty_text(metadata["title"], f"{path}.evidence.twitch_metadata.title", 400)
            if type(metadata["length_seconds"]) is not int or metadata["length_seconds"] <= 0:
                raise FixtureValidationError(f"{path}.evidence.twitch_metadata.length_seconds is invalid")
            _snapshot_reference(metadata["snapshot"], f"{path}.evidence.twitch_metadata.snapshot", f"twitch/{vod_id}.raw.json")
            _snapshot_reference(metadata["yt_dlp_snapshot"], f"{path}.evidence.twitch_metadata.yt_dlp_snapshot", f"twitch/v{vod_id}.info.json")
            try:
                created = datetime.strptime(metadata["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                published = datetime.strptime(metadata["published_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except (TypeError, ValueError) as error:
                raise FixtureValidationError(f"{path}.evidence.twitch_metadata archive dates are invalid") from error
            created_timestamp = int(created.timestamp())
            published_timestamp = int(published.timestamp())
            if metadata["yt_dlp_timestamp"] != published_timestamp or metadata["yt_dlp_upload_date"] != published.strftime("%Y%m%d"):
                raise FixtureValidationError(f"{path}.evidence.twitch_metadata publication fields disagree")
            local_created = _local_from_timestamp(created_timestamp)
            if evidence["archive_created_at_utc"] != metadata["created_at"] or evidence["archive_created_at_local"] != local_created.isoformat(timespec="seconds"):
                raise FixtureValidationError(f"{path}.evidence archive creation derivation is invalid")
            if evidence["archive_local_date"] != local_created.date().isoformat() or evidence["archive_local_date"] != calendar_date:
                raise FixtureValidationError(f"{path}.evidence archive creation date does not match its row")
            if evidence["local_timezone"] != _LOCAL_TIMEZONE:
                raise FixtureValidationError(f"{path}.evidence.local_timezone is invalid")
            expected_summary = (
                f"Public Twitch archive metadata for VOD {vod_id} was created on {calendar_date} in {_LOCAL_TIMEZONE}; "
                "this is not proof of the exact stream start, and no content claims are made without captions."
            )
            if day["summary"] != expected_summary:
                raise FixtureValidationError(f"{path}.summary must use the archive-publication template")
            _nonempty_text(day["turn_prompt"], f"{path}.turn_prompt", 360)
            summaries.add(day["summary"])
            twitch_ids.add(vod_id)
        elif status == "unsupported-date":
            day = _exact_keys(day, {"calendar_date", "status", "date_basis", "evidence"}, path)
            if day["date_basis"] != "unsupported" or day["evidence"] != {
                "basis": "no-evidence-eligible-source-in-bounded-fixture",
                "stream_occurrence": "unknown",
            }:
                raise FixtureValidationError(f"{path} must preserve unsupported occurrence as unknown")
        else:
            raise FixtureValidationError(f"{path}.status is invalid")

    ordered_intervals = sorted(source_intervals)
    for previous, current in zip(ordered_intervals, ordered_intervals[1:]):
        if current[0] < previous[1]:
            raise FixtureValidationError(f"YouTube sources overlap: {previous[2]} and {current[2]}")
    if len(summaries) != sum(day["status"] != "unsupported-date" for day in days):
        raise FixtureValidationError("eligible summaries must be unique")
    if len(lessons) != sum(day["status"] == "caption-grounded" for day in days):
        raise FixtureValidationError("eligible Wisdom lessons must be unique")

    questions = fixture["questions"]
    if not isinstance(questions, list) or len(questions) != 5:
        raise FixtureValidationError("questions must contain exactly five mappings")
    unique_values = [set(), set(), set(), set()]
    for index, question in enumerate(questions):
        path = f"questions[{index}]"
        question = _exact_keys(question, {"id", "question", "query", "expected_lesson"}, path)
        values = [
            _nonempty_text(question["id"], f"{path}.id", 80),
            _nonempty_text(question["question"], f"{path}.question", 240),
            _nonempty_text(question["query"], f"{path}.query", 80),
            _nonempty_text(question["expected_lesson"], f"{path}.expected_lesson", 360),
        ]
        for target, value in zip(unique_values, values):
            target.add(value)
        query = question["query"]
        expected_lesson = question["expected_lesson"]
        if not re.fullmatch(r"[a-z]+ [a-z]+", query) or query not in expected_lesson.lower():
            raise FixtureValidationError(f"{path}.query must be a lowercase phrase in its lesson")
        if query in question["question"].lower() or sum(query in lesson.lower() for lesson in lessons) != 1:
            raise FixtureValidationError(f"{path}.query must uniquely retrieve without revealing its answer")
        expected_date = _QUESTION_DATES.get(query)
        if expected_date is None or lesson_by_date.get(expected_date) != expected_lesson:
            raise FixtureValidationError(f"{path} does not match its reviewed lesson")
    if any(len(values) != len(questions) for values in unique_values) or {question["query"] for question in questions} != set(_QUESTION_DATES):
        raise FixtureValidationError("question fields and approved retrieval queries must be unique")
    return fixture


def load_fixture(path: str | Path) -> dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as fixture_file:
            fixture = json.load(fixture_file)
    except (OSError, json.JSONDecodeError) as error:
        raise FixtureValidationError(f"Cannot load fixture: {error}") from error
    return validate_fixture(fixture)


def verify_local_evidence(
    fixture: dict[str, Any],
    evidence_dir: str | Path,
    caption_dir: str | Path,
) -> dict[str, int]:
    metadata_files = {}
    expected_files = {}
    for day in fixture.get("days", []):
        if day.get("status") != "caption-grounded":
            if day.get("status") == "metadata-only":
                metadata = day["evidence"]["twitch_metadata"]
                metadata_files[metadata["snapshot"]["file"]] = (metadata["snapshot"], "twitch", metadata)
                metadata_files[metadata["yt_dlp_snapshot"]["file"]] = (metadata["yt_dlp_snapshot"], "twitch-yt-dlp", metadata)
            continue
        for part in day["evidence"]["source_parts"]:
            filename = part["caption"]["file"]
            if filename in expected_files:
                raise FixtureValidationError(f"Caption file is referenced more than once: {filename}")
            expected_files[filename] = part
            snapshot = part["youtube_metadata"]["snapshot"]
            metadata_files[snapshot["file"]] = (snapshot, "youtube", part)

    evidence_directory = Path(evidence_dir)
    if not evidence_directory.is_dir():
        raise FixtureValidationError(f"Evidence directory does not exist: {evidence_directory}")
    actual_metadata = {
        path.relative_to(evidence_directory).as_posix(): path
        for path in evidence_directory.rglob("*")
        if path.is_file()
    }
    missing_metadata = sorted(set(metadata_files) - set(actual_metadata))
    if missing_metadata:
        raise FixtureValidationError(f"Missing metadata snapshots: {', '.join(missing_metadata)}")
    unreferenced_metadata = sorted(set(actual_metadata) - set(metadata_files))
    if unreferenced_metadata:
        raise FixtureValidationError(f"Unreferenced metadata snapshots: {', '.join(unreferenced_metadata)}")
    for filename, (reference, kind, source) in metadata_files.items():
        content = actual_metadata[filename].read_bytes()
        if hashlib.sha256(content).hexdigest() != reference["sha256"]:
            raise FixtureValidationError(f"Metadata SHA-256 mismatch: {filename}")
        try:
            metadata = json.loads(content)
        except json.JSONDecodeError as error:
            raise FixtureValidationError(f"Metadata snapshot is not JSON: {filename}") from error
        if kind == "youtube":
            expected = source["youtube_metadata"]
            fields = {
                "id": source["video_id"],
                "channel_id": expected["channel_id"],
                "uploader_id": expected["uploader_id"],
                "uploader": expected["uploader"],
                "live_status": expected["live_status"],
                "release_timestamp": expected["release_timestamp"],
                "timestamp": expected["timestamp"],
                "upload_date": expected["upload_date"],
                "title": expected["title"],
            }
            if any(metadata.get(key) != value for key, value in fields.items()) or int(metadata.get("duration", 0)) != expected["duration_seconds"]:
                raise FixtureValidationError(f"YouTube metadata fields changed: {filename}")
        elif kind == "twitch":
            owner = metadata.get("owner") if isinstance(metadata.get("owner"), dict) else {}
            fields = {
                "id": source["id"],
                "createdAt": source["created_at"],
                "publishedAt": source["published_at"],
                "broadcastType": source["broadcast_type"],
                "title": source["title"],
                "lengthSeconds": source["length_seconds"],
            }
            owner_fields = {
                "id": source["owner_id"],
                "login": source["owner_login"],
                "displayName": source["owner_display_name"],
            }
            if any(metadata.get(key) != value for key, value in fields.items()) or any(owner.get(key) != value for key, value in owner_fields.items()):
                raise FixtureValidationError(f"Twitch raw metadata fields changed: {filename}")
        else:
            if metadata.get("id") != f"v{source['id']}" or metadata.get("timestamp") != source["yt_dlp_timestamp"] or metadata.get("upload_date") != source["yt_dlp_upload_date"]:
                raise FixtureValidationError(f"Twitch yt-dlp metadata fields changed: {filename}")

    directory = Path(caption_dir)
    if not directory.is_dir():
        raise FixtureValidationError(f"Caption directory does not exist: {directory}")
    actual_files = {
        path.relative_to(directory).as_posix(): path
        for path in directory.rglob("*")
        if path.is_file()
    }
    missing = sorted(set(expected_files) - set(actual_files))
    if missing:
        raise FixtureValidationError(f"Missing caption files: {', '.join(missing)}")
    unreferenced = sorted(set(actual_files) - set(expected_files))
    if unreferenced:
        raise FixtureValidationError(f"Unreferenced caption files: {', '.join(unreferenced)}")

    for filename, part in expected_files.items():
        content = actual_files[filename].read_bytes()
        caption = part["caption"]
        if len(content) != caption["bytes"]:
            raise FixtureValidationError(f"Caption byte length mismatch: {filename}")
        if hashlib.sha256(content).hexdigest() != caption["sha256"]:
            raise FixtureValidationError(f"Caption SHA-256 mismatch: {filename}")
        try:
            document = json.loads(content)
        except json.JSONDecodeError as error:
            raise FixtureValidationError(f"Caption file is not JSON3: {filename}") from error
        event_text = {}
        for event in document.get("events", []):
            if not isinstance(event, dict) or type(event.get("tStartMs")) is not int:
                continue
            segments = event.get("segs")
            if not isinstance(segments, list):
                continue
            text = "".join(segment.get("utf8", "") for segment in segments if isinstance(segment, dict)).strip()
            if text:
                event_text[event["tStartMs"]] = text
        unresolved = [offset for offset in caption["evidence_event_start_ms"] if offset not in event_text]
        if unresolved:
            raise FixtureValidationError(f"Caption offsets do not resolve to nonblank events in {filename}: {unresolved}")
    return {"metadata_snapshots": len(metadata_files), "caption_files": len(expected_files)}


def extract_assistant_summary(content: Any, turn_prompt: str) -> str:
    prefix = f"User:\n{turn_prompt}\n\nElle:\n"
    if not isinstance(content, str) or not content.startswith(prefix):
        raise AssertionError("Persisted automatic-turn content does not match its production wrapper")
    return content[len(prefix):]


class JsonRpcMcpClient:
    def __init__(
        self,
        *,
        rust_binary: str | Path,
        data_dir: str | Path,
        role: str,
        tenant_id: str,
        user_id: str,
        field_encryption_key: str,
        request_timeout: float = 10.0,
    ) -> None:
        self.rust_binary = Path(rust_binary)
        self.data_dir = Path(data_dir)
        self.role = role
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.field_encryption_key = field_encryption_key
        self.request_timeout = request_timeout
        self.process: subprocess.Popen[str] | None = None
        self._stderr_file = None
        self._stdout_queue: queue.Queue[str | BaseException] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._request_id = 0

    def __enter__(self) -> "JsonRpcMcpClient":
        environment = os.environ.copy()
        environment.update(
            {
                "ELLE_LOCAL_DEV": "1",
                "ELLE_TENANT_ID": self.tenant_id,
                "ELLE_USER_ID": self.user_id,
                "ELLE_MCP_ROLE": self.role,
                "ELLE_FIELD_ENCRYPTION_KEY": self.field_encryption_key,
                "ELLE_DATA_DIR": str(self.data_dir),
            }
        )
        self._stderr_file = tempfile.TemporaryFile(mode="w+b")
        try:
            self.process = subprocess.Popen(
                [str(self.rust_binary), "stdio"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_file,
                text=True,
                encoding="utf-8",
                env=environment,
            )
            self._stdout_thread = threading.Thread(
                target=self._read_stdout,
                name="elle-dragons-den-mcp-stdout",
                daemon=True,
            )
            self._stdout_thread.start()
            initialize_result = self._request(
                "initialize",
                {
                    "protocolVersion": _PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "elle-dragons-den-rehearsal", "version": "1"},
                },
            )
            self._verify_server_contract(initialize_result, self._request("tools/list", {}))
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            return self
        except Exception:
            self.close(check_exit=False)
            raise

    def __exit__(self, exception_type, _exception, _traceback) -> None:
        self.close(check_exit=exception_type is None)

    def _stderr(self) -> str:
        if self._stderr_file is None:
            return ""
        self._stderr_file.flush()
        self._stderr_file.seek(0)
        return self._stderr_file.read().decode("utf-8", errors="replace")[-2000:].strip()

    def _read_stdout(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            self._stdout_queue.put(McpProtocolError("MCP process has no stdout"))
            return
        try:
            while True:
                response_line = process.stdout.readline(64 * 1024 + 2)
                self._stdout_queue.put(response_line)
                if not response_line:
                    return
        except (OSError, ValueError) as error:
            self._stdout_queue.put(error)

    def _send(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise McpProtocolError("MCP process is not running")
        try:
            self.process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise McpProtocolError(self._process_failure("Cannot write to MCP process")) from error

    def _process_failure(self, message: str) -> str:
        return_code = self.process.poll() if self.process is not None else None
        stderr = self._stderr()
        detail = f"; stderr: {stderr}" if stderr else ""
        return f"{message}; exit code: {return_code}{detail}"

    def _terminate_process(self) -> None:
        process = self.process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        if self.process is None or self.process.stdout is None:
            raise McpProtocolError("MCP process has no stdout")
        try:
            response_line = self._stdout_queue.get(timeout=self.request_timeout)
        except queue.Empty as error:
            self._terminate_process()
            message = self._process_failure(
                f"MCP request {method} timed out after {self.request_timeout:g} seconds"
            )
            self.close(check_exit=False)
            raise McpProtocolError(message) from error
        if isinstance(response_line, BaseException):
            raise McpProtocolError(self._process_failure("Cannot read from MCP process")) from response_line
        if not response_line:
            raise McpProtocolError(self._process_failure("MCP process closed stdout"))
        if len(response_line.encode("utf-8")) > 64 * 1024 + 1:
            raise McpProtocolError("MCP response exceeded the size limit")
        try:
            response = json.loads(response_line)
        except json.JSONDecodeError as error:
            raise McpProtocolError("MCP process returned invalid JSON") from error
        if not isinstance(response, dict) or response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
            raise McpProtocolError("MCP process returned an invalid or mismatched response")
        if "error" in response:
            raise McpProtocolError(f"MCP JSON-RPC error: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise McpProtocolError("MCP response result must be an object")
        return result

    def _tool_result(self, name: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if type(result.get("isError")) is not bool:
            raise McpProtocolError(f"MCP tool {name} did not return isError")
        content = result.get("content")
        if not isinstance(content, list) or not content:
            raise McpProtocolError(f"MCP tool {name} returned no content")
        decoded = []
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
                raise McpProtocolError(f"MCP tool {name} returned malformed text content")
            try:
                decoded.append(json.loads(item["text"]))
            except json.JSONDecodeError as error:
                raise McpProtocolError(f"MCP tool {name} returned non-JSON text content") from error
        return (decoded[0] if len(decoded) == 1 else decoded), result["isError"]

    def _verify_server_contract(
        self,
        initialize_result: dict[str, Any],
        tools_result: dict[str, Any],
    ) -> None:
        contract = _ROLE_CONTRACTS.get(self.role)
        if contract is None:
            raise McpProtocolError(f"Unknown MCP role: {self.role}")
        server_info = initialize_result.get("serverInfo")
        if (
            initialize_result.get("protocolVersion") != _PROTOCOL_VERSION
            or not isinstance(server_info, dict)
            or server_info.get("name") != contract["server_name"]
            or not isinstance(server_info.get("version"), str)
            or not server_info["version"]
            or initialize_result.get("capabilities") != {"tools": {"listChanged": False}}
        ):
            raise McpProtocolError(f"MCP {self.role} server identity or capabilities are invalid")
        tools = tools_result.get("tools")
        if not isinstance(tools, list):
            raise McpProtocolError(f"MCP {self.role} tools/list did not return an array")
        names = []
        for tool in tools:
            if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
                raise McpProtocolError(f"MCP {self.role} tools/list returned a malformed tool")
            names.append(tool["name"])
        if tuple(names) != contract["tools"]:
            raise McpProtocolError(f"MCP {self.role} tools/list inventory is invalid: {names}")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        value, is_error = self._tool_result(name, arguments)
        if is_error:
            raise McpToolError(f"MCP tool {name} failed: {value}")
        return value

    def call_tool_expect_error(self, name: str, arguments: dict[str, Any]) -> Any:
        value, is_error = self._tool_result(name, arguments)
        if not is_error or value != {"error": "Access denied"}:
            raise AssertionError(f"MCP tool {name} did not return the exact Access denied payload")
        return value

    def close(self, *, check_exit: bool) -> None:
        process = self.process
        if process is None:
            if self._stderr_file is not None:
                self._stderr_file.close()
                self._stderr_file = None
            return
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        try:
            return_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                return_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait(timeout=5)
        stderr = self._stderr()
        if process.stdout is not None:
            process.stdout.close()
        if self._stdout_thread is not None:
            self._stdout_thread.join(timeout=1)
            self._stdout_thread = None
        self.process = None
        if self._stderr_file is not None:
            self._stderr_file.close()
            self._stderr_file = None
        if check_exit and return_code != 0:
            detail = f"; stderr: {stderr}" if stderr else ""
            raise McpProtocolError(f"MCP process exited with code {return_code}{detail}")


def _entry_texts(result: Any, tool_name: str) -> set[str]:
    if not isinstance(result, dict) or not isinstance(result.get("entries"), list):
        raise AssertionError(f"{tool_name} did not return an entries array")
    texts = set()
    for entry in result["entries"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("text"), str):
            raise AssertionError(f"{tool_name} returned a malformed entry")
        texts.add(entry["text"])
    return texts


def _matching_private_records(records: Any, persistence_rows: list[dict[str, Any]]) -> int:
    if not isinstance(records, list):
        raise AssertionError("elle_list_memories did not return an array")
    content_values = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("payload"), dict):
            raise AssertionError("elle_list_memories returned a malformed record")
        content = record["payload"].get("content")
        if not isinstance(content, str):
            raise AssertionError("elle_list_memories returned a malformed record")
        content_values.append(content)
    if len(records) != len(persistence_rows):
        raise AssertionError("Private automatic-turn record count mismatch")
    expected_contents = []
    for day in persistence_rows:
        expected_arguments = build_automatic_turn_arguments(
            user_text=day["turn_prompt"],
            assistant_text=day["summary"],
            response_id=f"dragons-den-{day['calendar_date']}",
        )
        expected_contents.append(expected_arguments["payload"]["content"])
    if Counter(content_values) != Counter(expected_contents):
        raise AssertionError("Private automatic-turn record content multiset mismatch")
    matched = 0
    for day, expected_content in zip(persistence_rows, expected_contents):
        persisted_contents = [content for content in content_values if content == expected_content]
        if len(persisted_contents) != 1:
            raise AssertionError(f"Private automatic-turn record mismatch for {day['calendar_date']}")
        persisted_summary = extract_assistant_summary(persisted_contents[0], day["turn_prompt"])
        if persisted_summary != day["summary"]:
            raise AssertionError(f"Private summary bytes changed for {day['calendar_date']}")
        matched += 1
    return matched


def _wisdom_result(result: Any, tool_name: str) -> tuple[set[str], int]:
    expected_keys = {
        "source",
        "mode",
        "entries",
        "privateDerivedPublicationEnabled",
        "durableHumanContributions",
    }
    if not isinstance(result, dict) or set(result) != expected_keys:
        raise AssertionError(f"{tool_name} did not return the exact Wisdom metadata contract")
    if (
        result["source"] != "reviewed_catalog_and_explicit_human_contributions"
        or result["mode"] != "keyword"
        or result["privateDerivedPublicationEnabled"] is not False
        or type(result["durableHumanContributions"]) is not int
        or result["durableHumanContributions"] < 0
    ):
        raise AssertionError(f"{tool_name} returned invalid Wisdom metadata")
    return _entry_texts(result, tool_name), result["durableHumanContributions"]


def _run_with_clients(
    fixture: dict[str, Any],
    client_factory: Callable[[str, dict[str, str]], Any],
) -> dict[str, Any]:
    persistence_rows = [
        day
        for day in fixture["days"]
        if day["status"] != "unsupported-date"
    ]
    wisdom_rows = [
        day
        for day in fixture["days"]
        if day["status"] == "caption-grounded"
        and day.get("wisdom", {}).get("explicitly_reviewed") is True
    ]
    excluded_wisdom_rows = [day for day in fixture["days"] if day not in wisdom_rows]
    unsupported_rows = [day for day in fixture["days"] if day["status"] == "unsupported-date"]
    summaries = [day["summary"] for day in persistence_rows]
    questions = fixture["questions"]
    demo_user_1 = fixture["users"]["demo_user_1"]
    demo_user_2 = fixture["users"]["demo_user_2"]

    with client_factory("private", demo_user_1) as client:
        for day in persistence_rows:
            arguments = build_automatic_turn_arguments(
                user_text=day["turn_prompt"],
                assistant_text=day["summary"],
                response_id=f"dragons-den-{day['calendar_date']}",
            )
            client.call_tool("elle_remember", arguments)
        demo_user_1_records = client.call_tool("elle_list_memories", {})
        exact_summary_count = _matching_private_records(demo_user_1_records, persistence_rows)

    with client_factory("private", demo_user_2) as client:
        demo_user_2_records = client.call_tool("elle_list_memories", {})
        if demo_user_2_records != []:
            raise AssertionError("DemoUser2 unexpectedly has private memories")
        cross_user_hits = 0
        context_probes = 0
        for day in persistence_rows:
            private_context = client.call_tool(
                "elle_context",
                {"query": day["summary"], "limit": 20},
            )
            context_text = json.dumps(private_context, ensure_ascii=False)
            hits = sum(summary in context_text for summary in summaries)
            cross_user_hits += hits
            context_probes += 1
            if hits:
                raise AssertionError(f"DemoUser2 retrieved DemoUser1 content for {day['calendar_date']}")
        private_role_error = client.call_tool_expect_error(
            "elle_shared_wisdom",
            {"query": "visible boundary", "limit": 1},
        )

    pre_seed_exact_hits = 0
    pre_seed_queries = 0
    with client_factory("wisdom", demo_user_2) as client:
        wisdom_role_error = client.call_tool_expect_error("elle_list_memories", {})
        for day in wisdom_rows:
            before = client.call_tool(
                "elle_shared_wisdom",
                {"query": day["wisdom"]["text"], "limit": 20},
            )
            before_entries, durable_count = _wisdom_result(before, "elle_shared_wisdom")
            if durable_count != 0:
                raise AssertionError("Wisdom had durable human contributions before seeding")
            if day["wisdom"]["text"] in before_entries:
                pre_seed_exact_hits += 1
                raise AssertionError(f"Wisdom lesson existed before seeding for {day['calendar_date']}")
            pre_seed_queries += 1

    attempted_contributions = 0
    accepted_contributions = 0
    with client_factory("wisdom", demo_user_1) as client:
        for day in wisdom_rows:
            attempted_contributions += 1
            contribution = client.call_tool(
                "elle_contribute_wisdom",
                {"text": day["wisdom"]["text"]},
            )
            if (
                not isinstance(contribution, dict)
                or contribution.get("text") != day["wisdom"]["text"]
                or contribution.get("reviewed") is not True
                or contribution.get("provenance") != "human"
                or type(contribution.get("version")) is not int
                or contribution["version"] < 1
                or not isinstance(contribution.get("id"), str)
            ):
                raise AssertionError(f"Wisdom contribution mismatch for {day['calendar_date']}")
            accepted_contributions += 1

    post_seed_lesson_hits = 0
    post_seed_queries = 0
    stage_question_hits = 0
    with client_factory("wisdom", demo_user_2) as client:
        for day in wisdom_rows:
            after = client.call_tool(
                "elle_shared_wisdom",
                {"query": day["wisdom"]["text"], "limit": 20},
            )
            after_entries, durable_count = _wisdom_result(after, "elle_shared_wisdom")
            if durable_count != accepted_contributions:
                raise AssertionError("Wisdom durable contribution count does not match accepted actions")
            if day["wisdom"]["text"] not in after_entries:
                raise AssertionError(f"Seeded Wisdom lesson missing for {day['calendar_date']}")
            post_seed_lesson_hits += 1
            post_seed_queries += 1
        for question in questions:
            after = client.call_tool(
                "elle_shared_wisdom",
                {"query": question["query"], "limit": 20},
            )
            after_entries, durable_count = _wisdom_result(after, "elle_shared_wisdom")
            if durable_count != accepted_contributions or question["expected_lesson"] not in after_entries:
                raise AssertionError(f"Expected Wisdom lesson missing for question {question['id']}")
            stage_question_hits += 1

    return {
        "fixture_schema_version": fixture["schema_version"],
        "public_research": True,
        "local_only": True,
        "elle_rewrite": {
            "status": fixture["elle_rewrite"]["status"],
            "executed_by_local_runner": fixture["elle_rewrite"]["local_runner_executes_gate"],
        },
        "date_range": {
            "calendar_dates": len(fixture["days"]),
            "evidence_eligible_summary_dates": len(persistence_rows),
            "youtube_actual_start_dates": len(wisdom_rows),
            "twitch_archive_created_dates": sum(day["status"] == "metadata-only" for day in fixture["days"]),
            "unsupported_dates": len(unsupported_rows),
            "youtube_sources": sum(
                len(day["evidence"]["source_parts"]) for day in wisdom_rows
            ),
        },
        "private_memory": {
            "demo_user_1_exact_summaries": exact_summary_count,
            "demo_user_2_memories": len(demo_user_2_records),
            "cross_user_summary_hits": cross_user_hits,
            "demo_user_2_context_probes": context_probes,
        },
        "wisdom": {
            "eligible_lessons": len(wisdom_rows),
            "attempted_contributions": attempted_contributions,
            "accepted_contributions": accepted_contributions,
            "excluded_rows": len(excluded_wisdom_rows),
            "pre_seed_lesson_queries": pre_seed_queries,
            "pre_seed_exact_hits": pre_seed_exact_hits,
            "pre_seed_durable_contributions": 0,
            "post_seed_lesson_queries": post_seed_queries,
            "post_seed_lesson_hits": post_seed_lesson_hits,
            "post_seed_durable_contributions": accepted_contributions,
            "stage_questions_checked": len(questions),
            "stage_question_hits": stage_question_hits,
        },
        "role_boundaries": {
            "private_rejected_shared_wisdom": bool(private_role_error),
            "wisdom_rejected_private_list": bool(wisdom_role_error),
        },
    }


def _prepare_explicit_data_directory(path: Path) -> None:
    marker = path / _DATA_MARKER
    retired_markers = [path / name for name in (_LEGACY_DATA_MARKER, _OLDER_DATA_MARKER)]
    if any(retired_marker.is_file() for retired_marker in retired_markers) and not marker.is_file():
        raise RuntimeError("Explicit data directory carries only a retired rehearsal marker")
    if path.exists() and any(path.iterdir()) and not marker.is_file():
        raise RuntimeError("Explicit data directory is nonempty and is not owned by this rehearsal")
    path.mkdir(parents=True, exist_ok=True)
    for role_directory in ("elle", "elle-shared-wisdom"):
        target = path / role_directory
        if target.exists():
            shutil.rmtree(target)
    marker.write_text("public-evidence local rehearsal data\n", encoding="ascii")


def _preflight_rust_binary(binary: Path, fixture: dict[str, Any]) -> None:
    if not binary.is_file():
        raise FileNotFoundError(f"Rust local stdio host not found: {binary}")
    user = fixture["users"]["demo_user_1"]
    with tempfile.TemporaryDirectory(prefix="elle-dragons-den-preflight-") as temporary_directory:
        for role in _ROLE_CONTRACTS:
            with JsonRpcMcpClient(
                rust_binary=binary,
                data_dir=temporary_directory,
                role=role,
                tenant_id=user["tenant_id"],
                user_id=user["user_id"],
                field_encryption_key=_TEST_KEY,
            ):
                pass


def run_rehearsal(
    fixture: dict[str, Any],
    *,
    rust_binary: str | Path | None = None,
    data_dir: str | Path | None = None,
    evidence_dir: str | Path | None = None,
    caption_dir: str | Path | None = None,
    client_factory: Callable[[str, dict[str, str]], Any] | None = None,
) -> dict[str, Any]:
    fixture = validate_fixture(fixture)
    if evidence_dir is None or caption_dir is None:
        raise FixtureValidationError("evidence_dir and caption_dir are required")
    local_evidence = verify_local_evidence(fixture, evidence_dir, caption_dir)
    binary = Path(rust_binary or _DEFAULT_RUST_BINARY).resolve()
    if client_factory is None:
        _preflight_rust_binary(binary, fixture)

    @contextmanager
    def execute(directory: Path) -> Iterator[dict[str, Any]]:
        if client_factory is None:
            def local_factory(role: str, user: dict[str, str]) -> JsonRpcMcpClient:
                return JsonRpcMcpClient(
                    rust_binary=binary,
                    data_dir=directory,
                    role=role,
                    tenant_id=user["tenant_id"],
                    user_id=user["user_id"],
                    field_encryption_key=_TEST_KEY,
                )

            active_factory = local_factory
        else:
            active_factory = client_factory
        result = _run_with_clients(fixture, active_factory)
        result["local_evidence"] = local_evidence
        yield result

    if data_dir is not None:
        directory = Path(data_dir).resolve()
        _prepare_explicit_data_directory(directory)
        with execute(directory) as evidence:
            return evidence
    with tempfile.TemporaryDirectory(prefix="elle-dragons-den-") as temporary_directory:
        with execute(Path(temporary_directory)) as evidence:
            return evidence


def _arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the reviewed public-evidence, local-only Elle Dragon's Den rehearsal."
    )
    parser.add_argument("--fixture", type=Path, default=_DEFAULT_FIXTURE)
    parser.add_argument("--rust-binary", type=Path, default=_DEFAULT_RUST_BINARY)
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        required=True,
        help="Required directory containing the exact public metadata snapshots referenced by the fixture.",
    )
    parser.add_argument(
        "--caption-dir",
        type=Path,
        required=True,
        help="Required directory containing the exact official JSON3 caption files referenced by the fixture.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        help="Optional rehearsal-owned directory. It is reset on each run; nonempty unmarked directories are refused.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _arguments(argv)
    try:
        fixture = load_fixture(arguments.fixture)
        evidence = run_rehearsal(
            fixture,
            rust_binary=arguments.rust_binary,
            data_dir=arguments.data_dir,
            evidence_dir=arguments.evidence_dir,
            caption_dir=arguments.caption_dir,
        )
    except (FixtureValidationError, McpProtocolError, McpToolError, AssertionError, OSError, RuntimeError) as error:
        print(f"Dragon's Den rehearsal failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())