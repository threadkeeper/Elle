import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import wisdom_tools


class Response:
    status = 200

    def read(self, _limit):
        return b'{"entries":[]}'

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class WisdomToolsTests(unittest.TestCase):
    def setUp(self):
        self.credential = MagicMock()
        self.credential.get_token.return_value = SimpleNamespace(token="workload-token")
        self.tools = wisdom_tools.make_wisdom_tools(
            credential=self.credential,
            endpoint="https://wisdom.example/bridge",
            scope="api://elle/.default",
        )

    def test_search_uses_workload_token_and_exact_payload(self):
        with patch("wisdom_tools.urllib.request.urlopen", return_value=Response()) as open_url:
            result = self.tools[0]("listen before advising", 3)

        self.assertEqual(result, {"entries": []})
        self.credential.get_token.assert_called_once_with("api://elle/.default")
        request = open_url.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://wisdom.example/bridge/elle_shared_wisdom",
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer workload-token")
        self.assertEqual(
            json.loads(request.data),
            {"query": "listen before advising", "limit": 3},
        )

    def test_contribution_uses_role_scoped_action(self):
        with patch("wisdom_tools.urllib.request.urlopen", return_value=Response()) as open_url:
            self.tools[1](
                "Listening before offering advice often reveals what support is actually useful."
            )

        request = open_url.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "https://wisdom.example/bridge/elle_contribute_wisdom",
        )
        self.assertEqual(
            json.loads(request.data),
            {
                "text": (
                    "Listening before offering advice often reveals what support "
                    "is actually useful."
                )
            },
        )


if __name__ == "__main__":
    unittest.main()