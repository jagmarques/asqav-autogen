"""attach(): route an AutoGen tool or workbench call through a GuardrailProvider.

Wraps BaseTool.run_json or Workbench.call_tool in an explicit proxy class. No
autogen internals are patched. On DENY the underlying tool never runs, on
MODIFY it runs with the rewritten args, and on ALLOW it runs unchanged.
"""

from __future__ import annotations

from typing import Any, Mapping

from autogen_core import CancellationToken
from autogen_core.tools import TextResultContent, ToolResult

from .protocol import Decision, GuardrailProvider

__all__ = ["attach", "GuardedTool", "GuardedWorkbench"]

_DENY_PREFIX = "Tool call denied by asqav guardrail"


class GuardedTool:
    """Proxy over a BaseTool that guards run_json. All else delegates."""

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

    def __getattr__(self, name: str) -> Any:
        # Transparent proxy: name, description, schema, state, and the rest of
        # the tool surface come straight from the wrapped tool.
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._tool, name)

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
        if result.decision is Decision.DENY:
            return f"{_DENY_PREFIX}: {result.reason or 'policy violation'}"
        effective = args
        if result.decision is Decision.MODIFY and result.modified_args is not None:
            effective = result.modified_args
        return await self._tool.run_json(effective, cancellation_token, call_id)


class GuardedWorkbench:
    """Proxy over a Workbench that guards call_tool. All else delegates."""

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

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        return getattr(self._workbench, name)

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        cancellation_token: CancellationToken | None = None,
        call_id: str | None = None,
    ) -> ToolResult:
        args = dict(arguments or {})
        result = await self._guardrail.evaluate(
            tool_name=name,
            args=args,
            agent_name=self._agent_name,
            call_id=call_id,
            cancellation_token=cancellation_token,
        )
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
