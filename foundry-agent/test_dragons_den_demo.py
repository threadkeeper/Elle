import copy
import hashlib
import json
import subprocess
import tempfile
import threading
import unittest
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import dragons_den_demo
import private_tools


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "app" / "demo" / "dragons-den-history.json"


class RecordingInput:
    def __init__(self):
        self.closed = False
        self.writes = []

    def write(self, value):
        self.writes.append(value)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class SilentOutput:
    def __init__(self):
        self.closed = False
        self._closed = threading.Event()

    def readline(self, _limit):
        self._closed.wait()
        return ""

    def close(self):
        self.closed = True
        self._closed.set()


class SilentProcess:
    def __init__(self):
        self.stdin = RecordingInput()
        self.stdout = SilentOutput()
        self.return_code = None
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.return_code

    def terminate(self):
        self.terminated = True
        self.return_code = 143

    def kill(self):
        self.killed = True
        self.return_code = 137

    def wait(self, timeout):
        if self.return_code is None:
            raise subprocess.TimeoutExpired("silent-mcp", timeout)
        return self.return_code


class McpClientTests(unittest.TestCase):
    def test_request_timeout_terminates_silent_process_and_closes_streams(self):
        client = dragons_den_demo.JsonRpcMcpClient(
            rust_binary="unused",
            data_dir="unused",
            role="private",
            tenant_id="tenant",
            user_id="user",
            field_encryption_key="key",
            request_timeout=0.01,
        )
        process = SilentProcess()
        client.process = process
        client._stdout_thread = threading.Thread(target=client._read_stdout, daemon=True)
        client._stdout_thread.start()

        with self.assertRaisesRegex(dragons_den_demo.McpProtocolError, "timed out"):
            client._request("silent", {})

        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)
        self.assertIsNone(client.process)


class PublicEvidenceFakeState:
    def __init__(self):
        self.memories = defaultdict(dict)
        self.wisdom = set()
        self.calls = []

    def factory(self, role, user):
        return PublicEvidenceFakeClient(self, role, user)


class PublicEvidenceFakeClient:
    def __init__(self, state, role, user):
        self.state = state
        self.role = role
        self.user = user

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def call_tool(self, name, arguments):
        self.state.calls.append((self.role, self.user["label"], name, copy.deepcopy(arguments)))
        if self.role == "private" and name == "elle_remember":
            records = self.state.memories[self.user["user_id"]]
            key = arguments["idempotency_key"]
            records.setdefault(key, {"id": key, "payload": copy.deepcopy(arguments["payload"])})
            return copy.deepcopy(records[key])
        if self.role == "private" and name == "elle_list_memories":
            return copy.deepcopy(list(self.state.memories[self.user["user_id"]].values()))
        if self.role == "private" and name == "elle_context":
            return {"recall": {"memories": copy.deepcopy(list(self.state.memories[self.user["user_id"]].values()))}}
        if self.role == "wisdom" and name == "elle_contribute_wisdom":
            text = arguments["text"]
            self.state.wisdom.add(text)
            return {
                "id": f"human-{hashlib.sha256(text.encode('utf-8')).hexdigest()}",
                "text": text,
                "provenance": "human",
                "version": 1,
                "reviewed": True,
            }
        if self.role == "wisdom" and name == "elle_shared_wisdom":
            query_tokens = dragons_den_demo._tokens(arguments["query"])
            matches = sorted(
                self.state.wisdom,
                key=lambda lesson: (-len(query_tokens & dragons_den_demo._tokens(lesson)), lesson),
            )
            return {
                "source": "reviewed_catalog_and_explicit_human_contributions",
                "mode": "keyword",
                "entries": [
                    {"text": lesson}
                    for lesson in matches
                    if query_tokens & dragons_den_demo._tokens(lesson)
                ][: arguments["limit"]],
                "privateDerivedPublicationEnabled": False,
                "durableHumanContributions": len(self.state.wisdom),
            }
        raise AssertionError(f"Unexpected fake tool call: {self.role} {name}")

    def call_tool_expect_error(self, name, arguments):
        self.state.calls.append((self.role, self.user["label"], name, copy.deepcopy(arguments)))
        if (self.role, name) in {("private", "elle_shared_wisdom"), ("wisdom", "elle_list_memories")}:
            return {"error": "Access denied"}
        raise AssertionError(f"Expected-error fake received an allowed tool: {self.role} {name}")


