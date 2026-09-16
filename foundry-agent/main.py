import asyncio
import os
from pathlib import Path

from agent_framework.foundry import FoundryChatClient
from agent_framework_foundry_hosting import FoundryToolbox, ResponsesHostServer
from azure.identity import DefaultAzureCredential

from request_scoped_tools import RequestScopedToolboxAgent


def load_instructions() -> str:
    path = Path(__file__).with_name("instructions.txt")
    instructions = path.read_text(encoding="utf-8").strip()
    if not instructions:
        raise RuntimeError("instructions.txt is empty")
    return instructions


async def main() -> None:
    model = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "model-router")
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
    agent = RequestScopedToolboxAgent(
        name=os.environ.get("FOUNDRY_AGENT_NAME", "elle"),
        client=client,
        instructions=load_instructions(),
        toolbox_factory=lambda: FoundryToolbox(credential, url=toolbox_url),
        default_options={"store": False},
    )

    server = ResponsesHostServer(agent)
    await server.run_async()


if __name__ == "__main__":
    asyncio.run(main())
