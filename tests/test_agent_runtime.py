"""Actual AutoGen consumers and SDK requests; model/HTTP replies are local fixtures."""

import asyncio
import json
import socket

import asqav
import httpx
import pytest
from asqav.canonicalize import hash_action
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import ToolCallExecutionEvent
from autogen_core import CancellationToken, FunctionCall
from autogen_core.models import CreateResult, RequestUsage
from autogen_core.tools import (
    BaseTool,
    FunctionTool,
    StaticStreamWorkbench,
    StaticWorkbench,
    StreamTool,
    Workbench,
)
from autogen_ext.models.replay import ReplayChatCompletionClient
from pydantic import BaseModel

from asqav_autogen import AsqavGuardrail, Decision, GuardrailResult, PolicyVerdict, attach


@pytest.fixture
def transport(monkeypatch):
    import asqav.client as sdk

    state = {"requests": [], "error": False, "deny": False}

    def blocked(*args, **kwargs):
        raise AssertionError("Network forbidden in runtime tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setenv("ASQAV_MODE", "full-payload")
    monkeypatch.setattr(sdk, "_api_base", "https://api.asqav.com/api/v1")

    def send(client, request, **kwargs):
        assert request.url.host == "api.asqav.com"
        body = json.loads(request.content)
        if request.url.path == "/api/v1/agents/create":
            data = dict(
                agent_id="agent_test",
                name=body["name"],
                public_key="fixture",
                key_id="fixture",
                algorithm="ml-dsa-65",
                capabilities=[],
                created_at=0,
            )
        else:
            assert request.url.path == "/api/v1/agents/agent_test/sign"
            state["requests"].append(body)
            if state["error"]:
                return httpx.Response(403, json={"detail": "local refusal"}, request=request)
            data = dict(
                signature="fixture",
                signature_id="sig_test",
                action_id="action_test",
                timestamp=0,
                verification_url="https://example.invalid/test",
                policy_decision="deny" if state["deny"] else body["policy_decision"],
            )
        return httpx.Response(200, json=data, request=request)

    monkeypatch.setattr(httpx.Client, "send", send)
    asqav.init(api_key="test-only-key")
    yield state
    if sdk._client is not None:
        sdk._client.close()


def agent_for(target, workbench=False, arguments='{"city":"Lisbon"}'):
    model = ReplayChatCompletionClient(
        [
            CreateResult(
                finish_reason="function_calls",
                content=[FunctionCall(id="call_test", name="echo", arguments=arguments)],
                usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
                cached=False,
            )
        ],
        model_info={
            "vision": False,
            "function_calling": True,
            "json_output": False,
            "family": "unknown",
            "structured_output": False,
        },
    )
    return AssistantAgent(
        "local_agent",
        model_client=model,
        reflect_on_tool_use=False,
        **({"workbench": target} if workbench else {"tools": [target]}),
    )


def echo_tool(seen):
    async def echo(city: str, cancellation_token: CancellationToken) -> str:
        seen.append((city, cancellation_token))
        return "weather:" + city

    return FunctionTool(echo, description="Local echo", name="echo", strict=True)


@pytest.mark.parametrize("workbench", [False, True])
@pytest.mark.parametrize("path", ["allow", "deny", "modify", "server_deny", "failure", "open"])
async def test_actual_agent_dispatch(transport, workbench, path):
    seen = []
    transport["error"] = path in {"failure", "open"}
    transport["deny"] = path == "server_deny"
    decision = {"deny": Decision.DENY, "modify": Decision.MODIFY}.get(path, Decision.ALLOW)
    guard = AsqavGuardrail(
        policy=lambda *_: PolicyVerdict(
            decision, "local policy", {"city": "Porto"} if path == "modify" else None
        ),
        fail_closed=path != "open",
    )
    raw = echo_tool(seen)
    target = attach(StaticWorkbench([raw]) if workbench else raw, guard, agent_name="local_agent")
    token = CancellationToken()
    result = await asyncio.wait_for(
        agent_for(target, workbench).run(task="Echo Lisbon", cancellation_token=token), timeout=5
    )
    assert isinstance(target, Workbench if workbench else BaseTool)
    allowed = path in {"allow", "modify", "open"}
    assert seen == ([("Porto" if path == "modify" else "Lisbon", token)] if allowed else [])
    execution = next(m.content[0] for m in result.messages if isinstance(m, ToolCallExecutionEvent))
    assert ("weather:" if allowed else "denied") in execution.content
    assert execution.call_id == "call_test"
    (body,) = transport["requests"]
    assert body["action_type"] == "tool:authorize"
    context = body["context"]
    assert context["call_id"] == "call_test" and context["agent"] == "local_agent"
    assert context["args_digest"] == hash_action(
        "tool:args", {"args": {"city": "Porto" if path == "modify" else "Lisbon"}}
    )
    assert "Lisbon" not in json.dumps(body) and "Porto" not in json.dumps(body)
    assert guard.last_receipt_id == (None if transport["error"] else "sig_test")


@pytest.mark.parametrize("workbench", [False, True])
@pytest.mark.parametrize(
    "bad", ["type", "decision", "raise", "arguments", "modified_type", "reason"]
)
async def test_bad_provider_or_arguments_never_execute(transport, workbench, bad):
    class Provider:
        async def evaluate(self, **kwargs):
            if bad == "raise":
                raise RuntimeError("local provider failure")
            if bad == "type":
                return None
            if bad == "decision":
                return GuardrailResult("deny")
            if bad == "modified_type":
                return GuardrailResult(Decision.MODIFY, modified_args=object())
            if bad == "reason":

                class Unprintable:
                    def __str__(self):
                        raise RuntimeError("reason formatting failed")

                return GuardrailResult(Decision.DENY, reason=Unprintable())
            return GuardrailResult(Decision.MODIFY, modified_args={"wrong": "input"})

    seen = []
    raw = echo_tool(seen)
    target = attach(StaticWorkbench([raw]) if workbench else raw, Provider())
    result = await asyncio.wait_for(agent_for(target, workbench).run(task="Echo Lisbon"), timeout=5)
    execution = next(m.content[0] for m in result.messages if isinstance(m, ToolCallExecutionEvent))
    assert execution.is_error and seen == [] and transport["requests"] == []


class City(BaseModel):
    city: str


class StatefulTool(BaseTool):
    def __init__(self):
        super().__init__(City, str, "echo", "Stateful echo", strict=True)
        self.calls = []

    async def run(self, args, cancellation_token):
        self.calls.append((args.city, cancellation_token))
        return args.city

    def return_value_as_string(self, value):
        return "formatted:" + value

    async def save_state_json(self):
        return {"cities": [city for city, _ in self.calls]}

    async def load_state_json(self, state):
        self.calls = [(city, None) for city in state["cities"]]


@pytest.mark.parametrize("workbench", [False, True])
async def test_public_state_lifecycle_and_config(transport, workbench):
    raw = StatefulTool()
    guard = AsqavGuardrail(observe=True)
    target = attach(StaticWorkbench([raw]) if workbench else raw, guard)
    if workbench:
        async with target as entered:
            assert entered is target
            assert await target.list_tools() == [raw.schema]
            await target.call_tool("echo", {"city": "Lisbon"})
            state = await target.save_state()
            await target.reset()
            raw.calls.clear()
            await target.load_state(state)
    else:
        assert target.name == raw.name and target.description == raw.description
        assert target.schema == raw.schema
        assert target.args_type() is City and target.return_type() is str
        assert target.state_type() == raw.state_type()
        assert target.return_value_as_string("Lisbon") == "formatted:Lisbon"
        assert await target.run(City(city="Lisbon"), CancellationToken()) == "Lisbon"
        state = await target.save_state_json()
        raw.calls.clear()
        await target.load_state_json(state)
    assert raw.calls == [("Lisbon", None)]
    with pytest.raises(NotImplementedError, match="dumping to config"):
        target.dump_component()


@pytest.mark.parametrize("workbench", [False, True])
@pytest.mark.parametrize("through_agent", [False, True])
async def test_cancellation_propagates_without_tool_execution(transport, workbench, through_agent):
    entered = asyncio.Event()

    class WaitingGuard:
        async def evaluate(self, **kwargs):
            token = kwargs["cancellation_token"]
            assert kwargs["call_id"] == "call_test"
            future = asyncio.get_running_loop().create_future()
            token.link_future(future)
            entered.set()
            await future

    seen = []
    raw = echo_tool(seen)
    target = attach(StaticWorkbench([raw]) if workbench else raw, WaitingGuard())
    token = CancellationToken()
    if through_agent:
        call = agent_for(target, workbench).run(task="Echo", cancellation_token=token)
    elif workbench:
        call = target.call_tool("echo", {"city": "Lisbon"}, token, "call_test")
    else:
        call = target.run_json({"city": "Lisbon"}, token, "call_test")
    task = asyncio.create_task(call)
    await asyncio.wait_for(entered.wait(), timeout=2)
    token.cancel()
    if through_agent:
        # AutoGen's result queue needs its consumer cancelled as well.
        task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert seen == []


async def test_stream_capability_cannot_bypass_guard(transport):
    class StreamingTool(StatefulTool):
        async def run_json_stream(self, args, cancellation_token, call_id=None):
            self.calls.append(("unguarded stream", cancellation_token))
            yield "unguarded stream"

    raw = StreamingTool()
    assert isinstance(raw, StreamTool)
    guarded = attach(raw, AsqavGuardrail(denied_tools={"echo"}, observe=True))
    assert not isinstance(guarded, StreamTool)
    results = [
        r
        async for r in StaticStreamWorkbench([guarded]).call_tool_stream("echo", {"city": "Lisbon"})
    ]
    assert len(results) == 1 and "denied" in results[0].to_text() and raw.calls == []


@pytest.mark.parametrize("mode", ["hash-only", "full-payload"])
async def test_sdk_request_mode_and_modify_digest(transport, monkeypatch, mode):
    monkeypatch.setenv("ASQAV_MODE", mode)
    asqav.init(api_key="test-only-key")
    guard = AsqavGuardrail(
        policy=lambda *_: PolicyVerdict(Decision.MODIFY, "local reason", {"city": "Porto"})
    )
    result = await guard.evaluate(tool_name="echo", args={"city": "Lisbon"}, call_id="call_test")
    (body,) = transport["requests"]
    context = {
        "tool": "echo",
        "agent": None,
        "call_id": "call_test",
        "decision": "modify",
        "args_digest": hash_action("tool:args", {"args": {"city": "Porto"}}),
        "original_args_digest": hash_action("tool:args", {"args": {"city": "Lisbon"}}),
        "_tool_name": "echo",
    }
    if mode == "full-payload":
        assert body["context"] == context
    else:
        assert "context" not in body
        assert body["hash"] == hash_action("tool:authorize", context)
    assert body["reason"] == "local reason" and result.metadata["receipt_id"] == "sig_test"


@pytest.mark.parametrize("path", ["direct", "workbench", "agent_tools", "agent_workbench"])
@pytest.mark.parametrize("arguments", [[], "", 0, False, [["city", "Lisbon"]], [1], "x", 1, True])
async def test_object_input_precedes_provider_evaluation(transport, path, arguments):
    calls, evaluations = [], []

    async def echo(city: str = "default") -> str:
        calls.append(city)
        return city

    class ReplacingProvider:
        async def evaluate(self, **kwargs):
            evaluations.append(kwargs["args"])
            return GuardrailResult(Decision.MODIFY, modified_args={"city": "Porto"})

    workbench = path in {"workbench", "agent_workbench"}
    raw = FunctionTool(echo, description="Object input control")
    target = attach(StaticWorkbench([raw]) if workbench else raw, ReplacingProvider())
    if path.startswith("agent"):
        response = await asyncio.wait_for(
            agent_for(target, workbench, json.dumps(arguments)).run(task="Echo"), 3
        )
        result = next(
            m.content[0] for m in response.messages if isinstance(m, ToolCallExecutionEvent)
        )
    elif workbench:
        result = await target.call_tool("echo", arguments)
    else:
        with pytest.raises(TypeError, match="arguments must be an object"):
            await target.run_json(arguments, CancellationToken())
    if path == "agent_tools" and not arguments:
        # The host erases falsey input types before calling an attached tool.
        assert evaluations == [{}] and calls == ["Porto"] and not result.is_error
    else:
        assert evaluations == [] and calls == []
        if path != "direct":
            assert result.is_error
    assert transport["requests"] == []


@pytest.mark.parametrize("path", ["direct", "workbench", "agent_tools", "agent_workbench"])
@pytest.mark.parametrize("arguments", [None, {}, {"city": "Porto"}])
async def test_empty_object_and_optional_workbench_arguments(transport, path, arguments):
    calls = []

    async def echo(city: str = "default") -> str:
        calls.append(city)
        return city

    workbench = path in {"workbench", "agent_workbench"}
    raw = FunctionTool(echo, description="Optional argument control")
    guard = AsqavGuardrail()
    target = attach(StaticWorkbench([raw]) if workbench else raw, guard)
    if path.startswith("agent"):
        await asyncio.wait_for(
            agent_for(target, workbench, json.dumps(arguments)).run(task="Echo"), 3
        )
    elif workbench:
        assert not (await target.call_tool("echo", arguments)).is_error
    elif arguments is None:
        with pytest.raises(TypeError, match="arguments must be an object"):
            await target.run_json(arguments, CancellationToken())
        assert calls == [] and transport["requests"] == []
        return
    else:
        await target.run_json(arguments, CancellationToken())
    assert calls == ["Porto" if arguments else "default"]
    assert len(transport["requests"]) == 1
