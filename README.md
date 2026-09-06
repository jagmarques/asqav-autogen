# Asqav tool guardrails for AutoGen

This package evaluates tool requests with a local policy and attempts to record each decision through [Asqav](https://asqav.com). Attach a guard to an AutoGen tool or workbench before passing it to `AssistantAgent`. A denied request stops at the attachment; an allowed request reaches the wrapped tool.

Asqav maintains this integration. Signing uses an Asqav API key and the Asqav service. The package does not verify receipt signatures or prove that an allowed tool completed.

## Install

Install the source:

```bash
python -m pip install "asqav-autogen @ git+https://github.com/jagmarques/asqav-autogen.git" "autogen-agentchat>=0.7.5,<0.8"
```

The package requires AutoGen Core 0.7.5 through the 0.7 series and Asqav SDK 0.10.10 through the 0.10 series. The consumer tests exercise AutoGen Core and AgentChat 0.7.5 with SDK 0.10.10. The policy types belong to this package; they do not depend on adoption of an upstream proposal.

## Attach a tool

Configure `ASQAV_API_KEY` in the application environment. Supply your configured AutoGen model client as `model_client`:

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_core.tools import FunctionTool
from asqav_autogen import AsqavGuardrail, attach

def get_weather(city: str) -> str:
    """Return a local example response."""
    return f"Weather in {city}: sunny"

guard = AsqavGuardrail(agent_name="weather-agent", denied_tools={"shell"})
tool = attach(FunctionTool(get_weather, description="Example weather"), guard)
agent = AssistantAgent("weather_agent", model_client=model_client, tools=[tool])
result = await agent.run(task="Get the weather in Lisbon")
```

For direct tool execution, see [examples/quickstart.py](examples/quickstart.py). That example calls the Asqav API and prints a local weather fixture, not a weather service response.

For a workbench, pass `workbench=attach(my_workbench, guard)` to `AssistantAgent` instead of `tools`. The wrapper delegates listing, start/stop/reset and runtime state. Its asynchronous context manager returns the guarded wrapper. Tool wrappers preserve schemas, argument/return types, return formatting and JSON runtime state.

Attachments expose guarded non-streaming calls. Streaming tools use their ordinary `run_json` path; streaming-only operations are not forwarded. Configuration export with `dump_component()` raises `NotImplementedError`: a policy callback cannot be reconstructed from an unguarded tool configuration. Restore runtime state into an attachment that your application has already configured.

## Choose the policy

A matching denylist entry takes precedence. Otherwise, a custom policy returns `PolicyVerdict`; without a custom policy the default is `ALLOW`.

```python
from asqav_autogen import AsqavGuardrail, Decision, PolicyVerdict

def policy(tool_name, args):
    if tool_name == "search":
        return PolicyVerdict(Decision.MODIFY, "capped limit", {**args, "limit": 100})
    return PolicyVerdict(Decision.ALLOW)

guard = AsqavGuardrail(agent_name="search-agent", policy=policy)
```

`ALLOW` passes the input mapping through. `DENY` returns a denial message without calling the wrapped tool; a workbench denial has `is_error=True`. `MODIFY` passes the replacement mapping to the tool for validation; when `modified_args` is `None`, it uses the original mapping. A deny in the signing response overrides a local allow or modification.

Provider exceptions and malformed results stop execution; AutoGen reports them as tool errors in the tested agent path. The cancellation token and call identifier pass to the provider and tool. When cancelling an AutoGen agent run, cancel the outer `agent.run()` task as well as its token: the tested host can otherwise wait on its result queue after a cancelled tool. Cancellation cannot undo a synchronous signing request already running in the SDK's worker thread or a tool's completed side effects.

## Signing and data handling

A successful signing request adds `receipt_id` to `GuardrailResult.metadata`. `last_receipt_id` identifies the most recent successful response, so it can refer to another call after a signing failure. Signing failure normally returns `DENY`; `fail_closed=False` retains the local policy result without a receipt. `observe=True` skips signing while retaining local policy decisions. Provider construction can still create or fetch an Asqav agent in observation mode. The SDK may retry retryable HTTP failures.

The provider computes `hash_action("tool:args", {"args": mapping})` for the selected argument mapping. Modification also computes an original-argument digest. These digests enter signing context with the tool name, agent name, call identifier and decision. Non-serializable arguments can produce a `None` digest. Tool validation, coercion and execution happen afterwards; the package does not establish that a receipt commits the final executed argument bytes.

Set `ASQAV_MODE=full-payload` to send that selected context, or `ASQAV_MODE=hash-only` to hash the context locally. Raw argument mappings are not placed in signing context. The SDK can still send identifiers, policy decision and reason separately; a custom reason may contain sensitive input. Other AutoGen components and model clients have their own data handling. The integration does not independently validate what the service retains in a receipt.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

The consumer regression uses actual `AssistantAgent`, `FunctionTool`, workbenches and the released SDK. AutoGen's replay model and intercepted HTTP responses provide deterministic local replies, and sockets are prohibited. It checks tool execution counts, denial, modification, error handling, cancellation, runtime state and configuration boundaries. These checks do not call a model or production service and do not prove cryptographic receipt validity. A separate live test requires `ASQAV_API_KEY` and is skipped without it.

## License

[Elastic License 2.0](LICENSE).
