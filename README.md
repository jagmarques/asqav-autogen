<p align="center">
  <a href="https://asqav.com">
    <img src="https://asqav.com/logo-text-white.png" alt="Asqav" width="200">
  </a>
</p>
<p align="center">
  An AutoGen GuardrailProvider that signs every guarded tool call with asqav.
</p>
<p align="center">
  <a href="https://www.asqav.com/">Website</a> |
  <a href="https://www.asqav.com/docs">Docs</a> |
  <a href="https://github.com/jagmarques/asqav-sdk">SDK</a> |
  <a href="https://github.com/microsoft/autogen/issues/7405">autogen#7405</a>
</p>

# Asqav GuardrailProvider for AutoGen

This package implements the `GuardrailProvider` protocol proposed in
[microsoft/autogen#7405](https://github.com/microsoft/autogen/issues/7405). It
sits at the pre-execution point of a tool call, records the decision through
[asqav](https://asqav.com) as a cryptographic receipt, and returns the receipt
id with the verdict.

It is a standalone package. The protocol types ship here, so you do not need any
change to autogen to use it. When (or if) the protocol lands in `autogen-core`,
the shapes match and this stays a drop-in.

## Install

Not yet on PyPI. Install from GitHub:

```bash
pip install "asqav-autogen @ git+https://github.com/jagmarques/asqav-autogen.git"
```

This pulls in the `asqav` SDK and `autogen-core`.

## Quickstart

Five lines from import to a signed receipt for one guarded tool call:

```python
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool
from asqav_autogen import AsqavGuardrail, attach

guardrail = AsqavGuardrail(api_key="sk_...", agent_name="autogen-quickstart")
tool = attach(FunctionTool(get_weather, description="Get the weather"), guardrail)
result = await tool.run_json({"city": "Lisbon"}, CancellationToken())
print(guardrail.last_receipt_id)  # asqav receipt for that call
```

The full runnable version is in [`examples/quickstart.py`](examples/quickstart.py).
It reads `ASQAV_API_KEY` from the environment and signs against api.asqav.com.

## Digest binding

The design follows one rule from the autogen#7405 discussion: bind the receipt
to the arguments that actually run.

> If a guardrail rewrites the args, that is a new bound payload and it needs its
> own digest, otherwise the record you signed and the args that ran quietly
> diverge.

> The calls that cause pain later are the denied and the rewritten ones, not the
> clean executes. A record that only fires when a tool actually runs misses half
> of them.

So on a `MODIFY`, the guardrail signs the rewritten arguments, not the original.
The receipt carries the digest of the effective payload plus the digest of the
original, so a verifier can see the before and after. And every path signs,
including `DENY`, so a blocked call still leaves a record.

## Usage

`attach()` wraps a `BaseTool` (guarding `run_json`) or a `Workbench` (guarding
`call_tool`) in an explicit proxy. Autogen internals are never patched.

```python
from asqav_autogen import AsqavGuardrail, Decision, PolicyVerdict, attach

# Deny a small set of tools by name, allow the rest. Every decision is a receipt.
guardrail = AsqavGuardrail(agent_name="my-agents", denied_tools={"shell", "wire_transfer"})
guarded_tool = attach(my_tool, guardrail)
guarded_workbench = attach(my_workbench, guardrail)
```

Bring your own decision. Pass a `policy` callback and asqav signs whatever it
returns. Return `MODIFY` to sanitize arguments before they run:

```python
def policy(tool_name, args):
    if tool_name == "search":
        # cap an unbounded parameter, then let the call proceed
        return PolicyVerdict(Decision.MODIFY, "capped limit", {**args, "limit": min(args.get("limit", 100), 100)})
    return PolicyVerdict(Decision.ALLOW)

guardrail = AsqavGuardrail(agent_name="my-agents", policy=policy)
```

## Decision mapping

| asqav / policy | GuardrailResult | Effect on the tool |
|---|---|---|
| allow | `Decision.ALLOW` | runs with the original args, signed |
| deny | `Decision.DENY` | does not run, the deny is signed |
| modify | `Decision.MODIFY` | runs with the rewritten args, signed |

An asqav deny always wins. If the backend policy denies a call the local policy
allowed, the final decision is `DENY`.

## Fail-closed by default

If asqav is unreachable, the guardrail cannot produce a receipt for the
decision. By default it denies the call rather than act without a record:

```python
AsqavGuardrail(fail_closed=True)   # default: block on an asqav error
AsqavGuardrail(fail_closed=False)  # proceed and drop the receipt
```

## Standalone, no upstream change

The `Decision`, `GuardrailResult`, and `GuardrailProvider` types in this package
mirror the autogen#7405 proposal exactly. They are defined here, not imported
from autogen, so nothing upstream needs to move for this to work today.

## Data handling

`asqav-autogen` is a thin wrapper around the `asqav` Python SDK and inherits its
mode behavior. On asqav cloud the SDK hashes your tool arguments locally and
sends only the hash plus a small metadata bag, so raw arguments stay on your
side. Self-hosted asqav can take the full context for server-side policy and
richer audit views.

## Configuration

```python
# Use an existing asqav agent by id
AsqavGuardrail(agent_id="ag_abc123")

# Override the API key
AsqavGuardrail(api_key="sk_other", agent_name="authz-agents")

# Observe only: no receipts written, decisions still returned
AsqavGuardrail(observe=True)
```

## License

Elastic License 2.0 (ELv2). See [LICENSE](LICENSE).
