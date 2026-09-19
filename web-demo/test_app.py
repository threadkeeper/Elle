import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock


os.environ["AZURE_TOKEN_CREDENTIALS"] = "dev"
sys.path.insert(0, os.path.dirname(__file__))
web = importlib.import_module("app")


class WebDemoTests(unittest.TestCase):
    def setUp(self):
        web.sessions.clear()
        web.project = MagicMock()
        web.project.agents.create_session.return_value.agent_session_id = "session-1"
        response = MagicMock()
        response.output_text = "Hello from Elle"
        client = web.project.get_openai_client.return_value.__enter__.return_value
        client.responses.create.return_value = response
        self.client = web.app.test_client()

    def test_chat_reuses_session_for_authenticated_user(self):
        headers = {"X-MS-CLIENT-PRINCIPAL-ID": "user-1"}

        first = self.client.post("/api/chat", json={"message": "Hello"}, headers=headers)
        second = self.client.post("/api/chat", json={"message": "Again"}, headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()["message"], "Hello from Elle")
        self.assertFalse(first.get_json()["sessionReused"])
        self.assertTrue(second.get_json()["sessionReused"])
        version = web.project.agents.create_session.call_args.kwargs[
            "version_indicator"
        ]
        self.assertEqual(version.agent_version, "22")

    def test_chat_rejects_empty_message(self):
        response = self.client.post("/api/chat", json={"message": "  "})

        self.assertEqual(response.status_code, 400)
        web.project.get_openai_client.assert_not_called()

    def test_identity_uses_easy_auth_headers(self):
        response = self.client.get(
            "/api/me",
            headers={
                "X-MS-CLIENT-PRINCIPAL-ID": "user-1",
                "X-MS-CLIENT-PRINCIPAL-NAME": "Ada Lovelace",
            },
        )

        self.assertEqual(
            response.get_json(),
            {"authenticated": True, "name": "Ada Lovelace"},
        )


if __name__ == "__main__":
    unittest.main()