import asyncio
import logging
from collections.abc import Callable
from typing import Any

from agent_framework import AgentContext, AgentMiddleware, AgentResponse
from azure.ai.agentserver.core import get_request_context

from private_tools import remember_conversation_turn


logger = logging.getLogger(__name__)


class AutomaticTurnMemory(AgentMiddleware):
    """Queue one private memory after each completed user/assistant turn."""

    def __init__(
        self,
        *,
        endpoint: str | None,
        save_turn: Callable[..., Any] = remember_conversation_turn,
    ) -> None:
        self.endpoint = endpoint
        self.save_turn = save_turn
        self.pending: set[asyncio.Task[None]] = set()

    async def process(self, context: AgentContext, call_next) -> None:
        user_text = next(
            (
                message.text
                for message in reversed(context.messages)
                if message.role == "user" and message.text.strip()
            ),
            "",
        )
        user_id = get_request_context().user_id

        if context.stream:
            context.stream_result_hooks.append(
                lambda response: self._queue(response, user_id, user_text)
            )
            await call_next()
            return

        await call_next()
        if isinstance(context.result, AgentResponse):
            self._queue(context.result, user_id, user_text)

    def _queue(
        self,
        response: AgentResponse,
        user_id: str | None,
        user_text: str,
    ) -> AgentResponse:
        assistant_text = response.text.strip()
        if not user_id or not user_text or not assistant_text:
            return response
        task = asyncio.create_task(
            self._save(
                user_id=user_id,
                user_text=user_text,
                assistant_text=assistant_text,
                response_id=response.response_id,
            )
        )
        self.pending.add(task)
        task.add_done_callback(self.pending.discard)
        return response

    async def _save(
        self,
        *,
        user_id: str,
        user_text: str,
        assistant_text: str,
        response_id: str | None,
    ) -> None:
        try:
            await asyncio.to_thread(
                self.save_turn,
                endpoint=self.endpoint,
                user_id=user_id,
                user_text=user_text,
                assistant_text=assistant_text,
                response_id=response_id,
            )
        except Exception:
            logger.exception("Automatic conversation-turn memory failed")