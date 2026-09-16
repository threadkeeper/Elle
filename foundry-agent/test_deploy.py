import io
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import deploy
from azure.ai.projects.models import (
    ActivityProtocolConfiguration,
    AgentEndpointConfig,
    BotServiceTenantAuthorizationScheme,
    EntraAuthorizationScheme,
    FixedRatioVersionSelectionRule,
    MCPToolboxTool,
    ProtocolConfiguration,
    ResponsesProtocolConfiguration,
    VersionSelector,
)


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.project = MagicMock()
        self.project.toolboxes.get.return_value.default_version = "3"
        self.baseline_tool = MCPToolboxTool(
            name="existing", server_label="existing", server_url="https://example.com/mcp"
        )
        self.project.toolboxes.get_version.return_value = SimpleNamespace(
            tools=[self.baseline_tool], skills=[], policies=None
        )
        self.project.toolboxes.create_version.return_value.version = "4"
        self.project.agents.get_version.return_value.status = "active"
        self.endpoint = AgentEndpointConfig(
            version_selector=VersionSelector(
                version_selection_rules=[
                    FixedRatioVersionSelectionRule(agent_version="3", traffic_percentage=100)
                ]
            ),
            protocol_configuration=ProtocolConfiguration(
                responses=ResponsesProtocolConfiguration(),
                activity=ActivityProtocolConfiguration(),
            ),
            authorization_schemes=[
                EntraAuthorizationScheme(),
                BotServiceTenantAuthorizationScheme(),
            ],
        )
        self.project.agents.get.return_value.agent_endpoint = self.endpoint

    def test_no_addition_reuses_current_toolbox(self):
        self.assertEqual(deploy.stage_toolbox(self.project, []), "3")
        self.project.toolboxes.create_version.assert_not_called()

    def test_addition_preserves_existing_tools_without_publishing(self):
        version = deploy.stage_toolbox(self.project, ["elle_private=elle-private-oauth"])
        self.assertEqual(version, "4")
        tools = self.project.toolboxes.create_version.call_args.kwargs["tools"]
        self.assertEqual(tools[0], self.baseline_tool)
        self.assertEqual(tools[1].project_connection_id, "elle-private-oauth")
        self.project.toolboxes.update.assert_not_called()

    def test_explicit_baseline_preserves_previous_restoration_step(self):
        deploy.stage_toolbox(self.project, ["elle_wisdom=wisdom"], "4")
        self.project.toolboxes.get_version.assert_called_once_with("elle-tools", "4")

    def test_staging_refuses_automatic_latest_routing(self):
        self.project.agents.get.return_value.agent_endpoint = None
        with self.assertRaisesRegex(RuntimeError, "Pin live traffic"):
            deploy.deploy(self.project, "4")
        self.project.agents.create_version_from_code.assert_not_called()

    def test_duplicate_tool_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "already exists"):
            deploy.stage_toolbox(self.project, ["existing=another-connection"])
        self.project.toolboxes.create_version.assert_not_called()

    def test_invalid_additions_are_rejected(self):
        for addition in ("missing-equals", "=connection", "name="):
            with self.subTest(addition=addition), self.assertRaises(ValueError):
                deploy.stage_toolbox(self.project, [addition])
        self.project.toolboxes.create_version.assert_not_called()

    def test_missing_connection_is_not_ignored(self):
        self.project.connections.get.side_effect = RuntimeError("missing connection")
        with self.assertRaisesRegex(RuntimeError, "missing connection"):
            deploy.stage_toolbox(self.project, ["elle_private=missing"])
        self.project.toolboxes.create_version.assert_not_called()

    def test_staging_does_not_switch_traffic(self):
        self.project.agents.create_version_from_code.return_value.version = "4"
        with patch.object(deploy, "wait_until_active"), patch.object(
            deploy, "package_source", return_value=(b"zip", "digest")
        ):
            self.assertEqual(deploy.deploy(self.project, "4"), "4")
        self.project.agents.update_details.assert_not_called()
        self.project.toolboxes.update.assert_not_called()

    def test_promotion_preserves_channel_authentication(self):
        before = self.endpoint.as_dict()
        deploy.promote(self.project, "4", "3")
        updated = self.project.agents.update_details.call_args.kwargs["agent_endpoint"].as_dict()
        self.assertEqual(updated["authorization_schemes"], before["authorization_schemes"])
        self.assertEqual(updated["protocol_configuration"], before["protocol_configuration"])
        self.assertEqual(updated["version_selector"]["version_selection_rules"][0]["agent_version"], "4")
        self.assertEqual(self.endpoint.as_dict(), before)

    def test_promotion_refuses_changed_routing(self):
        with self.assertRaisesRegex(RuntimeError, "routing changed"):
            deploy.promote(self.project, "4", "2")
        self.project.agents.update_details.assert_not_called()

    def test_promotion_refuses_inactive_candidate(self):
        self.project.agents.get_version.return_value.status = "failed"
        with self.assertRaisesRegex(RuntimeError, "not active"):
            deploy.promote(self.project, "4", "3")
        self.project.agents.update_details.assert_not_called()

    def test_package_contains_runtime_and_prompt_without_front_matter(self):
        payload, digest = deploy.package_source()
        self.assertEqual(len(digest), 64)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            self.assertEqual(
                archive.namelist(),
                [
                    "main.py",
                    "request_scoped_tools.py",
                    "requirements.txt",
                    "instructions.txt",
                ],
            )
            prompt = archive.read("instructions.txt").decode("utf-8")
            self.assertTrue(prompt.startswith("You are Elle."))

    def test_smoke_test_pins_session_and_stops_it(self):
        self.project.agents.create_session.return_value.agent_session_id = "candidate-session"
        client = self.project.get_openai_client.return_value.__enter__.return_value
        client.responses.create.return_value.output_text = "Responses protocol"
        self.assertEqual(deploy.smoke_test(self.project, "4"), "Responses protocol")
        indicator = self.project.agents.create_session.call_args.kwargs["version_indicator"]
        self.assertEqual(indicator.agent_version, "4")
        self.assertEqual(
            client.responses.create.call_args.kwargs["extra_body"],
            {"session_id": "candidate-session"},
        )
        self.project.agents.stop_session.assert_called_once_with("elle", "candidate-session")

    def test_smoke_failure_still_stops_diagnostic_session(self):
        self.project.agents.create_session.return_value.agent_session_id = "candidate-session"
        client = self.project.get_openai_client.return_value.__enter__.return_value
        client.responses.create.side_effect = RuntimeError("tool failure")
        with self.assertRaisesRegex(RuntimeError, "tool failure"):
            deploy.smoke_test(self.project, "4")
        self.project.agents.stop_session.assert_called_once_with("elle", "candidate-session")


if __name__ == "__main__":
    unittest.main()
