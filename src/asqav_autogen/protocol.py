"""Package-owned tool policy types used by Asqav attachments."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol, runtime_checkable

from autogen_core import CancellationToken

__all__ = ["Decision", "GuardrailResult", "GuardrailProvider"]


class Decision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    MODIFY = "modify"


@dataclass
class GuardrailResult:
    """Outcome of a guardrail evaluation."""

    decision: Decision
    reason: str | None = None
    modified_args: Mapping[str, Any] | None = None  # only when Decision.MODIFY
    metadata: dict[str, Any] = field(default_factory=dict)  # audit trail data


@runtime_checkable
class GuardrailProvider(Protocol):
    """Intercepts tool calls before execution for policy enforcement."""

    @abstractmethod
    async def evaluate(
        self,
        *,
        tool_name: str,
        args: Mapping[str, Any],
        agent_name: str | None = None,
        call_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> GuardrailResult:
        """Evaluate whether a tool call should proceed."""
        ...