class SchemaV3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = dragons_den_demo.load_fixture(FIXTURE_PATH)

    def test_calendar_counts_and_eligibility_derive_from_rows(self):
        expected_dates = [
            (date(2026, 8, 1) + timedelta(days=offset)).isoformat()
            for offset in range(48)
        ]
        self.assertEqual(self.fixture["schema_version"], 3)
        self.assertEqual(self.fixture["range"], {
            "start": "2026-08-01",
            "end": "2026-09-17",
            "timezone": "America/Chicago",
        })
        self.assertEqual([day["calendar_date"] for day in self.fixture["days"]], expected_dates)
        self.assertEqual(
            Counter(day["status"] for day in self.fixture["days"]),
            Counter({"caption-grounded": 39, "metadata-only": 2, "unsupported-date": 7}),
        )
        self.assertNotIn("verified_stream_dates", self.fixture["range"])

    def test_release_timestamp_controls_actual_start_and_local_date(self):
        parts = [
            part
            for day in self.fixture["days"]
            if day["status"] == "caption-grounded"
            for part in day["evidence"]["source_parts"]
        ]
        self.assertEqual(len(parts), 42)
        self.assertTrue(any(part["youtube_metadata"]["release_timestamp"] != part["youtube_metadata"]["timestamp"] for part in parts))
        for part in parts:
            metadata = part["youtube_metadata"]
            self.assertEqual(part["broadcast_started_at_utc"], dragons_den_demo._utc_from_timestamp(metadata["release_timestamp"]))
            self.assertEqual(part["broadcast_started_at_local"], dragons_den_demo._local_from_timestamp(metadata["release_timestamp"]).isoformat(timespec="seconds"))
            self.assertEqual(part["stream_local_date"], part["broadcast_started_at_local"][:10])

        invalid = copy.deepcopy(self.fixture)
        part = invalid["days"][0]["evidence"]["source_parts"][0]
        part["broadcast_started_at_utc"] = dragons_den_demo._utc_from_timestamp(part["youtube_metadata"]["timestamp"])
        with self.assertRaisesRegex(dragons_den_demo.FixtureValidationError, "release_timestamp"):
            dragons_den_demo.validate_fixture(invalid)

    def test_sources_do_not_overlap_and_only_supported_reconnect_is_declared(self):
        intervals = []
        grouped = {}
        reconnects = []
        for day in self.fixture["days"]:
            if day["status"] != "caption-grounded":
                continue
            grouped[day["calendar_date"]] = [part["video_id"] for part in day["evidence"]["source_parts"]]
            for part in day["evidence"]["source_parts"]:
                start = part["youtube_metadata"]["release_timestamp"]
                intervals.append((start, start + part["youtube_metadata"]["duration_seconds"]))
                self.assertEqual(part["stream_local_date"], day["calendar_date"])
                if "reconnects_video_id" in part:
                    reconnects.append((part["video_id"], part["reconnects_video_id"]))
        intervals.sort()
        self.assertTrue(all(current[0] >= previous[1] for previous, current in zip(intervals, intervals[1:])))
        self.assertEqual(grouped["2026-08-04"], ["IX8mDR9i658", "rUZDk2X6eUo"])
        self.assertEqual(grouped["2026-08-11"], ["oi3Tml3BlLg", "O58xTnKJFjM", "hpSIP7Dey5c"])
        self.assertEqual(reconnects, [("O58xTnKJFjM", "oi3Tml3BlLg")])

    def test_each_youtube_source_binds_owner_live_snapshot_and_caption(self):
        seen = set()
        for day in self.fixture["days"]:
            if day["status"] != "caption-grounded":
                continue
            for part in day["evidence"]["source_parts"]:
                metadata = part["youtube_metadata"]
                caption = part["caption"]
                self.assertEqual(metadata["channel_id"], "UCMNEVbszv8ZyvSXoTn3yhpQ")
                self.assertEqual(metadata["uploader_id"], "@TheBurntPeanut")
                self.assertEqual(metadata["uploader"], "TheBurntPeanut")
                self.assertEqual(metadata["live_status"], "was_live")
                self.assertRegex(metadata["snapshot"]["sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual(caption["language"], "en")
                self.assertEqual(caption["kind"], "youtube-automatic-original")
                self.assertTrue(caption["evidence_event_start_ms"])
                seen.add(part["video_id"])
        self.assertEqual(len(seen), 42)
        self.assertTrue(FIXTURE_PATH.read_bytes().isascii())

    def test_twitch_is_archive_published_and_unsupported_dates_remain_unknown(self):
        twitch_rows = [day for day in self.fixture["days"] if day["status"] == "metadata-only"]
        self.assertEqual([day["calendar_date"] for day in twitch_rows], ["2026-08-06", "2026-09-01"])
        for day in twitch_rows:
            metadata = day["evidence"]["twitch_metadata"]
            self.assertEqual(day["date_basis"], "twitch-archive-created-at")
            self.assertEqual(metadata["broadcast_type"], "ARCHIVE")
            self.assertEqual(metadata["owner_id"], "472066926")
            self.assertIn("not proof of the exact stream start", day["summary"])
            self.assertNotIn("started_at", json.dumps(day))
            self.assertNotIn("wisdom", day)
        unsupported = [day for day in self.fixture["days"] if day["status"] == "unsupported-date"]
        self.assertEqual(len(unsupported), 7)
        self.assertTrue(all(day["evidence"]["stream_occurrence"] == "unknown" for day in unsupported))
        self.assertTrue(all("summary" not in day and "wisdom" not in day for day in unsupported))

    def test_eligible_wisdom_builder_identity_and_pending_rewrite(self):
        eligible = [day for day in self.fixture["days"] if day["status"] != "unsupported-date"]
        wisdom_rows = [day for day in self.fixture["days"] if day["status"] == "caption-grounded"]
        self.assertEqual(len(eligible), 41)
        self.assertEqual(len(wisdom_rows), 39)
        self.assertTrue(all(day["wisdom"]["explicitly_reviewed"] is True for day in wisdom_rows))
        self.assertIs(dragons_den_demo.build_automatic_turn_arguments, private_tools.build_automatic_turn_arguments)
        for day in eligible:
            arguments = dragons_den_demo.build_automatic_turn_arguments(
                user_text=day["turn_prompt"],
                assistant_text=day["summary"],
                response_id=f"dragons-den-{day['calendar_date']}",
            )
            self.assertEqual(
                dragons_den_demo.extract_assistant_summary(arguments["payload"]["content"], day["turn_prompt"]).encode("utf-8"),
                day["summary"].encode("utf-8"),
            )
        self.assertEqual(len(self.fixture["questions"]), 5)
        self.assertEqual(self.fixture["elle_rewrite"]["status"], "awaiting_authorized_hosted_run")
        self.assertFalse(self.fixture["elle_rewrite"]["local_runner_executes_gate"])

    def test_private_records_require_the_exact_expected_multiset(self):
        eligible = [day for day in self.fixture["days"] if day["status"] != "unsupported-date"]
        records = [
            {
                "payload": dragons_den_demo.build_automatic_turn_arguments(
                    user_text=day["turn_prompt"],
                    assistant_text=day["summary"],
                    response_id=f"dragons-den-{day['calendar_date']}",
                )["payload"]
            }
            for day in eligible
        ]
        cases = {
            "extra unrelated": records + [{"payload": {"content": "unrelated"}}],
            "extra duplicate": records + [copy.deepcopy(records[0])],
            "missing": records[:-1],
            "duplicate replacing missing": records[:-1] + [copy.deepcopy(records[0])],
        }
        for name, returned_records in cases.items():
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, "record (count|content multiset) mismatch"):
                dragons_den_demo._matching_private_records(returned_records, eligible)

    def test_validator_rejects_wrong_channel_and_ineligible_wisdom(self):
        invalid = copy.deepcopy(self.fixture)
        invalid["days"][0]["evidence"]["source_parts"][0]["youtube_metadata"]["channel_id"] = "wrong"
        with self.assertRaises(dragons_den_demo.FixtureValidationError):
            dragons_den_demo.validate_fixture(invalid)
        invalid = copy.deepcopy(self.fixture)
        row = next(day for day in invalid["days"] if day["status"] == "metadata-only")
        row["wisdom"] = copy.deepcopy(invalid["days"][0]["wisdom"])
        with self.assertRaises(dragons_den_demo.FixtureValidationError):
            dragons_den_demo.validate_fixture(invalid)


class EvidenceV3Tests(unittest.TestCase):
    @staticmethod
    def _tiny_evidence(root):
        evidence_dir = root / "evidence"
        caption_dir = root / "captions"
        (evidence_dir / "youtube").mkdir(parents=True)
        (evidence_dir / "twitch").mkdir()
        caption_dir.mkdir()
        youtube = {
            "id": "abcdefghijk", "channel_id": "channel", "uploader_id": "@owner",
            "uploader": "Owner", "live_status": "was_live", "release_timestamp": 100,
            "timestamp": 200, "upload_date": "19700101", "title": "Title", "duration": 10,
        }
        youtube_path = evidence_dir / "youtube" / "abcdefghijk.info.json"
        youtube_path.write_text(json.dumps(youtube), encoding="utf-8")
        raw = {
            "id": "123", "createdAt": "1970-01-01T00:05:00Z", "publishedAt": "1970-01-01T00:05:00Z", "broadcastType": "ARCHIVE",
            "title": "Archive", "lengthSeconds": 10,
            "owner": {"id": "9", "login": "owner", "displayName": "Owner"},
        }
        raw_path = evidence_dir / "twitch" / "123.raw.json"
        raw_path.write_text(json.dumps(raw), encoding="utf-8")
        info_path = evidence_dir / "twitch" / "v123.info.json"
        info_path.write_text(json.dumps({"id": "v123", "timestamp": 300, "upload_date": "19700101"}), encoding="utf-8")
        caption_path = caption_dir / "abcdefghijk.en-orig.json3"
        caption_path.write_text(json.dumps({"events": [{"tStartMs": 1234, "segs": [{"utf8": " reviewed text "}]}]}), encoding="utf-8")
        fixture = {"days": [
            {"status": "caption-grounded", "evidence": {"source_parts": [{
                "video_id": "abcdefghijk",
                "youtube_metadata": {
                    **{key: youtube[key] for key in ("channel_id", "uploader_id", "uploader", "live_status", "release_timestamp", "timestamp", "upload_date", "title")},
                    "duration_seconds": 10,
                    "snapshot": {"file": "youtube/abcdefghijk.info.json", "sha256": hashlib.sha256(youtube_path.read_bytes()).hexdigest()},
                },
                "caption": {
                    "file": caption_path.name, "bytes": caption_path.stat().st_size,
                    "sha256": hashlib.sha256(caption_path.read_bytes()).hexdigest(),
                    "evidence_event_start_ms": [1234],
                },
            }]}},
            {"status": "metadata-only", "evidence": {"twitch_metadata": {
                "id": "123", "created_at": raw["createdAt"], "published_at": raw["publishedAt"], "broadcast_type": raw["broadcastType"],
                "title": raw["title"], "length_seconds": raw["lengthSeconds"],
                "owner_id": "9", "owner_login": "owner", "owner_display_name": "Owner",
                "snapshot": {"file": "twitch/123.raw.json", "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest()},
                "yt_dlp_timestamp": 300, "yt_dlp_upload_date": "19700101",
                "yt_dlp_snapshot": {"file": "twitch/v123.info.json", "sha256": hashlib.sha256(info_path.read_bytes()).hexdigest()},
            }}},
        ]}
        return fixture, evidence_dir, caption_dir

    def test_hash_bound_metadata_and_nonblank_json3_offsets(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            fixture, evidence_dir, caption_dir = self._tiny_evidence(Path(temporary_directory))
            self.assertEqual(dragons_den_demo.verify_local_evidence(fixture, evidence_dir, caption_dir), {"metadata_snapshots": 3, "caption_files": 1})

    def test_changed_unreferenced_and_unresolved_evidence_is_rejected(self):
        for case in (
            "metadata", "caption", "unreferenced", "offset",
            "differently-named-metadata", "nested-metadata",
            "differently-named-caption", "nested-caption",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary_directory:
                fixture, evidence_dir, caption_dir = self._tiny_evidence(Path(temporary_directory))
                if case == "metadata":
                    (evidence_dir / "youtube" / "abcdefghijk.info.json").write_text("{}", encoding="utf-8")
                elif case == "caption":
                    (caption_dir / "abcdefghijk.en-orig.json3").write_text("{}", encoding="utf-8")
                elif case == "unreferenced":
                    (evidence_dir / "youtube" / "extra.info.json").write_text("{}", encoding="utf-8")
                elif case == "offset":
                    fixture["days"][0]["evidence"]["source_parts"][0]["caption"]["evidence_event_start_ms"] = [999]
                elif case == "differently-named-metadata":
                    (evidence_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")
                elif case == "nested-metadata":
                    nested = evidence_dir / "youtube" / "nested"
                    nested.mkdir()
                    (nested / "unexpected.bin").write_bytes(b"unexpected")
                elif case == "differently-named-caption":
                    (caption_dir / "unexpected.txt").write_text("unexpected", encoding="utf-8")
                else:
                    nested = caption_dir / "nested"
                    nested.mkdir()
                    (nested / "unexpected.bin").write_bytes(b"unexpected")
                with self.assertRaises(dragons_den_demo.FixtureValidationError):
                    dragons_den_demo.verify_local_evidence(fixture, evidence_dir, caption_dir)


class RehearsalV3Tests(unittest.TestCase):
    def test_runtime_proof_is_exhaustive_and_counts_observed_actions(self):
        fixture = dragons_den_demo.load_fixture(FIXTURE_PATH)
        state = PublicEvidenceFakeState()
        result = dragons_den_demo._run_with_clients(fixture, state.factory)
        self.assertEqual(result["date_range"], {
            "calendar_dates": 48,
            "evidence_eligible_summary_dates": 41,
            "youtube_actual_start_dates": 39,
            "twitch_archive_created_dates": 2,
            "unsupported_dates": 7,
            "youtube_sources": 42,
        })
        self.assertEqual(result["private_memory"], {
            "demo_user_1_exact_summaries": 41,
            "demo_user_2_memories": 0,
            "cross_user_summary_hits": 0,
            "demo_user_2_context_probes": 41,
        })
        self.assertEqual(result["wisdom"], {
            "eligible_lessons": 39,
            "attempted_contributions": 39,
            "accepted_contributions": 39,
            "excluded_rows": 9,
            "pre_seed_lesson_queries": 39,
            "pre_seed_exact_hits": 0,
            "pre_seed_durable_contributions": 0,
            "post_seed_lesson_queries": 39,
            "post_seed_lesson_hits": 39,
            "post_seed_durable_contributions": 39,
            "stage_questions_checked": 5,
            "stage_question_hits": 5,
        })
        self.assertTrue(all(result["role_boundaries"].values()))
        self.assertEqual(sum(call[2] == "elle_remember" for call in state.calls), 41)
        self.assertEqual(sum(call[2] == "elle_context" for call in state.calls), 41)
        self.assertEqual(sum(call[2] == "elle_contribute_wisdom" for call in state.calls), 39)

    def test_preexisting_durable_wisdom_is_rejected(self):
        fixture = dragons_den_demo.load_fixture(FIXTURE_PATH)
        state = PublicEvidenceFakeState()
        state.wisdom.add("A durable public lesson already exists before this local rehearsal begins.")
        with self.assertRaisesRegex(AssertionError, "before seeding"):
            dragons_den_demo._run_with_clients(fixture, state.factory)

    def test_evidence_is_mandatory_and_failure_precedes_writes(self):
        fixture = dragons_den_demo.load_fixture(FIXTURE_PATH)
        state = PublicEvidenceFakeState()
        with self.assertRaisesRegex(dragons_den_demo.FixtureValidationError, "required"):
            dragons_den_demo.run_rehearsal(fixture, client_factory=state.factory)
        with tempfile.TemporaryDirectory() as temporary_directory:
            empty = Path(temporary_directory)
            with self.assertRaisesRegex(dragons_den_demo.FixtureValidationError, "Missing metadata"):
                dragons_den_demo.run_rehearsal(fixture, evidence_dir=empty, caption_dir=empty, client_factory=state.factory)
        self.assertEqual(state.calls, [])

    def test_binary_preflight_precedes_owned_directory_reset(self):
        fixture = dragons_den_demo.load_fixture(FIXTURE_PATH)
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_path = Path(temporary_directory) / "data"
            role_path = data_path / "elle"
            role_path.mkdir(parents=True)
            old_file = role_path / "old.json"
            old_file.write_text("{}", encoding="ascii")
            (data_path / dragons_den_demo._DATA_MARKER).write_text("owned", encoding="ascii")
            with mock.patch.object(dragons_den_demo, "verify_local_evidence", return_value={"metadata_snapshots": 1, "caption_files": 1}):
                with self.assertRaises(FileNotFoundError):
                    dragons_den_demo.run_rehearsal(
                        fixture,
                        rust_binary=data_path / "missing.exe",
                        data_dir=data_path,
                        evidence_dir="evidence",
                        caption_dir="captions",
                    )
            self.assertTrue(old_file.is_file())

    def test_v2_marker_is_refused_and_v3_owned_roles_reset(self):
        for marker in (dragons_den_demo._LEGACY_DATA_MARKER, dragons_den_demo._OLDER_DATA_MARKER):
            with self.subTest(marker=marker), tempfile.TemporaryDirectory() as temporary_directory:
                path = Path(temporary_directory)
                (path / marker).write_text("retired", encoding="ascii")
                with self.assertRaisesRegex(RuntimeError, "retired rehearsal marker"):
                    dragons_den_demo._prepare_explicit_data_directory(path)
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory)
            (path / dragons_den_demo._DATA_MARKER).write_text("owned", encoding="ascii")
            role = path / "elle"
            role.mkdir()
            (role / "old.json").write_text("{}", encoding="ascii")
            dragons_den_demo._prepare_explicit_data_directory(path)
            self.assertFalse(role.exists())


class McpContractV3Tests(unittest.TestCase):
    @staticmethod
    def _initialize(name):
        return {
            "protocolVersion": dragons_den_demo._PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": name, "version": "0.1.0"},
        }

    def test_exact_role_identities_tool_catalogs_and_denial_payload(self):
        for role, contract in dragons_den_demo._ROLE_CONTRACTS.items():
            client = dragons_den_demo.JsonRpcMcpClient(
                rust_binary="unused", data_dir="unused", role=role,
                tenant_id="tenant", user_id="user", field_encryption_key="key",
            )
            tools = {"tools": [{"name": name} for name in contract["tools"]]}
            client._verify_server_contract(self._initialize(contract["server_name"]), tools)
            with self.assertRaises(dragons_den_demo.McpProtocolError):
                client._verify_server_contract(self._initialize("wrong"), tools)
            with self.assertRaises(dragons_den_demo.McpProtocolError):
                client._verify_server_contract(self._initialize(contract["server_name"]), {"tools": list(reversed(tools["tools"]))})
        client = dragons_den_demo.JsonRpcMcpClient(
            rust_binary="unused", data_dir="unused", role="private",
            tenant_id="tenant", user_id="user", field_encryption_key="key",
        )
        with mock.patch.object(client, "_tool_result", return_value=({"error": "Access denied"}, True)):
            self.assertEqual(client.call_tool_expect_error("blocked", {}), {"error": "Access denied"})
        for result in (({"error": "Unauthorized"}, True), ({"error": "Access denied"}, False)):
            with mock.patch.object(client, "_tool_result", return_value=result):
                with self.assertRaises(AssertionError):
                    client.call_tool_expect_error("blocked", {})


if __name__ == "__main__":
    unittest.main()