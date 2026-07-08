"""AsqavGuardrail: a GuardrailProvider backed by asqav signed receipts.

Every evaluate() records the tool-call decision as an asqav receipt. Allow,
deny, and modify each produce a receipt, and the receipt id comes back in
GuardrailResult.metadata. See microsoft/autogen#7405 for the protocol.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from asqav.canonicalize import hash_action
from asqav.extras._base import AsqavAdapter
from autogen_core import CancellationToken

from .protocol import Decision, GuardrailResult

logger = logging.getLogger("asqav")

__all__ = ["AsqavGuardrail", "PolicyVerdict", "PolicyFn"]

_AUTHORIZE_ACTION_TYPE = "tool:authorize"
_ARGS_DIGEST_ACTION = "tool:args"


@dataclass
class PolicyVerdict:
    """A client-side policy outcome for one tool call."""

    decision: Decision
    reason: str | None = None
    modified_args: Mapping[str, Any] | None = None


# (tool_name, args) -> PolicyVerdict. The callback owns the local decision,
# asqav owns the signed receipt for whatever it decides.
PolicyFn = Callable[[str, Mapping[str, Any]], PolicyVerdict]


def _args_digest(args: Mapping[str, Any]) -> str | None:
    """sha256 over JCS-canonical args, or None when args are not serializable."""
    try:
        return hash_action(_ARGS_DIGEST_ACTION, {"args": dict(args)})
    except (TypeError, ValueError):
        return None


class AsqavGuardrail(AsqavAdapter):
    """GuardrailProvider that signs every guarded tool call through asqav.

    On evaluate() the guardrail computes a local verdict (a denylist, an
    optional policy callback, or allow-by-default), signs that verdict as an
    asqav receipt, and lets an asqav deny override to block. The receipt id
    travels back in GuardrailResult.metadata, so "who authorized this tool
    call and when" is answerable from a tamper-evident record.

    asqav allow maps to ALLOW, asqav deny maps to DENY. A policy callback may
    return MODIFY with rewritten args, and the rewritten args are the payload
    that gets signed, so the receipt binds the args that actually run.
    """

    def __init__(
        self,
        *,
        policy: PolicyFn | None = None,
        denied_tools: "set[str] | list[str] | None" = None,
        fail_closed: bool = True,
        action_type: str = _AUTHORIZE_ACTION_TYPE,
        **adapter_kwargs: Any,
    ) -> None:
        super().__init__(**adapter_kwargs)
        self._policy = policy
        self._denied: set[str] = set(denied_tools or ())
        self._fail_closed = fail_closed
        self._action_type = action_type

    @property
    def last_receipt_id(self) -> str | None:
        """signature_id of the most recent asqav receipt, or None."""
        if not self._signatures:
            return None
        return getattr(self._signatures[-1], "signature_id", None)

    def _local_verdict(self, tool_name: str, args: Mapping[str, Any]) -> PolicyVerdict:
        if tool_name in self._denied:
            return PolicyVerdict(Decision.DENY, f"denied by denylist: {tool_name}")
        if self._policy is not None:
            return self._policy(tool_name, args)
        return PolicyVerdict(Decision.ALLOW, "default-allow")

    async def evaluate(
        self,
        *,
        tool_name: str,
        args: Mapping[str, Any],
        agent_name: str | None = None,
        call_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> GuardrailResult:
        """Authorize one tool call and record the verdict as an asqav receipt."""
        verdict = self._local_verdict(tool_name, args)

        # MODIFY rebinds the payload: the rewritten args are what we sign and run.
        effective_args: Mapping[str, Any] = args
        if verdict.decision is Decision.MODIFY and verdict.modified_args is not None:
            effective_args = verdict.modified_args

        digest = _args_digest(effective_args)
        context: dict[str, Any] = {
            "tool": tool_name,
            "agent": agent_name,
            "call_id": call_id,
            "decision": verdict.decision.value,
            "args_digest": digest,
        }
        metadata: dict[str, Any] = {"policy_decision": "permit", "args_digest": digest}
        if verdict.decision is Decision.MODIFY:
            original = _args_digest(args)
            context["original_args_digest"] = original
            metadata["original_args_digest"] = original

        policy_decision = "deny" if verdict.decision is Decision.DENY else "permit"
        metadata["policy_decision"] = policy_decision

        sig = None
        if not self._observe:
            try:
                sig = await asyncio.to_thread(
                    self._agent.sign,
                    self._action_type,
                    context,
                    tool_name=tool_name,
                    policy_decision=policy_decision,
                    reason=verdict.reason,
                )
                self._signatures.append(sig)
            except Exception as exc:
                # asqav is the evidence layer. No receipt means no proof, so
                # fail closed by default: deny rather than act without a record.
                logger.warning("asqav sign failed: %s", exc)
                if self._fail_closed:
                    return GuardrailResult(
                        decision=Decision.DENY,
                        reason=f"asqav unreachable: {exc}",
                        metadata={**metadata, "fail_closed": True, "receipt_id": None},
                    )
        else:
            logger.info(
                "OBSERVE: would sign %s decision=%s tool=%s",
                self._action_type,
                verdict.decision.value,
                tool_name,
            )

        metadata["receipt_id"] = getattr(sig, "signature_id", None)

        # asqav governance can override an allow or modify to deny. Deny wins.
        asqav_denied = sig is not None and (
            getattr(sig, "policy_decision", "permit") == "deny"
            or getattr(sig, "decision", None) == "deny"
        )
        if asqav_denied:
            metadata["policy_decision"] = "deny"
            return GuardrailResult(
                decision=Decision.DENY,
                reason=verdict.reason or "denied by asqav policy",
                metadata=metadata,
            )

        if verdict.decision is Decision.DENY:
            return GuardrailResult(Decision.DENY, verdict.reason, metadata=metadata)
        if verdict.decision is Decision.MODIFY:
            return GuardrailResult(
                Decision.MODIFY,
                verdict.reason,
                modified_args=effective_args,
                metadata=metadata,
            )
        return GuardrailResult(Decision.ALLOW, verdict.reason, metadata=metadata)
