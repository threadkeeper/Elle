import hashlib
import json
import unittest
from unittest.mock import patch

from azure.ai.agentserver.core import (
    FoundryAgentRequestContext,
    reset_request_context,
    set_request_context,
)

import private_tools


class Response:
    status = 200

    def read(self, _limit):
        return b'{"ok":true}'

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class PrivateToolsTests(unittest.TestCase):
    def test_private_context_accepts_explicit_user_binding(self):
        with patch("private_tools.urllib.request.urlopen", return_value=Response()) as open_url:
            result = private_tools.private_context(
                endpoint="https://example.test/bridge",
                query="fast recall",
                limit=3,
                user_id="explicit-user",
            )

        request = open_url.call_args.args[0]
        self.assertEqual(result, {"ok": True})
        self.assertEqual(
            request.get_header("X-elle-continuity-handle-sha256"),
            hashlib.sha256(b"explicit-user").hexdigest(),
        )
        self.assertEqual(json.loads(request.data), {"query": "fast recall", "limit": 3})

    def test_private_context_can_request_dynamic_data_only(self):
        with patch("private_tools.urllib.request.urlopen", return_value=Response()) as open_url:
            private_tools.private_context(
                endpoint="https://example.test/bridge",
                query="fast recall",
                user_id="explicit-user",
                dynamic_only=True,
            )

        request = open_url.call_args.args[0]
        self.assertEqual(
            json.loads(request.data),
            {"query": "fast recall", "limit": 5, "dynamic_only": True},
        )

    def test_context_forwards_current_user_binding(self):
        request = None
        with patch("private_tools.urllib.request.urlopen", return_value=Response()) as open_url:
            token = set_request_context(FoundryAgentRequestContext(user_id="demo-user"))
            try:
                result = private_tools.make_private_tools(
                    endpoint="https://example.test/bridge",
                )[0]("green dashboard", 5)
                request = open_url.call_args.args[0]
            finally:
                reset_request_context(token)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.full_url, "https://example.test/bridge/elle_context")
        self.assertNotIn("Authorization", request.headers)
        self.assertEqual(
            request.get_header("X-elle-continuity-handle-sha256"),
            hashlib.sha256(b"demo-user").hexdigest(),
        )
        self.assertEqual(
            json.loads(request.data),
            {"query": "green dashboard", "limit": 5},
        )

    def test_current_user_binding_is_resolved_on_each_call(self):
        tool = private_tools.make_private_tools()[0]
        with patch("private_tools.urllib.request.urlopen", return_value=Response()) as open_url:
            for user_id in ("demo-one", "demo-two"):
                token = set_request_context(FoundryAgentRequestContext(user_id=user_id))
                try:
                    tool("dashboard")
                    request = open_url.call_args.args[0]
                    self.assertEqual(
                        request.get_header("X-elle-continuity-handle-sha256"),
                        hashlib.sha256(user_id.encode("utf-8")).hexdigest(),
                    )
                finally:
                    reset_request_context(token)

    def test_mutation_payloads_match_direct_action_schema(self):
        captured = []

        def open_url(request, timeout):
            captured.append((request.full_url, json.loads(request.data), timeout))
            return Response()

        tools = private_tools.make_private_tools(
            endpoint="https://example.test/bridge"
        )
        with patch("private_tools.urllib.request.urlopen", side_effect=open_url):
            token = set_request_context(FoundryAgentRequestContext(user_id="demo-user"))
            try:
                tools[2]("remembered", "personal", "")
                tools[3]("m-123", 2, "corrected", "fact", "demo")
                tools[4]("m-123", 2)
            finally:
                reset_request_context(token)

        self.assertEqual([item[0] for item in captured], [
            "https://example.test/bridge/elle_remember",
            "https://example.test/bridge/elle_correct",
            "https://example.test/bridge/elle_forget",
        ])
        self.assertEqual(captured[0][1]["payload"], {
            "content": "remembered", "category": "fact", "source": "m365"
        })
        self.assertEqual(captured[1][1]["payload"]["content"], "corrected")
        self.assertEqual(captured[2][1]["expected_version"], 2)

    def test_automatic_turn_arguments_preserve_exact_text_and_are_bounded(self):
        arguments = private_tools.build_automatic_turn_arguments(
            user_text="synthetic prompt",
            assistant_text="short original summary",
            response_id="response-1",
        )
        repeated = private_tools.build_automatic_turn_arguments(
            user_text="synthetic prompt",
            assistant_text="short original summary",
            response_id="response-1",
        )

        self.assertEqual(
            arguments["payload"],
            {
                "content": (
                    "User:\nsynthetic prompt\n\nElle:\nshort original summary"
                ),
                "category": "project",
                "source": "automatic-conversation-turn",
            },
        )
        self.assertEqual(arguments["idempotency_key"], repeated["idempotency_key"])
        self.assertIsNone(arguments["expires_at"])

        bounded = private_tools.build_automatic_turn_arguments(
            user_text="hello",
            assistant_text="é" * 20_000,
            response_id=None,
        )
        self.assertLessEqual(
            len(bounded["payload"]["content"].encode("utf-8")),
            16_384,
        )
        self.assertTrue(bounded["payload"]["content"].startswith("User:\nhello"))

    def test_automatic_turn_is_bounded_and_uses_explicit_user(self):
        requests = []

        def open_url(request, timeout):
            requests.append((request, timeout))
            return Response()

        with patch("private_tools.urllib.request.urlopen", side_effect=open_url):
            for _attempt in range(2):
                private_tools.remember_conversation_turn(
                    endpoint="https://example.test/bridge",
                    user_id="background-user",
                    user_text="hello",
                    assistant_text="é" * 20_000,
                    response_id="response-1",
                )

        first_body = json.loads(requests[0][0].data)
        second_body = json.loads(requests[1][0].data)
        self.assertEqual(
            requests[0][0].get_header("X-elle-continuity-handle-sha256"),
            hashlib.sha256(b"background-user").hexdigest(),
        )
        self.assertLessEqual(
            len(first_body["payload"]["content"].encode("utf-8")),
            16_384,
        )
        self.assertEqual(first_body["payload"]["category"], "project")
        self.assertEqual(
            first_body["payload"]["source"], "automatic-conversation-turn"
        )
        self.assertEqual(
            first_body["idempotency_key"], second_body["idempotency_key"]
        )


if __name__ == "__main__":
    unittest.main()
