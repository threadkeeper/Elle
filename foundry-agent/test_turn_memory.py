import asyncio
import threading
import time
import unittest

from agent_framework import AgentContext, AgentResponse, Message
from azure.ai.agentserver.core import (
    FoundryAgentRequestContext,
    reset_request_context,
    set_request_context,
)

from turn_memory import AutomaticTurnMemory


class AutomaticTurnMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_stream_reply_does_not_wait_for_background_save(self):
        started = threading.Event()
        release = threading.Event()
        captured = []

        def save_turn(**kwargs):
            captured.append(kwargs)
            started.set()
            release.wait(2)

        middleware = AutomaticTurnMemory(
            endpoint="https://example.test/bridge",
            save_turn=save_turn,
        )
        context = AgentContext(
            agent=object(),
            messages=[Message("user", ["latest user turn"])],
            stream=True,
        )

        async def call_next():
            return None

        token = set_request_context(FoundryAgentRequestContext(user_id="demo-user"))
        try:
            await middleware.process(context, call_next)
        finally:
            reset_request_context(token)

        self.assertEqual(len(context.stream_result_hooks), 1)
        response = AgentResponse(
            messages=[Message("assistant", ["final Elle reply"])],
            response_id="response-1",
        )
        before = time.perf_counter()
        returned = context.stream_result_hooks[0](response)
        elapsed = time.perf_counter() - before

        self.assertIs(returned, response)
        self.assertLess(elapsed, 0.05)
        self.assertTrue(await asyncio.to_thread(started.wait, 1))
        self.assertEqual(len(middleware.pending), 1)
        self.assertEqual(
            captured,
            [{
                "endpoint": "https://example.test/bridge",
                "user_id": "demo-user",
                "user_text": "latest user turn",
                "assistant_text": "final Elle reply",
                "response_id": "response-1",
            }],
        )

        pending = list(middleware.pending)
        release.set()
        await asyncio.gather(*pending)
        self.assertFalse(middleware.pending)

    async def test_empty_completed_turn_is_not_queued(self):
        middleware = AutomaticTurnMemory(
            endpoint=None,
            save_turn=lambda **_kwargs: self.fail("save should not run"),
        )
        response = AgentResponse(messages=[Message("assistant", [""])])
        self.assertIs(middleware._queue(response, "demo-user", "hello"), response)
        self.assertFalse(middleware.pending)


if __name__ == "__main__":
    unittest.main()
