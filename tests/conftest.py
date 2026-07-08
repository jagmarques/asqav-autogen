"""Shared fixtures. Patches the asqav client so tests run network-free."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import asqav.client
import pytest

# Make examples/quickstart.py importable for the quickstart test.
_EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))


def make_signature(
    signature_id: str = "sig_test123",
    policy_decision: str = "permit",
    decision: str | None = None,
) -> SimpleNamespace:
    """Stand-in for asqav SignatureResponse with the fields the guardrail reads."""
    return SimpleNamespace(
        signature_id=signature_id,
        policy_decision=policy_decision,
        decision=decision,
        action_id="act_test",
        verification_url="https://verify.asqav.com/act_test",
    )


@pytest.fixture
def fake_agent(monkeypatch):
    """Init the asqav client with a fake key and a mock agent whose sign is a mock."""
    monkeypatch.setattr(asqav.client, "_api_key", "sk_test_client", raising=False)
    agent = MagicMock()
    agent.agent_id = "ag_test"
    agent.name = "asqav-autogen"
    agent.sign = MagicMock(return_value=make_signature())
    monkeypatch.setattr(asqav.client.Agent, "create", lambda *a, **kw: agent)
    return agent


@pytest.fixture
def sign_factory():
    """Return the SignatureResponse stand-in builder for custom-response tests."""
    return make_signature
