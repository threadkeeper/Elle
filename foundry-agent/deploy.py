import argparse
import copy
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEndpointConfig,
    CodeConfiguration,
    CodeDependencyResolution,
    FixedRatioVersionSelectionRule,
    HostedAgentDefinition,
    MCPToolboxTool,
    ProtocolVersionRecord,
    VersionSelector,
    VersionRefIndicator,
)
from azure.identity import AzureCliCredential


ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).resolve().parent
PROJECT_ENDPOINT = (
    "https://foundry-jva-002.services.ai.azure.com/api/projects/"
    "proj-default-sweden"
)
AGENT_NAME = "elle"
TOOLBOX_NAME = "elle-tools"


def prompt_text() -> str:
    text = (ROOT / "ELLE_COPILOT_STUDIO_PROMPT.md").read_text(encoding="utf-8")
    if text.startswith("---"):
        _, _, text = text.partition("---")
        _, separator, text = text.partition("---")
        if not separator:
            raise RuntimeError("Elle prompt front matter is incomplete")
    return text.strip() + "\n"


def package_source() -> tuple[bytes, str]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(SOURCE / "main.py", "main.py")
        archive.write(SOURCE / "caller_identity.py", "caller_identity.py")
        archive.write(SOURCE / "request_scoped_tools.py", "request_scoped_tools.py")
        archive.write(SOURCE / "requirements.txt", "requirements.txt")
        archive.writestr("instructions.txt", prompt_text())
    payload = buffer.getvalue()
    return payload, hashlib.sha256(payload).hexdigest()


def stage_toolbox(
    project: AIProjectClient, additions: list[str], base_version: str | None = None
) -> str:
    current = project.toolboxes.get(TOOLBOX_NAME)
    baseline_version = base_version or current.default_version
    baseline = project.toolboxes.get_version(TOOLBOX_NAME, baseline_version)
    tools = list(baseline.tools)
    names = {tool.name for tool in tools}
    for addition in additions:
        name, separator, connection = addition.partition("=")
        if not separator or not name.strip() or not connection.strip():
            raise ValueError("--add-mcp must be NAME=CONNECTION")
        if name in names:
            raise ValueError(f"Tool source already exists: {name}")
        project.connections.get(connection)
        tools.append(
            MCPToolboxTool(
                name=name,
                server_label=name,
                project_connection_id=connection,
                headers={"Accept": "application/json, text/event-stream"},
                require_approval="never",
            )
        )
        names.add(name)
    if not additions:
        return baseline_version
    created = project.toolboxes.create_version(
        TOOLBOX_NAME,
        description=f"Elle candidate based on toolbox {baseline_version}.",
        metadata={"owner": "Elle", "baseline": baseline_version},
        tools=tools,
        skills=baseline.skills,
        policies=baseline.policies,
    )
    return created.version


