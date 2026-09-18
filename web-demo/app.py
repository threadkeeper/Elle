import os
import threading
import time

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import VersionRefIndicator
from azure.identity import DefaultAzureCredential
from flask import Flask, jsonify, request


PROJECT_ENDPOINT = os.environ.get(
    "AZURE_AI_PROJECT_ENDPOINT",
    "https://foundry-jva-002.services.ai.azure.com/api/projects/proj-default-sweden",
)
AGENT_NAME = os.environ.get("AZURE_AI_AGENT_NAME", "elle")
AGENT_VERSION = os.environ.get("AZURE_AI_AGENT_VERSION", "20")
MAX_MESSAGE_LENGTH = 8_000

app = Flask(__name__, static_folder="static", static_url_path="")
credential = DefaultAzureCredential()
project = AIProjectClient(PROJECT_ENDPOINT, credential, allow_preview=True)
sessions: dict[str, str] = {}
sessions_lock = threading.Lock()


def caller_id() -> str:
    return request.headers.get("X-MS-CLIENT-PRINCIPAL-ID", "local-demo")


def get_session_id(user_id: str) -> tuple[str, bool]:
    with sessions_lock:
        existing = sessions.get(user_id)
        if existing:
            return existing, True
        created = project.agents.create_session(
            AGENT_NAME,
            version_indicator=VersionRefIndicator(agent_version=AGENT_VERSION),
        )
        if not created.agent_session_id:
            raise RuntimeError("Foundry did not return a session ID")
        sessions[user_id] = created.agent_session_id
        return created.agent_session_id, False


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/api/me")
def me():
    return jsonify(
        {
            "authenticated": "X-MS-CLIENT-PRINCIPAL-ID" in request.headers,
            "name": request.headers.get("X-MS-CLIENT-PRINCIPAL-NAME", "Local demo"),
        }
    )


@app.post("/api/chat")
def chat():
    body = request.get_json(silent=True) or {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return jsonify({"error": "Message is required"}), 400
    message = message.strip()
    if len(message) > MAX_MESSAGE_LENGTH:
        return jsonify({"error": "Message is too long"}), 400

    started = time.perf_counter()
    try:
        session_id, session_reused = get_session_id(caller_id())
        foundry_started = time.perf_counter()
        with project.get_openai_client(agent_name=AGENT_NAME) as client:
            response = client.responses.create(
                input=message,
                extra_body={"session_id": session_id},
            )
        foundry_ms = round((time.perf_counter() - foundry_started) * 1000)
    except Exception:
        app.logger.exception("Elle request failed")
        return jsonify({"error": "Elle request failed"}), 502

    return jsonify(
        {
            "message": response.output_text.strip(),
            "foundryMs": foundry_ms,
            "serverMs": round((time.perf_counter() - started) * 1000),
            "sessionReused": session_reused,
        }
    )


@app.get("/health")
def health():
    return jsonify({"status": "ok"})