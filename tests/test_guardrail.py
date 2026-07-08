"""AsqavGuardrail.evaluate() branch coverage, all network-free."""

from __future__ import annotations

from asqav.canonicalize import hash_action

from asqav_autogen import AsqavGuardrail, Decision, PolicyVerdict


async def test_default_allow_signs_and_returns_receipt(fake_agent):
    g = AsqavGuardrail()
    r = await g.evaluate(tool_name="search", args={"q": "cats"})

    assert r.decision is Decision.ALLOW
    assert r.metadata["receipt_id"] == "sig_test123"
    assert r.metadata["policy_decision"] == "permit"
    fake_agent.sign.assert_called_once()
    assert fake_agent.sign.call_args.args[0] == "tool:authorize"
    assert fake_agent.sign.call_args.kwargs["tool_name"] == "search"
    assert fake_agent.sign.call_args.kwargs["policy_decision"] == "permit"


async def test_denylist_denies_but_still_signs(fake_agent):
    g = AsqavGuardrail(denied_tools={"shell"})
    r = await g.evaluate(tool_name="shell", args={"cmd": "rm -rf /"})

    assert r.decision is Decision.DENY
    assert "denied by denylist" in r.reason
    # the deny path MUST still record a receipt (chain of evidence)
    assert r.metadata["receipt_id"] == "sig_test123"
    assert r.metadata["policy_decision"] == "deny"
    assert fake_agent.sign.call_args.kwargs["policy_decision"] == "deny"


async def test_asqav_side_deny_overrides_local_allow(fake_agent, sign_factory):
    fake_agent.sign.return_value = sign_factory(
        signature_id="sig_d", policy_decision="deny", decision="deny"
    )
    g = AsqavGuardrail()  # local default is allow
    r = await g.evaluate(tool_name="wire_transfer", args={})

    assert r.decision is Decision.DENY
    assert r.metadata["receipt_id"] == "sig_d"
    assert r.metadata["policy_decision"] == "deny"


async def test_policy_modify_returns_modified_args(fake_agent):
    def policy(tool_name, args):
        return PolicyVerdict(Decision.MODIFY, "normalized city", {"city": "Porto"})

    g = AsqavGuardrail(policy=policy)
    r = await g.evaluate(tool_name="weather", args={"city": "lisbon"})

    assert r.decision is Decision.MODIFY
    assert r.modified_args == {"city": "Porto"}
    assert r.reason == "normalized city"


async def test_modify_signs_the_rewritten_args_digest(fake_agent):
    def policy(tool_name, args):
        return PolicyVerdict(Decision.MODIFY, "capped", {"limit": 100})

    g = AsqavGuardrail(policy=policy)
    r = await g.evaluate(tool_name="search", args={"limit": 999999})

    # the signed digest binds the rewritten payload, not the original
    expected = hash_action("tool:args", {"args": {"limit": 100}})
    original = hash_action("tool:args", {"args": {"limit": 999999}})
    signed_context = fake_agent.sign.call_args.args[1]
    assert signed_context["args_digest"] == expected
    assert r.metadata["args_digest"] == expected
    assert r.metadata["original_args_digest"] == original
    assert expected != original


async def test_fail_closed_on_sign_error(fake_agent):
    fake_agent.sign.side_effect = RuntimeError("503 service unavailable")
    g = AsqavGuardrail(fail_closed=True)
    r = await g.evaluate(tool_name="search", args={"q": "x"})

    assert r.decision is Decision.DENY
    assert r.metadata["fail_closed"] is True
    assert r.metadata["receipt_id"] is None


async def test_fail_open_on_sign_error(fake_agent):
    fake_agent.sign.side_effect = RuntimeError("timeout")
    g = AsqavGuardrail(fail_closed=False)
    r = await g.evaluate(tool_name="search", args={"q": "x"})

    # default policy is allow, so fail-open lets it through with no receipt
    assert r.decision is Decision.ALLOW
    assert r.metadata["receipt_id"] is None


async def test_observe_mode_does_not_sign(fake_agent):
    g = AsqavGuardrail(observe=True)
    r = await g.evaluate(tool_name="search", args={"q": "x"})

    assert r.decision is Decision.ALLOW
    assert r.metadata["receipt_id"] is None
    fake_agent.sign.assert_not_called()


async def test_custom_policy_deny(fake_agent):
    def policy(tool_name, args):
        return PolicyVerdict(Decision.DENY, "blocked: regulated tool")

    g = AsqavGuardrail(policy=policy)
    r = await g.evaluate(tool_name="wire_transfer", args={})

    assert r.decision is Decision.DENY
    assert r.reason == "blocked: regulated tool"
    assert r.metadata["policy_decision"] == "deny"


async def test_last_receipt_id_property(fake_agent):
    g = AsqavGuardrail()
    assert g.last_receipt_id is None
    await g.evaluate(tool_name="search", args={"q": "x"})
    assert g.last_receipt_id == "sig_test123"
