import asyncio
import inspect
import unittest
from unittest.mock import patch

from agent_framework import Agent, ChatResponseUpdate, Content, ResponseStream, normalize_tools
from agent_framework.exceptions import AgentFrameworkException
from agent_framework_foundry_hosting import ResponsesHostServer
from azure.ai.agentserver.core import (
    FoundryAgentRequestContext,
    reset_request_context,
    set_request_context,
)
from azure.ai.agentserver.responses._response_context import ResponseContext
from azure.ai.agentserver.responses.models.runtime import ResponseModeFlags
from mcp import ErrorData, McpError

from request_scoped_tools import RequestScopedToolboxAgent


class FakeToolbox:
    def __init__(self, events, *, connect_error=None, close_error=None):
        self.events = events
        self.connect_error = connect_error
        self.close_error = close_error
        self.close_calls = 0

    async def connect(self):
        self.events.append("connect")
        if self.connect_error is not None:
            raise self.connect_error

    async def close(self):
        self.close_calls += 1
        self.events.append("close")
        if self.close_error is not None:
            raise self.close_error


class InMemoryStoreProvider:
    def __init__(self, *, set_error=None):
        self.sessions = {}
        self.set_error = set_error

    def get_store(self, **kwargs):
        return self

    async def get(self, session_id):
        return self.sessions.get(session_id)

    async def set(self, session_id, session):
        if self.set_error is not None:
            raise self.set_error
        self.sessions[session_id] = session