def wait_until_active(
    project: AIProjectClient, version: str, timeout_seconds: int = 900
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        details = project.agents.get_version(AGENT_NAME, version)
        status = details["status"]
        print(f"Elle {version}: {status}", flush=True)
        if status == "active":
            return
        if status == "failed":
            raise RuntimeError(
                f"Hosted agent provisioning failed: {dict(details)}"
            )
        time.sleep(10)
    raise TimeoutError("Timed out waiting for the hosted agent to become active")


def deploy(project: AIProjectClient, toolbox_version: str) -> str:
    endpoint = project.agents.get(AGENT_NAME).agent_endpoint
    if endpoint is None or endpoint.version_selector is None:
        raise RuntimeError("Pin live traffic to a version before staging")
    rules = endpoint.version_selector.version_selection_rules
    if not rules or any(rule.type != "FixedRatio" for rule in rules):
        raise RuntimeError("Pin live traffic to a version before staging")
    code, digest = package_source()
    toolbox_endpoint = (
        f"{PROJECT_ENDPOINT}/toolboxes/{TOOLBOX_NAME}/versions/"
        f"{toolbox_version}/mcp?api-version=v1"
    )
    created = project.agents.create_version_from_code(
        agent_name=AGENT_NAME,
        description=(
            "Elle hosted identity diagnostic with governed enterprise tools."
        ),
        definition=HostedAgentDefinition(
            cpu="1",
            memory="2Gi",
            code_configuration=CodeConfiguration(
                runtime="python_3_13",
                entry_point=["python", "main.py"],
                dependency_resolution=CodeDependencyResolution.REMOTE_BUILD,
            ),
            environment_variables={
                "AZURE_AI_MODEL_DEPLOYMENT_NAME": "model-router",
                "ELLE_TOOLBOX_LIFETIME": "request_scoped",
                "TOOLBOX_ENDPOINT": toolbox_endpoint,
            },
            protocol_versions=[
                ProtocolVersionRecord(protocol="responses", version="2.0.0")
            ],
        ),
        code=("elle.zip", code, "application/zip"),
        code_zip_sha256=digest,
    )
    wait_until_active(project, created.version)
    return created.version


def promote(project: AIProjectClient, version: str, expected_live_version: str) -> None:
    candidate = project.agents.get_version(AGENT_NAME, version)
    if candidate.status != "active":
        raise RuntimeError(f"Elle {version} is not active")
    current = project.agents.get(AGENT_NAME)
    endpoint = current.agent_endpoint
    if endpoint is None:
        raise RuntimeError("Elle has no existing endpoint configuration")
    rules = endpoint.version_selector.version_selection_rules
    if len(rules) != 1 or rules[0].agent_version != expected_live_version:
        raise RuntimeError("Live routing changed; inspect it before promotion")
    if rules[0].traffic_percentage != 100:
        raise RuntimeError("Refusing to overwrite split-traffic routing")
    config = AgentEndpointConfig(
        version_selector=VersionSelector(
            version_selection_rules=[
                FixedRatioVersionSelectionRule(
                    agent_version=version, traffic_percentage=100
                )
            ]
        ),
        protocol_configuration=copy.deepcopy(endpoint.protocol_configuration),
        authorization_schemes=copy.deepcopy(endpoint.authorization_schemes),
    )
    project.agents.update_details(AGENT_NAME, agent_endpoint=config)


def smoke_test(project: AIProjectClient, version: str) -> str:
    session = project.agents.create_session(
        AGENT_NAME, version_indicator=VersionRefIndicator(agent_version=version)
    )
    if not session.agent_session_id:
        raise RuntimeError("Foundry did not return a candidate session ID")
    try:
        with project.get_openai_client(agent_name=AGENT_NAME) as client:
            response = client.responses.create(
                input=(
                    "Read-only deployment diagnostic: do not save a memory. Use "
                    "Microsoft Learn to name the protocol used by Foundry hosted agents."
                ),
                extra_body={"session_id": session.agent_session_id},
            )
    finally:
        project.agents.stop_session(AGENT_NAME, session.agent_session_id)
    if not response.output_text.strip():
        raise RuntimeError("Elle returned an empty smoke-test response")
    return response.output_text.strip()


def main() -> None:
    global PROJECT_ENDPOINT

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-endpoint", default=PROJECT_ENDPOINT)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--promote-version", help="Promote an already-tested version")
    action.add_argument("--test-version", help="Smoke-test one explicit candidate")
    parser.add_argument("--expected-live-version", help="Required guard for promotion")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--toolbox-version", help="Stage against this existing toolbox")
    source.add_argument("--add-mcp", action="append", default=[], metavar="NAME=CONNECTION")
    parser.add_argument("--base-toolbox-version", help="Baseline for --add-mcp")
    args = parser.parse_args()
    if args.promote_version and not args.expected_live_version:
        parser.error("--promote-version requires --expected-live-version")
    if (args.promote_version or args.test_version) and (args.toolbox_version or args.add_mcp):
        parser.error("Testing/promotion cannot be combined with staging options")
    if args.base_toolbox_version and not args.add_mcp:
        parser.error("--base-toolbox-version requires --add-mcp")

    PROJECT_ENDPOINT = args.project_endpoint.rstrip("/")
    credential = AzureCliCredential(process_timeout=120)
    with AIProjectClient(PROJECT_ENDPOINT, credential, allow_preview=True) as project:
        if args.promote_version:
            promote(project, args.promote_version, args.expected_live_version)
            print(json.dumps({"promotedVersion": args.promote_version}))
            return
        if args.test_version:
            print(smoke_test(project, args.test_version))
            return
        toolbox_version = args.toolbox_version or stage_toolbox(
            project, args.add_mcp, args.base_toolbox_version
        )
        project.toolboxes.get_version(TOOLBOX_NAME, toolbox_version)
        agent_version = deploy(project, toolbox_version)

    print(
        json.dumps(
            {
                "agent": AGENT_NAME,
                "agentVersion": agent_version,
                "model": "model-router",
                "projectEndpoint": PROJECT_ENDPOINT,
                "toolbox": TOOLBOX_NAME,
                "toolboxVersion": toolbox_version,
                "promoted": False,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Deployment failed: {error}", file=sys.stderr)
        raise
