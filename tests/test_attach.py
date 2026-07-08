"""attach(): DENY blocks execution, ALLOW passes through, MODIFY rewrites args."""

from __future__ import annotations

import pytest
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool, TextResultContent, ToolResult

from asqav_autogen import (
    AsqavGuardrail,
    Decision,
    GuardedTool,
    GuardedWorkbench,
    PolicyVerdict,
    attach,
)


class FakeWorkbench:
    """Minimal duck-typed Workbench: records calls, returns a ToolResult."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, name, arguments=None, cancellation_token=None, call_id=None):
        self.calls.append((name, dict(arguments or {})))
        return ToolResult(name=name, result=[TextResultContent(content="ok")], is_error=False)


async def test_attach_tool_allow_executes_and_signs(fake_agent):
    seen = []

    def echo(city: str) -> str:
        seen.append(city)
        return f"weather:{city}"

    tool = attach(FunctionTool(echo, description="echo", name="echo"), AsqavGuardrail())
    out = await tool.run_json({"city": "Lisbon"}, CancellationToken())

    assert "Lisbon" in str(out)  # underlying tool ran
    assert seen == ["Lisbon"]
    fake_agent.sign.assert_called_once()  # and the call was signed


async def test_attach_tool_deny_blocks_execution(fake_agent):
    seen = []

    def echo(city: str) -> str:
        seen.append(city)
        return f"weather:{city}"

    guard = AsqavGuardrail(denied_tools={"echo"})
    tool = attach(FunctionTool(echo, description="echo", name="echo"), guard)
    out = await tool.run_json({"city": "Lisbon"}, CancellationToken())

    assert "denied" in str(out).lower()
    assert seen == []  # underlying tool NEVER ran


async def test_attach_tool_modify_rewrites_args(fake_agent):
    seen = {}

    def echo(city: str) -> str:
        seen["city"] = city
        return f"weather:{city}"

    def policy(tool_name, args):
        return PolicyVerdict(Decision.MODIFY, "normalized", {"city": "Porto"})

    guard = AsqavGuardrail(policy=policy)
    tool = attach(FunctionTool(echo, description="echo", name="echo"), guard)
    out = await tool.run_json({"city": "lisbon"}, CancellationToken())

    assert seen["city"] == "Porto"  # tool received the rewritten args
    assert "Porto" in str(out)


async def test_attach_workbench_allow_calls_underlying(fake_agent):
    wb = FakeWorkbench()
    guarded = attach(wb, AsqavGuardrail())

    assert isinstance(guarded, GuardedWorkbench)
    res = await guarded.call_tool("search", {"q": "x"}, CancellationToken())

    assert res.is_error is False
    assert wb.calls == [("search", {"q": "x"})]


async def test_attach_workbench_deny_returns_error_toolresult(fake_agent):
    wb = FakeWorkbench()
    guarded = attach(wb, AsqavGuardrail(denied_tools={"search"}))
    res = await guarded.call_tool("search", {"q": "x"}, CancellationToken())

    assert isinstance(res, ToolResult)
    assert res.is_error is True
    assert wb.calls == []  # underlying workbench never called


def test_attach_rejects_unknown_target(fake_agent):
    with pytest.raises(TypeError):
        attach(object(), AsqavGuardrail())


def test_guarded_tool_delegates_name(fake_agent):
    def echo(city: str) -> str:
        return city

    guarded = attach(FunctionTool(echo, description="d", name="echo"), AsqavGuardrail())
    assert isinstance(guarded, GuardedTool)
    assert guarded.name == "echo"  # proxied from the underlying tool
