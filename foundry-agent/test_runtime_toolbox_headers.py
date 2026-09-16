import asyncio
import contextlib
import contextvars
import socket
import time
import unittest
from collections.abc import Awaitable, Callable
from unittest.mock import patch

import uvicorn
from agent_framework import Agent, ChatResponse, Message
from agent_framework_foundry_hosting import FoundryToolbox
from azure.ai.agentserver.core import (
    FoundryAgentRequestContext,
    reset_request_context,
    set_request_context,
)
from azure.core.credentials import AccessToken
from mcp.server.fastmcp import FastMCP

from request_scoped_tools import RequestScopedToolboxAgent


CALL_ID_HEADER = b"x-agent-foundry-call-id"
CONCURRENT_ARRIVAL_TIMEOUT_SECONDS = 15
recorded_call_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "recorded_call_id",
    default=None,
)


class StaticCredential:
    def get_token(self, *scopes: str, **kwargs: object) -> AccessToken:
        return AccessToken("synthetic-token", int(time.time()) + 3600)


class StaticChatClient:
    additional_properties = {}

    def get_response(self, messages, *, stream=False, options=None, **kwargs):
        if stream:
            raise AssertionError("This client only supports the nonstream retention test")

        async def response():
            return ChatResponse(messages=[Message("assistant", ["ok"])])

        return response()


class HeaderRecorder:
    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app
        self.call_ids: list[str | None] = []

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] == "http" and scope["method"] == "POST":
            value = dict(scope["headers"]).get(CALL_ID_HEADER)
            call_id = value.decode("ascii") if value else None
            self.call_ids.append(call_id)
            token = recorded_call_id.set(call_id)
            try:
                await self.app(scope, receive, send)
            finally:
                recorded_call_id.reset(token)
            return
        await self.app(scope, receive, send)


class CountingFoundryToolbox(FoundryToolbox):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.connect_calls = 0
        self.close_calls = 0

    async def connect(self, *, reset: bool = False) -> None:
        self.connect_calls += 1
        await super().connect(reset=reset)

    async def close(self) -> None:
        self.close_calls += 1
        await super().close()


async def wait_until_started(server: uvicorn.Server) -> None:
    for _ in range(200):
        if server.started:
            return
        await asyncio.sleep(0.01)
    raise RuntimeError("Local MCP server did not start")


class ToolboxHeaderIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.arrivals: list[str] = []
        self.arrival_pairs: list[tuple[str, str | None]] = []
        self.arrival_events: dict[str, asyncio.Event] = {}
        self.release = asyncio.Event()
        mcp = FastMCP("request-context-test", stateless_http=True, json_response=True)

        @mcp.tool()
        async def echo_call(value: str) -> str:
            if value.startswith("concurrent-"):
                self.arrivals.append(value)
                self.arrival_pairs.append((value, recorded_call_id.get()))
                self.arrival_events[value].set()
                await self.release.wait()
            return value

        self.recorder = HeaderRecorder(mcp.streamable_http_app())
        self.listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listen_socket.bind(("127.0.0.1", 0))
        self.listen_socket.listen()
        port = self.listen_socket.getsockname()[1]
        self.toolbox_url = f"http://127.0.0.1:{port}/mcp"
        config = uvicorn.Config(self.recorder, log_level="error", lifespan="on")
        self.server = uvicorn.Server(config)
        self.server_task = asyncio.create_task(self.server.serve(sockets=[self.listen_socket]))
        await wait_until_started(self.server)

    async def asyncTearDown(self):
        self.release.set()
        self.server.should_exit = True
        with contextlib.suppress(asyncio.CancelledError):
            await self.server_task

    def make_agent(self, client=None):
        self.toolboxes: list[CountingFoundryToolbox] = []

        def factory():
            toolbox = CountingFoundryToolbox(StaticCredential(), url=self.toolbox_url)
            self.toolboxes.append(toolbox)
            return toolbox

        return RequestScopedToolboxAgent(client=client or object(), toolbox_factory=factory)

    async def invoke(self, agent, call_id: str, value: str):
        token = set_request_context(FoundryAgentRequestContext(call_id=call_id))
        try:
            return await agent.run(value)
        finally:
            reset_request_context(token)

    async def test_sequential_runs_bind_fresh_call_ids(self):
        agent = self.make_agent()

        async def fake_run(_agent, messages=None, *, tools=None, **kwargs):
            return await tools[-1].call_tool("echo_call", value=messages)

        with patch.object(Agent, "run", fake_run):
            await self.invoke(agent, "CALL-1", "first")
            first_end = len(self.recorder.call_ids)
            await self.invoke(agent, "CALL-2", "second")

        first_ids = self.recorder.call_ids[:first_end]
        second_ids = self.recorder.call_ids[first_end:]
        self.assertTrue(first_ids)
        self.assertTrue(second_ids)
        self.assertEqual(set(first_ids), {"CALL-1"})
        self.assertEqual(set(second_ids), {"CALL-2"})
        self.assertEqual(len(self.toolboxes), 2)
        self.assertTrue(all(toolbox.connect_calls == 1 for toolbox in self.toolboxes))
        self.assertTrue(all(toolbox.close_calls == 1 for toolbox in self.toolboxes))

    async def test_preconnected_toolbox_is_not_retained_by_agent_exit_stack(self):
        agent = self.make_agent(StaticChatClient())

        await self.invoke(agent, "CALL-STACK", "hello")
        self.assertEqual(len(self.toolboxes), 1)
        self.assertEqual(self.toolboxes[0].close_calls, 1)

        await agent.__aexit__(None, None, None)

        self.assertEqual(self.toolboxes[0].close_calls, 1)

    async def test_concurrent_runs_arrive_before_release_with_own_call_ids(self):
        agent = self.make_agent()
        first_arrived = asyncio.Event()
        second_arrived = asyncio.Event()
        self.arrival_events = {
            "concurrent-a": first_arrived,
            "concurrent-b": second_arrived,
        }

        async def fake_run(_agent, messages=None, *, tools=None, **kwargs):
            return await tools[-1].call_tool("echo_call", value=messages)

        with patch.object(Agent, "run", fake_run):
            first = asyncio.create_task(self.invoke(agent, "CALL-A", "concurrent-a"))
            second = asyncio.create_task(self.invoke(agent, "CALL-B", "concurrent-b"))
            try:
                await asyncio.wait_for(
                    asyncio.gather(first_arrived.wait(), second_arrived.wait()),
                    timeout=CONCURRENT_ARRIVAL_TIMEOUT_SECONDS,
                )
                self.assertFalse(first.done())
                self.assertFalse(second.done())
            finally:
                self.release.set()
            await asyncio.gather(first, second)

        self.assertCountEqual(self.arrivals, ["concurrent-a", "concurrent-b"])
        self.assertCountEqual(
            self.arrival_pairs,
            [("concurrent-a", "CALL-A"), ("concurrent-b", "CALL-B")],
        )
        self.assertEqual(set(self.recorder.call_ids), {"CALL-A", "CALL-B"})
        self.assertEqual(len(self.toolboxes), 2)
        self.assertTrue(all(toolbox.close_calls == 1 for toolbox in self.toolboxes))


if __name__ == "__main__":
    unittest.main()