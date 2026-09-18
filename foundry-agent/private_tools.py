import hashlib
import json
import logging
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

from azure.ai.agentserver.core import get_request_context


logger = logging.getLogger(__name__)
_DEFAULT_ENDPOINT = (
    "https://elle-private-vnet.yellowsky-9d92d540.swedencentral."
    "azurecontainerapps.io/bridge"
)
_MAX_RESPONSE_BYTES = 1024 * 1024
_TIMEOUT_SECONDS = 20
_MEMORY_CATEGORIES = {"fact", "preference", "project"}
_MAX_MEMORY_CONTENT_BYTES = 16_384


def _memory_payload(content: Any, category: Any, source: Any) -> dict[str, str]:
    normalized_category = category if category in _MEMORY_CATEGORIES else "fact"
    normalized_source = source if isinstance(source, str) and source.strip() else "m365"
    return {
        "content": str(content),
        "category": normalized_category,
        "source": normalized_source,
    }


def _bounded_text(value: str, maximum_bytes: int) -> str:
    encoded = value.encode("utf-8")
    if len(encoded) <= maximum_bytes:
        return value
    return encoded[:maximum_bytes].decode("utf-8", errors="ignore")


def build_automatic_turn_arguments(
    *,
    user_text: str,
    assistant_text: str,
    response_id: str | None,
) -> dict[str, Any]:
    content = _bounded_text(
        f"User:\n{user_text}\n\nElle:\n{assistant_text}",
        _MAX_MEMORY_CONTENT_BYTES,
    )
    key_material = f"{response_id or ''}\0{user_text}\0{assistant_text}".encode("utf-8")
    return {
        "payload": {
            "content": content,
            "category": "project",
            "source": "automatic-conversation-turn",
        },
        "idempotency_key": f"turn-{hashlib.sha256(key_material).hexdigest()}",
        "expires_at": None,
    }


def _request_tool(
    endpoint: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    user_id: str | None = None,
) -> Any:
    user_id = user_id or get_request_context().user_id
    if not user_id:
        raise RuntimeError("Private tools require a platform caller identity")
    request = urllib.request.Request(
        f"{endpoint.rstrip('/')}/{tool_name}",
        data=json.dumps(arguments, separators=(",", ":")).encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Elle-Continuity-Handle-SHA256": hashlib.sha256(user_id.encode("utf-8")).hexdigest(),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise RuntimeError(f"Private tool returned HTTP {response.status}")
            body = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        detail = error.read(512).decode("utf-8", errors="replace")
        raise RuntimeError(f"Private tool returned HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise RuntimeError("Private tool request failed") from error
    if len(body) > _MAX_RESPONSE_BYTES:
        raise RuntimeError("Private tool response exceeded the size limit")
    return json.loads(body)


def remember_conversation_turn(
    *,
    endpoint: str | None,
    user_id: str,
    user_text: str,
    assistant_text: str,
    response_id: str | None,
) -> Any:
    """Persist one completed conversation turn outside the model tool loop."""
    return _request_tool(
        endpoint or _DEFAULT_ENDPOINT,
        "elle_remember",
        build_automatic_turn_arguments(
            user_text=user_text,
            assistant_text=assistant_text,
            response_id=response_id,
        ),
        user_id=user_id,
    )


def private_context(
    *,
    endpoint: str | None,
    query: str,
    limit: int = 5,
    user_id: str | None = None,
    dynamic_only: bool = False,
) -> Any:
    arguments: dict[str, Any] = {"query": query, "limit": limit}
    if dynamic_only:
        arguments["dynamic_only"] = True
    return _request_tool(
        endpoint or _DEFAULT_ENDPOINT,
        "elle_context",
        arguments,
        user_id=user_id,
    )


def make_private_tools(*, endpoint: str | None = None) -> list[Callable[..., Any]]:
    endpoint = endpoint or _DEFAULT_ENDPOINT

    def elle_context(query: str, limit: int = 5) -> Any:
        """Recall relevant private Elle memories and personality guidance."""
        return private_context(endpoint=endpoint, query=query, limit=limit)

    def elle_list_memories() -> Any:
        """List the user's live private Elle memories, IDs, versions, and sources."""
        return _request_tool(endpoint, "elle_list_memories", {})

    def elle_remember(content: str, category: str, source: str) -> Any:
        """Save one private Elle memory after the user has confirmed it."""
        return _request_tool(endpoint, "elle_remember", {
            "payload": _memory_payload(content, category, source),
            "idempotency_key": str(uuid.uuid4()),
            "expires_at": None,
        })

    def elle_correct(memory_id: str, expected_version: int, content: str, category: str, source: str) -> Any:
        """Correct one private Elle memory using its current reviewed version."""
        return _request_tool(endpoint, "elle_correct", {
            "id": memory_id,
            "expected_version": expected_version,
            "payload": _memory_payload(content, category, source),
        })

    def elle_forget(memory_id: str, expected_version: int) -> Any:
        """Delete one private Elle memory using its current reviewed version."""
        return _request_tool(endpoint, "elle_forget", {
            "id": memory_id,
            "expected_version": expected_version,
        })

    def elle_personality() -> Any:
        """Open the user's private Elle personality workshop."""
        return _request_tool(endpoint, "elle_personality", {})

    def elle_set_personality(expected_version: int, settings: dict[str, Any]) -> Any:
        """Save private Elle personality settings after explicit confirmation."""
        return _request_tool(endpoint, "elle_set_personality", {
            "expected_version": expected_version,
            "settings": settings,
        })

    return [
        elle_context,
        elle_list_memories,
        elle_remember,
        elle_correct,
        elle_forget,
        elle_personality,
        elle_set_personality,
    ]