class RequestScopedToolboxAgentTests(unittest.IsolatedAsyncioTestCase):
    def make_agent(self, factory):
        return RequestScopedToolboxAgent(client=object(), toolbox_factory=factory)

    async def test_nonstream_connects_and_closes_one_toolbox(self):
        events = []
        toolbox = FakeToolbox(events)
        agent = self.make_agent(lambda: toolbox)

        async def fake_run(_agent, messages=None, *, stream=False, tools=None, **kwargs):
            self.assertFalse(stream)
            self.assertEqual(messages, "hello")
            self.assertIs(tools[-1], toolbox)
            events.append("run")
            return "response"

        with patch.object(Agent, "run", fake_run):
            response = await agent.run("hello")

        self.assertEqual(response, "response")
        self.assertEqual(events, ["connect", "run", "close"])

    async def test_nonstream_error_closes_toolbox_once(self):
        events = []
        toolbox = FakeToolbox(events)
        agent = self.make_agent(lambda: toolbox)

        async def fake_run(_agent, **kwargs):
            raise RuntimeError("model failed")

        with patch.object(Agent, "run", fake_run):
            with self.assertRaisesRegex(RuntimeError, "model failed"):
                await agent.run("hello")

        self.assertEqual(events, ["connect", "close"])
        self.assertEqual(toolbox.close_calls, 1)

    async def test_nonstream_error_precedes_close_error(self):
        events = []
        toolbox = FakeToolbox(events, close_error=RuntimeError("close failed"))
        agent = self.make_agent(lambda: toolbox)

        async def fake_run(_agent, **kwargs):
            raise RuntimeError("model failed")

        with patch.object(Agent, "run", fake_run):
            with self.assertRaisesRegex(RuntimeError, "model failed"):
                await agent.run("hello")

        self.assertEqual(events, ["connect", "close"])
        self.assertEqual(toolbox.close_calls, 1)

    async def test_never_pulled_stream_creates_no_toolbox(self):
        created = []

        def factory():
            created.append(True)
            return FakeToolbox([])

        agent = self.make_agent(factory)
        stream = agent.run("hello", stream=True)

        self.assertIsInstance(stream, ResponseStream)
        self.assertEqual(created, [])

    async def test_stream_finalizes_inner_response_before_close(self):
        events = []
        toolbox = FakeToolbox(events)
        agent = self.make_agent(lambda: toolbox)

        async def updates():
            events.append("first")
            yield "first"
            events.append("last")
            yield "last"

        def inner_finalizer(items):
            self.assertEqual(toolbox.close_calls, 0)
            events.append("finalize")
            return "final response"

        def inner_result_hook(response):
            self.assertEqual(toolbox.close_calls, 0)
            events.append("result hook")
            return f"{response} with hook"

        def fake_run(_agent, *, stream=False, **kwargs):
            self.assertTrue(stream)
            return ResponseStream(updates(), finalizer=inner_finalizer).with_result_hook(inner_result_hook)

        with patch.object(Agent, "run", fake_run):
            stream = agent.run("hello", stream=True)
            received = [update async for update in stream]
            final_response = await stream.get_final_response()

        self.assertEqual(received, ["first", "last"])
        self.assertEqual(final_response, "final response with hook")
        self.assertEqual(events, ["connect", "first", "last", "finalize", "result hook", "close"])
        self.assertEqual(toolbox.close_calls, 1)

    async def test_stream_error_closes_toolbox_once(self):
        events = []
        toolbox = FakeToolbox(events)
        agent = self.make_agent(lambda: toolbox)

        async def updates():
            if False:
                yield None
            raise RuntimeError("stream failed")

        def fake_run(_agent, **kwargs):
            return ResponseStream(updates())

        with patch.object(Agent, "run", fake_run):
            stream = agent.run("hello", stream=True)
            with self.assertRaisesRegex(RuntimeError, "stream failed"):
                await stream.__anext__()

        self.assertEqual(toolbox.close_calls, 1)

    async def test_stream_cancellation_closes_toolbox_once(self):
        events = []
        toolbox = FakeToolbox(events)
        agent = self.make_agent(lambda: toolbox)
        started = asyncio.Event()
        release = asyncio.Event()

        async def updates():
            started.set()
            await release.wait()
            yield "late"

        def fake_run(_agent, **kwargs):
            return ResponseStream(updates())

        with patch.object(Agent, "run", fake_run):
            stream = agent.run("hello", stream=True)
            pull = asyncio.create_task(stream.__anext__())
            await asyncio.wait_for(started.wait(), timeout=2)
            pull.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pull

        self.assertEqual(toolbox.close_calls, 1)

    async def test_backing_generator_close_closes_toolbox_once(self):
        events = []
        toolbox = FakeToolbox(events)
        agent = self.make_agent(lambda: toolbox)

        async def updates():
            yield "first"
            yield "second"

        def fake_run(_agent, **kwargs):
            return ResponseStream(updates())

        with patch.object(Agent, "run", fake_run):
            stream = agent.run("hello", stream=True)
            self.assertEqual(await stream.__anext__(), "first")
            await stream._iterator.aclose()

        self.assertEqual(toolbox.close_calls, 1)

    async def test_connect_error_closes_and_next_run_uses_fresh_toolbox(self):
        events = []
        first = FakeToolbox(events, connect_error=RuntimeError("connect failed"))
        second = FakeToolbox(events)
        available = iter([first, second])
        agent = self.make_agent(lambda: next(available))

        async def fake_run(_agent, **kwargs):
            events.append("run")
            return "response"

        with patch.object(Agent, "run", fake_run):
            with self.assertRaisesRegex(RuntimeError, "connect failed"):
                await agent.run("first")
            self.assertEqual(await agent.run("second"), "response")

        self.assertEqual(first.close_calls, 1)
        self.assertEqual(second.close_calls, 1)
        self.assertEqual(events, ["connect", "close", "connect", "run", "close"])

    async def test_host_emits_first_use_consent_closes_and_retries(self):
        events = []
        consent_error = AgentFrameworkException(
            "Failed to connect to MCP server",
            McpError(
                ErrorData(
                    code=-32006,
                    message=(
                        'tools/list failed {"errors":[{"name":"elle_private","type":"mcp",'
                        '"error":{"code":"CONSENT_REQUIRED",'
                        '"message":"https://login.example.test/consent"}}]}'
                    ),
                )
            ),
        )
        first = FakeToolbox(events, connect_error=consent_error)
        retry_preflight = FakeToolbox(events)
        retry_run = FakeToolbox(events)
        available = iter([first, retry_preflight, retry_run])
        agent = self.make_agent(lambda: next(available))
        store_provider = InMemoryStoreProvider()
        host = ResponsesHostServer(
            agent,
            history_source="agent",
            agent_session_store_provider=store_provider,
            function_approval_store_provider=store_provider,
        )

        async def updates():
            yield ChatResponseUpdate(
                contents=[Content.from_text("ok")],
                role="assistant",
            )

        def fake_run(_agent, **kwargs):
            events.append("run")
            return ResponseStream(updates(), finalizer=lambda _items: "response")

        async def host_events(response_id, request=None):
            context = ResponseContext(
                response_id=response_id,
                mode_flags=ResponseModeFlags(stream=True, store=True, background=False),
                input_items=[{"type": "message", "role": "user", "content": "hello"}],
            )
            token = set_request_context(FoundryAgentRequestContext(call_id=response_id))
            try:
                return [
                    event
                    async for event in host._handle_response(request or {}, context, asyncio.Event())
                ]
            finally:
                reset_request_context(token)

        try:
            with patch.object(Agent, "run", fake_run):
                first_events = await host_events("CALL-CONSENT")
                second_events = await host_events(
                    "CALL-RETRY",
                    {"previous_response_id": "CALL-CONSENT"},
                )
        finally:
            await host._cleanup_agent()

        first_types = [event["type"] for event in first_events]
        self.assertNotIn("response.failed", first_types)
        self.assertEqual(first_types[-1], "response.incomplete")
        oauth_items = [
            event["item"]
            for event in first_events
            if event["type"] == "response.output_item.added"
            and event["item"]["type"] == "oauth_consent_request"
        ]
        self.assertEqual(len(oauth_items), 1)
        self.assertEqual(oauth_items[0]["server_label"], "elle_private")
        self.assertEqual(oauth_items[0]["consent_link"], "https://login.example.test/consent")
        self.assertEqual([event["type"] for event in second_events][-1], "response.completed")
        self.assertEqual(first.close_calls, 1)
        self.assertEqual(retry_preflight.close_calls, 1)
        self.assertEqual(retry_run.close_calls, 1)
        self.assertIn("CALL-CONSENT", store_provider.sessions)
        self.assertIs(
            store_provider.sessions["CALL-CONSENT"],
            store_provider.sessions["CALL-RETRY"],
        )
        self.assertEqual(
            events,
            ["connect", "close", "connect", "close", "connect", "run", "close"],
        )

    async def test_host_persistence_failure_emits_no_consent(self):
        events = []
        consent_error = AgentFrameworkException(
            "Failed to connect to MCP server",
            McpError(
                ErrorData(
                    code=-32006,
                    message=(
                        'tools/list failed {"errors":[{"name":"elle_private","type":"mcp",'
                        '"error":{"code":"CONSENT_REQUIRED",'
                        '"message":"https://login.example.test/consent"}}]}'
                    ),
                )
            ),
        )
        toolbox = FakeToolbox(events, connect_error=consent_error)
        agent = self.make_agent(lambda: toolbox)
        store_provider = InMemoryStoreProvider(set_error=RuntimeError("store failed"))
        host = ResponsesHostServer(
            agent,
            history_source="agent",
            agent_session_store_provider=store_provider,
            function_approval_store_provider=store_provider,
        )
        context = ResponseContext(
            response_id="CALL-STORE-FAIL",
            mode_flags=ResponseModeFlags(stream=True, store=True, background=False),
            input_items=[{"type": "message", "role": "user", "content": "hello"}],
        )
        token = set_request_context(FoundryAgentRequestContext(call_id=context.response_id))
        try:
            host_events = [
                event
                async for event in host._handle_response({}, context, asyncio.Event())
            ]
        finally:
            reset_request_context(token)
            await host._cleanup_agent()

        self.assertEqual(host_events[-1]["type"], "response.failed")
        self.assertIn("store failed", str(host_events[-1]))
        self.assertFalse(
            any(
                event["type"] == "response.output_item.added"
                and event["item"]["type"] == "oauth_consent_request"
                for event in host_events
            )
        )
        self.assertEqual(toolbox.close_calls, 1)
        self.assertEqual(events, ["connect", "close"])

    async def test_host_mixed_valid_invalid_consent_emits_no_consent(self):
        events = []
        consent_error = AgentFrameworkException(
            "Failed to connect to MCP server",
            McpError(
                ErrorData(
                    code=-32006,
                    message=(
                        'tools/list failed {"errors":['
                        '{"name":"elle_private","type":"mcp",'
                        '"error":{"code":"CONSENT_REQUIRED",'
                        '"message":"https://login.example.test/consent"}},'
                        '{"name":"unsafe_source","type":"mcp",'
                        '"error":{"code":"CONSENT_REQUIRED",'
                        '"message":"http://unsafe.example.test/consent"}}]}'
                    ),
                )
            ),
        )
        toolbox = FakeToolbox(events, connect_error=consent_error)
        agent = self.make_agent(lambda: toolbox)
        store_provider = InMemoryStoreProvider()
        host = ResponsesHostServer(
            agent,
            history_source="agent",
            agent_session_store_provider=store_provider,
            function_approval_store_provider=store_provider,
        )
        context = ResponseContext(
            response_id="CALL-MIXED-CONSENT",
            mode_flags=ResponseModeFlags(stream=True, store=True, background=False),
            input_items=[{"type": "message", "role": "user", "content": "hello"}],
        )
        token = set_request_context(FoundryAgentRequestContext(call_id=context.response_id))
        try:
            host_events = [
                event
                async for event in host._handle_response({}, context, asyncio.Event())
            ]
        finally:
            reset_request_context(token)
            await host._cleanup_agent()

        self.assertEqual(host_events[-1]["type"], "response.failed")
        self.assertIn("safe HTTPS consent link", str(host_events[-1]))
        self.assertFalse(
            any(
                event["type"] == "response.output_item.added"
                and event["item"]["type"] == "oauth_consent_request"
                for event in host_events
            )
        )
        self.assertEqual(toolbox.close_calls, 1)
        self.assertEqual(events, ["connect", "close"])

    async def test_host_close_failure_emits_no_consent_before_response_failed(self):
        events = []
        consent_error = AgentFrameworkException(
            "Failed to connect to MCP server",
            McpError(
                ErrorData(
                    code=-32006,
                    message=(
                        'tools/list failed {"errors":[{"name":"elle_private","type":"mcp",'
                        '"error":{"code":"CONSENT_REQUIRED",'
                        '"message":"https://login.example.test/consent"}}]}'
                    ),
                )
            ),
        )
        toolbox = FakeToolbox(
            events,
            connect_error=consent_error,
            close_error=RuntimeError("close failed"),
        )
        agent = self.make_agent(lambda: toolbox)
        store_provider = InMemoryStoreProvider()
        host = ResponsesHostServer(
            agent,
            history_source="agent",
            agent_session_store_provider=store_provider,
            function_approval_store_provider=store_provider,
        )
        context = ResponseContext(
            response_id="CALL-CLOSE-CONSENT",
            mode_flags=ResponseModeFlags(stream=True, store=True, background=False),
            input_items=[{"type": "message", "role": "user", "content": "hello"}],
        )
        token = set_request_context(FoundryAgentRequestContext(call_id=context.response_id))
        try:
            host_events = [
                event
                async for event in host._handle_response({}, context, asyncio.Event())
            ]
        finally:
            reset_request_context(token)
            await host._cleanup_agent()

        event_types = [event["type"] for event in host_events]
        self.assertEqual(event_types[-1], "response.failed")
        self.assertFalse(
            any(
                event["type"] == "response.output_item.added"
                and event["item"]["type"] == "oauth_consent_request"
                for event in host_events
            )
        )
        self.assertEqual(toolbox.close_calls, 1)
        self.assertEqual(events, ["connect", "close"])

    async def test_host_connect_error_precedes_close_error(self):
        events = []
        toolbox = FakeToolbox(
            events,
            connect_error=RuntimeError("connect failed"),
            close_error=RuntimeError("close failed"),
        )
        agent = self.make_agent(lambda: toolbox)
        store_provider = InMemoryStoreProvider()
        host = ResponsesHostServer(
            agent,
            history_source="agent",
            agent_session_store_provider=store_provider,
            function_approval_store_provider=store_provider,
        )
        context = ResponseContext(
            response_id="CALL-CONNECT-ERROR",
            mode_flags=ResponseModeFlags(stream=True, store=True, background=False),
            input_items=[{"type": "message", "role": "user", "content": "hello"}],
        )
        token = set_request_context(FoundryAgentRequestContext(call_id=context.response_id))
        try:
            host_events = [
                event
                async for event in host._handle_response({}, context, asyncio.Event())
            ]
        finally:
            reset_request_context(token)
            await host._cleanup_agent()

        failed_event = host_events[-1]
        self.assertEqual(failed_event["type"], "response.failed")
        self.assertIn("connect failed", str(failed_event))
        self.assertNotIn("close failed", str(failed_event))
        self.assertEqual(toolbox.close_calls, 1)
        self.assertEqual(events, ["connect", "close"])

    async def test_host_run_error_precedes_close_error(self):
        events = []
        preflight = FakeToolbox(events)
        toolbox = FakeToolbox(events, close_error=RuntimeError("close failed"))
        available = iter([preflight, toolbox])
        agent = self.make_agent(lambda: next(available))
        store_provider = InMemoryStoreProvider()
        host = ResponsesHostServer(
            agent,
            history_source="agent",
            agent_session_store_provider=store_provider,
            function_approval_store_provider=store_provider,
        )

        def fake_run(_agent, **kwargs):
            async def updates():
                if False:
                    yield None
                raise RuntimeError("model failed")

            return ResponseStream(updates())

        context = ResponseContext(
            response_id="CALL-CLOSE-ERROR",
            mode_flags=ResponseModeFlags(stream=True, store=True, background=False),
            input_items=[{"type": "message", "role": "user", "content": "hello"}],
        )
        token = set_request_context(FoundryAgentRequestContext(call_id=context.response_id))
        try:
            with patch.object(Agent, "run", fake_run):
                host_events = [
                    event
                    async for event in host._handle_response({}, context, asyncio.Event())
                ]
        finally:
            reset_request_context(token)
            await host._cleanup_agent()

        failed_event = host_events[-1]
        self.assertEqual(failed_event["type"], "response.failed")
        self.assertIn("model failed", str(failed_event))
        self.assertNotIn("close failed", str(failed_event))
        self.assertEqual(preflight.close_calls, 1)
        self.assertEqual(toolbox.close_calls, 1)
        self.assertEqual(events, ["connect", "close", "connect", "close"])

    async def test_supplied_non_mcp_tools_are_preserved_without_mutation(self):
        events = []
        toolbox = FakeToolbox(events)
        agent = self.make_agent(lambda: toolbox)

        def supplied_tool(value: str) -> str:
            return value

        normalized_tool = normalize_tools(supplied_tool)[0]
        supplied_tools = [normalized_tool]
        defaults_before = dict(agent.default_options)

        async def fake_run(_agent, *, tools=None, **kwargs):
            self.assertEqual(len(tools), 2)
            self.assertIs(tools[0], normalized_tool)
            self.assertIs(tools[1], toolbox)
            return "response"

        with patch.object(Agent, "run", fake_run):
            await agent.run("hello", tools=supplied_tools)

        self.assertEqual(supplied_tools, [normalized_tool])
        self.assertEqual(agent.default_options, defaults_before)

    def test_run_signature_preserves_public_runtime_options(self):
        parameters = inspect.signature(RequestScopedToolboxAgent.run).parameters
        expected = {
            "messages",
            "stream",
            "session",
            "middleware",
            "tools",
            "options",
            "compaction_strategy",
            "tokenizer",
            "function_invocation_kwargs",
            "client_kwargs",
        }
        self.assertTrue(expected.issubset(parameters))


if __name__ == "__main__":
    unittest.main()