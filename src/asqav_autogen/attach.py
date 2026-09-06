"""attach(): route an AutoGen tool or workbench call through a GuardrailProvider.

Wraps BaseTool.run_json or Workbench.call_tool in an explicit proxy class. No
autogen internals are patched. On DENY the underlying tool never runs, on
MODIFY it runs with the rewritten args, and on ALLOW it runs unchanged.
"""

from __future__ import annotations

from typing import Any, Mapping

from autogen_core import CancellationToken
from autogen_core.tools import BaseTool, TextResultContent, ToolResult, Workbench
from pydantic import BaseModel

from .protocol import Decision, GuardrailProvider, GuardrailResult

__all__ = ["attach", "GuardedTool", "GuardedWorkbench"]

_DENY_PREFIX = "Tool call denied by asqav guardrail"


def _validate_result(result: GuardrailResult) -> None:
    if not isinstance(result, GuardrailResult) or not isinstance(result.decision, Decision):
        raise TypeError("guardrail.evaluate() must return a GuardrailResult with a Decision")
    if result.modified_args is not None and not isinstance(result.modified_args, Mapping):
        raise TypeError("GuardrailResult.modified_args must be a mapping or None")


class GuardedTool(BaseTool):
    """Guard a tool's non-streaming execution and preserve its public tool interface."""

    def __init__(
        self,
        tool: Any,
        guardrail: GuardrailProvider,
        *,
        agent_name: str | None = None,
    ) -> None:
        self._tool = tool
        self._guardrail = guardrail
        self._agent_name = agent_name

    @property
    def name(self):
        return self._tool.name

    @property
    def description(self):
        return self._tool.description

    @property
    def schema(self):
        return self._tool.schema

    def args_type(self):
        return self._tool.args_type()

    def return_type(self):
        return self._tool.return_type()

    def state_type(self):
        return self._tool.state_type()

    def return_value_as_string(self, value: Any) -> str:
        return self._tool.return_value_as_string(value)

    async def save_state_json(self):
        return await self._tool.save_state_json()

    async def load_state_json(self, state: Mapping[str, Any]) -> None:
        await self._tool.load_state_json(state)

    async def run(self, args: BaseModel, cancellation_token: CancellationToken) -> Any:
        return await self.run_json(args.model_dump(), cancellation_token)

    async def run_json(
        self,
        args: Mapping[str, Any],
        cancellation_token: CancellationToken,
        call_id: str | None = None,
    ) -> Any:
        result = await self._guardrail.evaluate(
            tool_name=self._tool.name,
            args=args,
            agent_name=self._agent_name,
            call_id=call_id,
            cancellation_token=cancellation_token,
        )
        _validate_result(result)
        if result.decision is Decision.DENY:
            return f"{_DENY_PREFIX}: {result.reason or 'policy violation'}"
        effective = args
        if result.decision is Decision.MODIFY and result.modified_args is not None:
            effective = result.modified_args
        return await self._tool.run_json(effective, cancellation_token, call_id)


class GuardedWorkbench(Workbench):
    """Guard workbench calls and delegate its lifecycle and runtime state."""

    def __init__(
        self,
        workbench: Any,
        guardrail: GuardrailProvider,
        *,
        agent_name: str | None = None,
    ) -> None:
        self._workbench = workbench
        self._guardrail = guardrail
        self._agent_name = agent_name

    async def list_tools(self):
        return await self._workbench.list_tools()

    async def start(self) -> None:
        await self._workbench.start()

    async def stop(self) -> None:
        await self._workbench.stop()

    async def reset(self) -> None:
        await self._workbench.reset()

    async def save_state(self):
        return await self._workbench.save_state()

    async def load_state(self, state: Mapping[str, Any]) -> None:
        await self._workbench.load_state(state)

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        cancellation_token: CancellationToken | None = None,
        call_id: str | None = None,
    ) -> ToolResult:
        try:
            args = dict(arguments or {})
            result = await self._guardrail.evaluate(
                tool_name=name,
                args=args,
                agent_name=self._agent_name,
                call_id=call_id,
                cancellation_token=cancellation_token,
            )
            _validate_result(result)
            if result.decision is Decision.DENY:
                reason = result.reason or "policy violation"
                return ToolResult(
                    name=name,
                    result=[TextResultContent(content=f"{_DENY_PREFIX}: {reason}")],
                    is_error=True,
                )
            effective = args
            if result.decision is Decision.MODIFY and result.modified_args is not None:
                effective = dict(result.modified_args)
            return await self._workbench.call_tool(name, effective, cancellation_token, call_id)
        except Exception:
            return ToolResult(
                name=name,
                result=[TextResultContent(content="Guarded tool call failed")],
                is_error=True,
            )


def attach(
    target: Any,
    guardrail: GuardrailProvider,
    *,
    agent_name: str | None = None,
) -> Any:
    """Wrap a BaseTool or Workbench so its calls route through the guardrail.

    Returns a GuardedWorkbench when target exposes call_tool, else a GuardedTool
    when it exposes run_json. Raises TypeError for anything else.
    """
    if hasattr(target, "call_tool"):
        return GuardedWorkbench(target, guardrail, agent_name=agent_name)
    if hasattr(target, "run_json"):
        return GuardedTool(target, guardrail, agent_name=agent_name)
    raise TypeError(
        "attach() expects an autogen BaseTool (run_json) or Workbench (call_tool), "
        f"got {type(target).__name__}"
    )
