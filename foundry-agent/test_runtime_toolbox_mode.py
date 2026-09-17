import os
import unittest
from unittest.mock import patch

from agent_framework import Agent

import main as runtime
from request_scoped_tools import RequestScopedToolboxAgent


class ToolboxLifetimeTests(unittest.TestCase):
    def build_agent(self):
        return runtime.build_agent(
            client=object(),
            credential=object(),
            toolbox_url="https://example.test/mcp",
            name="elle",
            instructions="Test instructions",
        )

    def test_default_is_request_scoped(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            runtime, "FoundryToolbox"
        ) as toolbox_type:
            agent = self.build_agent()

        self.assertIs(type(agent), RequestScopedToolboxAgent)
        toolbox_type.assert_not_called()

    def test_explicit_request_scoped_is_request_scoped(self):
        with patch.dict(
            os.environ, {"ELLE_TOOLBOX_LIFETIME": "request_scoped"}, clear=True
        ):
            agent = self.build_agent()

        self.assertIs(type(agent), RequestScopedToolboxAgent)

    def test_long_lived_returns_plain_agent_with_exact_toolbox(self):
        with patch.dict(
            os.environ, {"ELLE_TOOLBOX_LIFETIME": "long_lived"}, clear=True
        ):
            agent = self.build_agent()

        self.assertIs(type(agent), Agent)
        self.assertEqual(len(agent.mcp_tools), 1)
        self.assertIsInstance(agent.mcp_tools[0], runtime.FoundryToolbox)

    def test_unknown_lifetime_is_rejected(self):
        with patch.dict(
            os.environ, {"ELLE_TOOLBOX_LIFETIME": "sometimes"}, clear=True
        ), self.assertRaisesRegex(
            ValueError, "Unsupported ELLE_TOOLBOX_LIFETIME: sometimes"
        ):
            self.build_agent()


if __name__ == "__main__":
    unittest.main()