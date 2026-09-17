import asyncio
import os
from pathlib import Path

from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import FoundryToolbox, ResponsesHostServer
from azure.identity import DefaultAzureCredential

from caller_identity import (
    elle_identity_status,
    validate_identity_binding_probe_nonce,
)
from continuity import load_continuity_config, make_continuity_tool
from request_scoped_tools import RequestScopedToolboxAgent


def load_instructions() -> str:
    path = Path(__file__).with_name("instructions.txt")
    instructions = path.read_text(encoding="utf-8").strip()
    if not instructions:
        raise RuntimeError("instructions.txt is empty")
    return instructions


def build_agent(*, client, credential, toolbox_url: str, name: str, instructions: str):
    lifetime = os.environ.get("ELLE_TOOLBOX_LIFETIME", "request_scoped")
    validate_identity_binding_probe_nonce(
        os.environ.get("ELLE_IDENTITY_BINDING_PROBE_NONCE")
    )
    continuity_config = load_continuity_config(
        os.environ.get("ELLE_CONTINUITY_ENDPOINT"),
        os.environ.get("ELLE_CONTINUITY_SCOPE"),
    )
    local_tools = [elle_identity_status]
    if continuity_config is not None:
        local_tools.append(
            make_continuity_tool(credential=credential, config=continuity_config)
        )
    options = {
        "name": name,
        "client": client,
        "instructions": instructions,
        "default_options": {"store": False},
    }
    if lifetime == "request_scoped":
        return RequestScopedToolboxAgent(
            **options,
            tools=local_tools,
            toolbox_factory=lambda: FoundryToolbox(credential, url=toolbox_url),
        )
    if lifetime == "long_lived":
        toolbox = FoundryToolbox(credential, url=toolbox_url)
        return Agent(**options, tools=[*local_tools, toolbox])
    raise ValueError(f"Unsupported ELLE_TOOLBOX_LIFETIME: {lifetime}")


async def main() -> None:
    model = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-5.6-luna")
    toolbox_url = os.environ["TOOLBOX_ENDPOINT"]
    credential = DefaultAzureCredential(
        exclude_cli_credential=True,
        exclude_developer_cli_credential=True,
        exclude_interactive_browser_credential=True,
        exclude_powershell_credential=True,
        exclude_shared_token_cache_credential=True,
        exclude_visual_studio_code_credential=True,
    )

    client = FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=model,
        credential=credential,
    )
    agent = build_agent(
        name=os.environ.get("FOUNDRY_AGENT_NAME", "elle"),
        client=client,
        instructions=load_instructions(),
        credential=credential,
        toolbox_url=toolbox_url,
    )

    server = ResponsesHostServer(agent)
    await server.run_async()


if __name__ == "__main__":
    asyncio.run(main())
