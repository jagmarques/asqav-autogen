"""Protocol conformance and the exact shape from microsoft/autogen#7405."""

from __future__ import annotations

import pytest

from asqav_autogen import AsqavGuardrail, Decision, GuardrailProvider, GuardrailResult


def test_decision_enum_matches_proposal():
    assert Decision.ALLOW.value == "allow"
    assert Decision.DENY.value == "deny"
    assert Decision.MODIFY.value == "modify"


def test_guardrail_result_defaults():
    r = GuardrailResult(decision=Decision.ALLOW)
    assert r.reason is None
    assert r.modified_args is None
    assert r.metadata == {}


def test_asqav_guardrail_is_runtime_checkable_provider(fake_agent):
    provider = AsqavGuardrail()
    assert isinstance(provider, GuardrailProvider)


def test_plain_object_with_async_evaluate_satisfies_protocol():
    class Custom:
        async def evaluate(
            self, *, tool_name, args, agent_name=None, call_id=None, cancellation_token=None
        ):
            return GuardrailResult(decision=Decision.ALLOW)

    assert isinstance(Custom(), GuardrailProvider)


def test_object_without_evaluate_is_not_a_provider():
    assert not isinstance(object(), GuardrailProvider)


def test_evaluate_is_keyword_only(fake_agent):
    # The proposal makes evaluate() keyword-only, so positional args are rejected
    # before a coroutine is even created.
    g = AsqavGuardrail()
    with pytest.raises(TypeError):
        g.evaluate("search", {"q": "x"})
