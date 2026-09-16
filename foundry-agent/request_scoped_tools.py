from collections.abc import Callable, Mapping, Sequence
from typing import Any

from agent_framework import Agent, ResponseStream, normalize_tools
from agent_framework.exceptions import AgentFrameworkException
from agent_framework_foundry_hosting._responses import consent_url_from_error


class RequestScopedToolboxAgent(Agent):
    def __init__(
        self,
        *args: Any,
        toolbox_factory: Callable[[], Any],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._toolbox_factory = toolbox_factory

    async def __aenter__(self) -> Any:
        toolbox = self._toolbox_factory()
        primary_error = None
        close_error = None
        try:
            await toolbox.connect()
        except BaseException as ex:
            primary_error = (ex, ex.__traceback__)
        try:
            await toolbox.close()
        except BaseException as ex:
            close_error = (ex, ex.__traceback__)
        if close_error is not None and (
            primary_error is None or consent_url_from_error(primary_error[0])
        ):
            error, traceback = close_error
            wrapped_error = AgentFrameworkException(
                "Failed to close request-scoped toolbox during host startup",
                error,
            )
            raise wrapped_error.with_traceback(traceback) from error
        if primary_error is not None:
            error, traceback = primary_error
            if not isinstance(error, AgentFrameworkException):
                wrapped_error = AgentFrameworkException(str(error), error)
                raise wrapped_error.with_traceback(traceback) from error
            raise error.with_traceback(traceback)
        return await super().__aenter__()

    def run(
        self,
        messages: Any | None = None,
        *,
        stream: bool = False,
        session: Any | None = None,
        middleware: Sequence[Any] | None = None,
        tools: Any | Callable[..., Any] | Sequence[Any | Callable[..., Any]] | None = None,
        options: Any | None = None,
        compaction_strategy: Any | None = None,
        tokenizer: Any | None = None,
        function_invocation_kwargs: Mapping[str, Any] | None = None,
        client_kwargs: Mapping[str, Any] | None = None,
    ) -> Any:
        parent_run = super().run

        def run_with_tools(toolbox: Any, *, use_stream: bool) -> Any:
            run_tools = [*normalize_tools(tools), toolbox]
            return parent_run(
                messages=messages,
                stream=use_stream,
                session=session,
                middleware=middleware,
                tools=run_tools,
                options=options,
                compaction_strategy=compaction_strategy,
                tokenizer=tokenizer,
                function_invocation_kwargs=function_invocation_kwargs,
                client_kwargs=client_kwargs,
            )

        if not stream:
            async def run_nonstream() -> Any:
                toolbox = self._toolbox_factory()
                primary_error = None
                try:
                    await toolbox.connect()
                    response = await run_with_tools(toolbox, use_stream=False)
                except BaseException as ex:
                    primary_error = (ex, ex.__traceback__)
                try:
                    await toolbox.close()
                except BaseException:
                    if primary_error is None:
                        raise
                if primary_error is not None:
                    error, traceback = primary_error
                    raise error.with_traceback(traceback)
                return response

            return run_nonstream()

        final_response: Any = None
        has_final_response = False

        async def stream_with_toolbox():
            nonlocal final_response, has_final_response
            toolbox = self._toolbox_factory()
            primary_error = None
            try:
                await toolbox.connect()
                inner_stream = run_with_tools(toolbox, use_stream=True)
                async for update in inner_stream:
                    yield update
                final_response = await inner_stream.get_final_response()
                has_final_response = True
            except BaseException as ex:
                primary_error = (ex, ex.__traceback__)
            try:
                await toolbox.close()
            except BaseException:
                if primary_error is None:
                    raise
            if primary_error is not None:
                error, traceback = primary_error
                raise error.with_traceback(traceback)

        def finalize(_updates: Sequence[Any]) -> Any:
            if not has_final_response:
                raise RuntimeError("The inner response stream did not produce a final response.")
            return final_response

        return ResponseStream(stream_with_toolbox(), finalizer=finalize)