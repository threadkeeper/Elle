import argparse
import json
import time
import uuid
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import VersionRefIndicator
from azure.identity import AzureCliCredential

from deploy import AGENT_NAME, PROJECT_ENDPOINT


def timed(call, *args, **kwargs) -> tuple[Any, int]:
    started = time.perf_counter()
    result = call(*args, **kwargs)
    return result, round((time.perf_counter() - started) * 1000)


def run_benchmark(project: AIProjectClient, version: str, marker: str) -> dict[str, Any]:
    sessions: list[str] = []
    results: dict[str, Any] = {"agentVersion": version, "marker": marker}

    try:
        save_session, results["saveSessionMs"] = timed(
            project.agents.create_session,
            AGENT_NAME,
            version_indicator=VersionRefIndicator(agent_version=version),
        )
        sessions.append(save_session.agent_session_id)

        with project.get_openai_client(agent_name=AGENT_NAME) as client:
            save, results["coldSaveMs"] = timed(
                client.responses.create,
                input=(
                    "This is synthetic benchmark data. Please remember that my "
                    f"benchmark marker is {marker}. I explicitly confirm saving it "
                    "as a fact. Reply with SAVED and the marker only after the "
                    "private memory save succeeds."
                ),
                extra_body={"session_id": save_session.agent_session_id},
            )
            results["saveReply"] = save.output_text.strip()

            recall_session, results["recallSessionMs"] = timed(
                project.agents.create_session,
                AGENT_NAME,
                version_indicator=VersionRefIndicator(agent_version=version),
            )
            sessions.append(recall_session.agent_session_id)

            recall, results["coldRecallMs"] = timed(
                client.responses.create,
                input=(
                    "Use my private memory and return my exact synthetic benchmark "
                    "marker. Reply with the marker only."
                ),
                extra_body={"session_id": recall_session.agent_session_id},
            )
            results["coldRecallReply"] = recall.output_text.strip()

            warm_recall, results["warmRecallMs"] = timed(
                client.responses.create,
                input="Return that same benchmark marker again, with no other text.",
                extra_body={"session_id": recall_session.agent_session_id},
            )
            results["warmRecallReply"] = warm_recall.output_text.strip()

            warm_plain, results["warmPlainMs"] = timed(
                client.responses.create,
                input="Without using memory, reply with exactly: LATENCY CHECK OK",
                extra_body={"session_id": recall_session.agent_session_id},
            )
            results["warmPlainReply"] = warm_plain.output_text.strip()
    finally:
        for session_id in sessions:
            project.agents.stop_session(AGENT_NAME, session_id)

    results["saveVerified"] = marker in results["saveReply"]
    results["coldRecallVerified"] = results["coldRecallReply"] == marker
    results["warmRecallVerified"] = results["warmRecallReply"] == marker
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-endpoint", default=PROJECT_ENDPOINT)
    parser.add_argument("--version", required=True)
    parser.add_argument(
        "--marker",
        default=f"ELLE-BENCH-{uuid.uuid4().hex[:12].upper()}",
    )
    args = parser.parse_args()

    credential = AzureCliCredential(process_timeout=120)
    with AIProjectClient(
        args.project_endpoint.rstrip("/"),
        credential,
        allow_preview=True,
    ) as project:
        result = run_benchmark(project, args.version, args.marker)

    print(json.dumps(result, indent=2))
    if not all(
        result[key]
        for key in ("saveVerified", "coldRecallVerified", "warmRecallVerified")
    ):
        raise RuntimeError("Private-memory benchmark verification failed")


if __name__ == "__main__":
    main()